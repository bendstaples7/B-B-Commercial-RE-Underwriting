"""Property management API endpoints.

Provides endpoints for listing, filtering, and retrieving properties,
starting analysis sessions from properties, and managing scoring weights.

Renamed from lead_controller.py — the underlying `leads` table is unchanged.
"""
import logging
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, url_for
from marshmallow import ValidationError
from sqlalchemy import false, func, or_

from app import db, limiter
from app.api_utils import get_current_user_id, require_auth
from app.models import (
    AnalysisSession,
    Lead,
    LeadAuditTrail,
    LeadScore,
    MarketingListMember,
    ScoringWeights,
    WorkflowStep,
)
from app.models.contact import Contact
from app.models.property_contact import PropertyContact
from app.models.user import User
from app.schemas import LeadListQuerySchema
from app.services.lead_scoring_engine import LeadScoringEngine
from app.services.scoring_rubric import calculate_score_tier, display_most_recent_sale
from app.services import scoring_rubric as rubric

logger = logging.getLogger(__name__)

properties_bp = Blueprint('properties', __name__)
leads_legacy_bp = Blueprint('leads_legacy', __name__)

scoring_engine = LeadScoringEngine()

# ---------------------------------------------------------------------------
# Allowed filter / sort values
# ---------------------------------------------------------------------------

ALLOWED_SORT_FIELDS = {'lead_score', 'created_at', 'property_street'}
ALLOWED_SORT_ORDERS = {'asc', 'desc'}
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

# Deprecated flat contact columns that must NOT be written to the database
_DEPRECATED_CONTACT_FIELDS = {
    'owner_first_name', 'owner_last_name',
    'owner_2_first_name', 'owner_2_last_name',
    'phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7',
    'email_1', 'email_2', 'email_3', 'email_4', 'email_5',
}


def _current_user_is_admin() -> bool:
    """Return True when the currently authenticated user has is_admin=True.

    Uses g.is_admin set by require_auth (live DB lookup on every authenticated
    request). Falls back to querying the database only when g.is_admin is not
    set (e.g. during testing or legacy paths).

    Returns False on any error so ownership scoping is always enforced when
    admin status cannot be confirmed.
    """
    from flask import g
    try:
        # Fast path: use is_admin set by require_auth (live DB lookup)
        is_admin = getattr(g, 'is_admin', None)
        if is_admin is not None:
            return bool(is_admin)
        # Fallback: query database directly (legacy/test paths)
        user_id = getattr(g, 'user_id', None)
        if not user_id or user_id == 'anonymous':
            return False
        user = User.query.filter_by(user_id=user_id).first()
        return bool(user and user.is_admin)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code

            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pagination(args):
    """Extract and validate pagination parameters from query string."""
    try:
        page = int(args.get('page', DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        per_page = int(args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE

    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _latest_scores_by_lead_id(lead_ids: list[int]) -> dict[int, LeadScore]:
    """Batch-fetch the most recent LeadScore row per lead."""
    if not lead_ids:
        return {}
    subq = (
        db.session.query(
            LeadScore.lead_id,
            func.max(LeadScore.id).label('max_id'),
        )
        .filter(LeadScore.lead_id.in_(lead_ids))
        .group_by(LeadScore.lead_id)
        .subquery()
    )
    rows = (
        db.session.query(LeadScore)
        .join(subq, LeadScore.id == subq.c.max_id)
        .all()
    )
    return {row.lead_id: row for row in rows}


def _serialize_property_summary(lead, latest_score: LeadScore | None = None):
    """Serialize a Property (Lead) for list views — includes all spreadsheet fields."""
    score_tier = None
    data_quality_score = None
    top_signal = None
    missing_data: list[str] = []
    recommended_action = getattr(lead, 'recommended_action', None)
    recommended_contact_method = getattr(lead, 'recommended_contact_method', None)
    if latest_score is not None:
        score_tier = latest_score.score_tier
        data_quality_score = latest_score.data_quality_score
        missing_data = list(latest_score.missing_data or [])
        signals = latest_score.top_signals or []
        if signals:
            top_signal = signals[0].get('dimension')
    elif lead.lead_score:
        score_tier = calculate_score_tier(lead.lead_score)
        _, missing_data = rubric.calculate_data_quality_score(lead)

    data = {
        'id': lead.id,
        'lead_category': lead.lead_category,
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'property_type': lead.property_type,
        'bedrooms': lead.bedrooms,
        'bathrooms': lead.bathrooms,
        'square_footage': lead.square_footage,
        'lot_size': lead.lot_size,
        'year_built': lead.year_built,
        'units': lead.units,
        'units_allowed': lead.units_allowed,
        'zoning': lead.zoning,
        'county_assessor_pin': lead.county_assessor_pin,
        'tax_bill_2021': lead.tax_bill_2021,
        'most_recent_sale': lead.most_recent_sale,
        'most_recent_sale_display': display_most_recent_sale(lead),
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'owner_2_first_name': lead.owner_2_first_name,
        'owner_2_last_name': lead.owner_2_last_name,
        'ownership_type': lead.ownership_type,
        'acquisition_date': lead.acquisition_date.isoformat() if lead.acquisition_date else None,
        'phone_1': lead.phone_1,
        'phone_2': lead.phone_2,
        'phone_3': lead.phone_3,
        'phone_4': lead.phone_4,
        'phone_5': lead.phone_5,
        'phone_6': lead.phone_6,
        'phone_7': lead.phone_7,
        'email_1': lead.email_1,
        'email_2': lead.email_2,
        'email_3': lead.email_3,
        'email_4': lead.email_4,
        'email_5': lead.email_5,
        'socials': lead.socials,
        'mailing_address': lead.mailing_address,
        'mailing_city': lead.mailing_city,
        'mailing_state': lead.mailing_state,
        'mailing_zip': lead.mailing_zip,
        'address_2': lead.address_2,
        'returned_addresses': lead.returned_addresses,
        'source': lead.source,
        'deal_source': getattr(lead, 'deal_source', None),
        'deal_description': getattr(lead, 'deal_description', None),
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'needs_skip_trace': lead.needs_skip_trace,
        'skip_tracer': lead.skip_tracer,
        'date_skip_traced': lead.date_skip_traced.isoformat() if lead.date_skip_traced else None,
        'date_added_to_hubspot': lead.date_added_to_hubspot.isoformat() if lead.date_added_to_hubspot else None,
        'up_next_to_mail': lead.up_next_to_mail,
        'lead_score': lead.lead_score,
        'score_tier': score_tier,
        'data_quality_score': data_quality_score,
        'recommended_action': recommended_action,
        'recommended_contact_method': recommended_contact_method,
        'top_signal': top_signal,
        'missing_data': missing_data,
        'missing_data_count': len(missing_data),
        'data_source': lead.data_source,
        'source_type': lead.source_type,
        'owner_user_id': lead.owner_user_id,
        'created_at': lead.created_at.isoformat() if lead.created_at else None,
        'updated_at': lead.updated_at.isoformat() if lead.updated_at else None,
    }
    return data


def _serialize_property_detail(lead):
    """Serialize a Property (Lead) with full detail for the detail view."""
    data = {
        'id': lead.id,
        # Property details
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'property_type': lead.property_type,
        'bedrooms': lead.bedrooms,
        'bathrooms': lead.bathrooms,
        'square_footage': lead.square_footage,
        'lot_size': lead.lot_size,
        'year_built': lead.year_built,
        # Owner information (legacy flat columns — read-only after migration)
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'ownership_type': lead.ownership_type,
        'acquisition_date': lead.acquisition_date.isoformat() if lead.acquisition_date else None,
        'owner_2_first_name': lead.owner_2_first_name,
        'owner_2_last_name': lead.owner_2_last_name,
        # Contact information (legacy flat columns — read-only after migration)
        'phone_1': lead.phone_1,
        'phone_2': lead.phone_2,
        'phone_3': lead.phone_3,
        'email_1': lead.email_1,
        'email_2': lead.email_2,
        'phone_4': lead.phone_4,
        'phone_5': lead.phone_5,
        'phone_6': lead.phone_6,
        'phone_7': lead.phone_7,
        'email_3': lead.email_3,
        'email_4': lead.email_4,
        'email_5': lead.email_5,
        'socials': lead.socials,
        # Mailing information
        'mailing_address': lead.mailing_address,
        'mailing_city': lead.mailing_city,
        'mailing_state': lead.mailing_state,
        'mailing_zip': lead.mailing_zip,
        'address_2': lead.address_2,
        'returned_addresses': lead.returned_addresses,
        # Additional property details
        'units': lead.units,
        'units_allowed': lead.units_allowed,
        'zoning': lead.zoning,
        'county_assessor_pin': lead.county_assessor_pin,
        'tax_bill_2021': lead.tax_bill_2021,
        'most_recent_sale': lead.most_recent_sale,
        'most_recent_sale_display': display_most_recent_sale(lead),
        'sale_date_meta': rubric.resolve_sale_date_meta(lead),
        # Research tracking
        'source': lead.source,
        'deal_source': getattr(lead, 'deal_source', None),
        'deal_description': getattr(lead, 'deal_description', None),
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'notes': lead.notes,
        'needs_skip_trace': lead.needs_skip_trace,
        'skip_tracer': lead.skip_tracer,
        'date_skip_traced': lead.date_skip_traced.isoformat() if lead.date_skip_traced else None,
        'date_added_to_hubspot': lead.date_added_to_hubspot.isoformat() if lead.date_added_to_hubspot else None,
        # Mailing tracking
        'up_next_to_mail': lead.up_next_to_mail,
        'mailer_history': lead.mailer_history,
        # Scoring
        'lead_score': lead.lead_score,
        'motivation_score': getattr(lead, 'motivation_score', None),
        'motivation_signal_summary': getattr(lead, 'motivation_signal_summary', None) or [],
        # Classification
        'lead_category': lead.lead_category,
        # Metadata
        'data_source': lead.data_source,
        'last_import_job_id': lead.last_import_job_id,
        'created_at': lead.created_at.isoformat() if lead.created_at else None,
        'updated_at': lead.updated_at.isoformat() if lead.updated_at else None,
        # Analysis link
        'analysis_session_id': lead.analysis_session_id,
    }

    # Enrichment records
    enrichment_records = lead.enrichment_records.all()
    data['enrichment_records'] = [
        {
            'id': er.id,
            'data_source_id': er.data_source_id,
            'data_source_name': er.data_source.name if er.data_source else None,
            'status': er.status,
            'retrieved_data': er.retrieved_data,
            'error_reason': er.error_reason,
            'created_at': er.created_at.isoformat() if er.created_at else None,
        }
        for er in enrichment_records
    ]

    from app.services.motivation_signal_service import SIGNAL_LABELS
    active_signals = sorted(
        (sig for sig in lead.motivation_signals if sig.is_active),
        key=lambda s: abs(s.points),
        reverse=True,
    )
    data['motivation_signals'] = [
        {
            'id': sig.id,
            'signal_type': sig.signal_type,
            'label': SIGNAL_LABELS.get(sig.signal_type, sig.signal_type),
            'severity': sig.severity,
            'points': sig.points,
            'source': sig.source,
            'source_dataset': sig.source_dataset,
            'evidence': sig.evidence,
            'detected_at': sig.detected_at.isoformat() + 'Z' if sig.detected_at else None,
            'is_active': sig.is_active,
        }
        for sig in active_signals
    ]

    # Marketing list memberships
    memberships = lead.marketing_list_members.all()
    data['marketing_lists'] = [
        {
            'marketing_list_id': m.marketing_list_id,
            'marketing_list_name': m.marketing_list.name if m.marketing_list else None,
            'outreach_status': m.outreach_status,
            'added_at': m.added_at.isoformat() if m.added_at else None,
        }
        for m in memberships
    ]

    # Linked analysis session
    if lead.analysis_session:
        session = lead.analysis_session
        data['analysis_session'] = {
            'id': session.id,
            'session_id': session.session_id,
            'current_step': session.current_step.name,
            'created_at': session.created_at.isoformat() if session.created_at else None,
            'updated_at': session.updated_at.isoformat() if session.updated_at else None,
        }
    else:
        data['analysis_session'] = None

    # Contacts — authoritative owner/phone source (same shape as command center).
    # Serialize from the lead relationship so unit stubs without an app context still work.
    # Legacy flat owner_*/phone_* columns are not kept in sync by HubSpot enrichment.
    from app.services.contact_service import ContactService

    linked_pcs = (
        lead.property_contacts
        .order_by(PropertyContact.is_primary.desc(), PropertyContact.id.asc())
        .all()
    )
    data['contacts'] = [
        ContactService.serialize_contact_summary(pc.contact, pc)
        for pc in linked_pcs
        if pc.contact
    ]

    return data


def _serialize_scoring_weights(weights):
    """Serialize ScoringWeights to dictionary."""
    return {
        'id': weights.id,
        'user_id': weights.user_id,
        'property_characteristics_weight': weights.property_characteristics_weight,
        'data_completeness_weight': weights.data_completeness_weight,
        'owner_situation_weight': weights.owner_situation_weight,
        'location_desirability_weight': weights.location_desirability_weight,
        'data_enrichment_weight': weights.data_enrichment_weight,
        'created_at': weights.created_at.isoformat() if weights.created_at else None,
        'updated_at': weights.updated_at.isoformat() if weights.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Properties Blueprint Routes
# ---------------------------------------------------------------------------

@properties_bp.route('/', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def list_properties():
    """List properties with pagination, filtering, and sorting.

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 20, max 100)
    property_type : str — filter by property type (exact match)
    city : str — filter by mailing city (case-insensitive)
    state : str — filter by mailing state (case-insensitive)
    zip : str — filter by mailing zip (exact match)
    owner_name : str — filter by contact name via property_contacts join (case-insensitive partial match)
    score_min : float — minimum lead score
    score_max : float — maximum lead score
    marketing_list_id : int — filter by marketing list membership
    sort_by : str — one of lead_score, created_at, property_street
    sort_order : str — asc or desc (default desc)
    """
    args = request.args
    page, per_page = _parse_pagination(args)

    query = Lead.query

    # --- Ownership scope (security) ---
    # Non-admin users see only leads they own (exact match on owner_user_id).
    # Leads with owner_user_id IS NULL are not visible to non-admin users.
    # Unauthenticated requests see no leads.
    if not _current_user_is_admin():
        from flask import g
        current_user_id = getattr(g, 'user_id', None)
        if not current_user_id or current_user_id == 'anonymous':
            # Fail closed — anonymous callers see no leads
            query = query.filter(false())
        else:
            query = query.filter(Lead.owner_user_id == current_user_id)

    # --- Filters ---
    lead_category = args.get('lead_category')
    if lead_category:
        query = query.filter(Lead.lead_category == lead_category)

    property_type = args.get('property_type')
    if property_type:
        query = query.filter(Lead.property_type == property_type)

    city = args.get('city')
    if city:
        query = query.filter(Lead.mailing_city.ilike(city))

    state = args.get('state')
    if state:
        query = query.filter(Lead.mailing_state.ilike(state))

    zip_code = args.get('zip')
    if zip_code:
        query = query.filter(Lead.mailing_zip == zip_code)

    owner_name = args.get('owner_name')
    if owner_name:
        # Build a subquery for Contact-based matches (individual fields + full name)
        contact_subquery = (
            db.session.query(PropertyContact.property_id)
            .join(Contact, Contact.id == PropertyContact.contact_id)
            .filter(or_(
                Contact.first_name.ilike(f'%{owner_name}%'),
                Contact.last_name.ilike(f'%{owner_name}%'),
                func.concat(Contact.first_name, ' ', Contact.last_name).ilike(f'%{owner_name}%'),
            ))
            .subquery()
        )
        query = query.filter(or_(
            Lead.owner_first_name.ilike(f'%{owner_name}%'),
            Lead.owner_last_name.ilike(f'%{owner_name}%'),
            func.concat(Lead.owner_first_name, ' ', Lead.owner_last_name).ilike(f'%{owner_name}%'),
            Lead.id.in_(contact_subquery),
        ))

    score_min = args.get('score_min')
    if score_min is not None:
        try:
            query = query.filter(Lead.lead_score >= float(score_min))
        except (TypeError, ValueError):
            pass

    score_max = args.get('score_max')
    if score_max is not None:
        try:
            query = query.filter(Lead.lead_score <= float(score_max))
        except (TypeError, ValueError):
            pass

    marketing_list_id = args.get('marketing_list_id')
    if marketing_list_id is not None:
        try:
            ml_id = int(marketing_list_id)
            query = query.join(MarketingListMember).filter(
                MarketingListMember.marketing_list_id == ml_id,
            )
        except (TypeError, ValueError):
            pass

    # --- DuPage filters: source_type and owner_user_id ---
    # Use LeadListQuerySchema to validate and deserialize these two params.
    # Marshmallow's validate.OneOf on source_type raises ValidationError for
    # invalid values, which the @handle_errors decorator converts to 400.
    _schema = LeadListQuerySchema()
    _validated = _schema.load({
        k: v for k, v in args.items()
        if k in ('source_type', 'owner_user_id')
    })
    source_type = _validated.get('source_type')
    if source_type is not None:
        query = query.filter(Lead.source_type == source_type)

    owner_user_id = _validated.get('owner_user_id')
    if owner_user_id is not None:
        query = query.filter(Lead.owner_user_id == owner_user_id)

    # --- Sorting ---
    sort_by = args.get('sort_by', 'created_at')
    sort_order = args.get('sort_order', 'desc')

    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = 'created_at'
    if sort_order not in ALLOWED_SORT_ORDERS:
        sort_order = 'desc'

    sort_column = getattr(Lead, sort_by)
    if sort_order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # --- Pagination ---
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    lead_ids = [lead.id for lead in pagination.items]
    latest_scores = _latest_scores_by_lead_id(lead_ids)

    return jsonify({
        'leads': [
            _serialize_property_summary(lead, latest_scores.get(lead.id))
            for lead in pagination.items
        ],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }), 200


@properties_bp.route('/<int:lead_id>', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_property(lead_id):
    """Get full property detail including score, enrichment records, and analysis links."""
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Property not found',
            'message': f'Property {lead_id} does not exist',
        }), 404

    # Ownership check: non-admins can only access leads they own.
    # NULL-owner leads are not accessible to non-admin users.
    if not _current_user_is_admin():
        from flask import g
        current_user_id = getattr(g, 'user_id', None)
        is_authenticated = current_user_id and current_user_id != 'anonymous'
        if not is_authenticated or lead.owner_user_id != current_user_id:
            return jsonify({
                'error': 'Property not found',
                'message': f'Property {lead_id} does not exist',
            }), 404

    return jsonify(_serialize_property_detail(lead)), 200


@properties_bp.route('/<int:lead_id>/analyze', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def analyze_property(lead_id):
    """Create an AnalysisSession pre-populated from property data.

    Request body
    ------------
    user_id : str (required)

    Returns the new session details.
    """
    # Auth check first -- before lead lookup -- to prevent info leak.
    # Cache admin status so a transient failure during the DB read doesn't
    # produce inconsistent behaviour between the two checks.
    # Missing credentials return 400, not 404, so unauthenticated callers
    # cannot distinguish valid lead IDs.
    is_admin = _current_user_is_admin()
    current_user_id = None
    if not is_admin:
        from flask import g
        current_user_id = getattr(g, 'user_id', None)
        if not current_user_id or current_user_id == 'anonymous':
            return jsonify({
                'error': 'Validation error',
                'message': 'user_id is required (send X-User-Id header)',
            }), 400

    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Property not found',
            'message': f'Property {lead_id} does not exist',
        }), 404

    # Ownership check: non-admins can only access leads they own.
    # NULL-owner leads are not accessible to non-admin users.
    if not is_admin:
        is_authenticated = current_user_id and current_user_id != 'anonymous'
        if not is_authenticated or lead.owner_user_id != current_user_id:
            return jsonify({
                'error': 'Property not found',
                'message': f'Property {lead_id} does not exist',
            }), 404

    data = request.get_json() or {}
    user_id = get_current_user_id()
    if not user_id or user_id == 'anonymous':
        return jsonify({
            'error': 'Validation error',
            'message': 'user_id is required (send X-User-Id header)',
        }), 400
    session_id = str(uuid.uuid4())
    session = AnalysisSession(
        session_id=session_id,
        user_id=user_id,
        current_step=WorkflowStep.PROPERTY_FACTS,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(session)
    db.session.flush()  # get session.id

    # Link lead to the new session
    lead.analysis_session_id = session.id
    lead.updated_at = datetime.utcnow()

    db.session.commit()

    logger.info(
        "Created analysis session %s from property %d for user %s",
        session_id, lead_id, user_id,
    )

    return jsonify({
        'session_id': session_id,
        'lead_id': lead.id,
        'user_id': user_id,
        'current_step': session.current_step.name,
        'created_at': session.created_at.isoformat(),
        'pre_populated': {
            'address': lead.property_street,
            'property_type': lead.property_type,
            'bedrooms': lead.bedrooms,
            'bathrooms': lead.bathrooms,
            'square_footage': lead.square_footage,
            'lot_size': lead.lot_size,
            'year_built': lead.year_built,
        },
    }), 201


# ---------------------------------------------------------------------------
# View endpoint helpers
# ---------------------------------------------------------------------------


def _scoped_lead_query():
    """Return a Lead query scoped to the current user's owned leads.

    Admins see all leads. Non-admins only see leads they own.
    Anonymous/missing-user requests return no rows (fail closed).
    """
    query = Lead.query
    if _current_user_is_admin():
        return query

    from flask import g

    current_user_id = getattr(g, "user_id", None)
    if not current_user_id or current_user_id == "anonymous":
        return query.filter(false())
    return query.filter(Lead.owner_user_id == current_user_id)


# ---------------------------------------------------------------------------
# Property View Endpoints — deprecated; redirect to canonical queue API (301)
# ---------------------------------------------------------------------------

def _redirect_view_to_queue(queue_endpoint: str):
    """Legacy /api/properties/views/* → /api/queues/* with query string preserved."""
    base = url_for(queue_endpoint)
    query = request.query_string.decode()
    if query:
        return redirect(f'{base}?{query}', 301)
    return redirect(base, 301)


@properties_bp.route('/views/previously-warm', methods=['GET'])
@limiter.limit("30 per minute")
def view_previously_warm():
    return _redirect_view_to_queue('queue.get_previously_warm')


@properties_bp.route('/views/needs-review', methods=['GET'])
@limiter.limit("30 per minute")
def view_needs_review():
    return _redirect_view_to_queue('queue.get_needs_review')


@properties_bp.route('/views/follow-up-overdue', methods=['GET'])
@limiter.limit("30 per minute")
def view_follow_up_overdue():
    return _redirect_view_to_queue('queue.get_follow_up_overdue')


@properties_bp.route('/views/no-next-action', methods=['GET'])
@limiter.limit("30 per minute")
def view_no_next_action():
    return _redirect_view_to_queue('queue.get_no_next_action')


@properties_bp.route('/views/do-not-contact', methods=['GET'])
@limiter.limit("30 per minute")
def view_do_not_contact():
    return _redirect_view_to_queue('queue.get_do_not_contact')


@properties_bp.route('/views/missing-property-match', methods=['GET'])
@limiter.limit("30 per minute")
def view_missing_property_match():
    return _redirect_view_to_queue('queue.get_missing_property_match')


@properties_bp.route('/scoring/weights', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_scoring_weights():
    """Get current scoring weights for a user."""
    user_id = get_current_user_id()
    if not user_id or user_id == 'anonymous':
        return jsonify({
            'error': 'Validation error',
            'message': 'user_id is required (send X-User-Id header)',
        }), 400
    weights = scoring_engine.get_weights(user_id)
    return jsonify(_serialize_scoring_weights(weights)), 200


@properties_bp.route('/scoring/weights', methods=['PUT'])
@limiter.limit("10 per minute")
@handle_errors
def update_scoring_weights():
    """Update scoring weights and trigger bulk rescore."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    user_id = get_current_user_id()
    if not user_id or user_id == 'anonymous':
        return jsonify({
            'error': 'Validation error',
            'message': 'user_id is required (send X-User-Id header)',
        }), 400

    required_weight_fields = [
        'property_characteristics_weight',
        'data_completeness_weight',
        'owner_situation_weight',
        'location_desirability_weight',
        'data_enrichment_weight',
    ]
    for field in required_weight_fields:
        if field not in data:
            return jsonify({
                'error': 'Validation error',
                'message': f'{field} is required',
            }), 400
        try:
            float(data[field])
        except (TypeError, ValueError):
            return jsonify({
                'error': 'Validation error',
                'message': f'{field} must be a number',
            }), 400

    weights = scoring_engine.update_weights(
        user_id=user_id,
        property_characteristics_weight=float(data['property_characteristics_weight']),
        data_completeness_weight=float(data['data_completeness_weight']),
        owner_situation_weight=float(data['owner_situation_weight']),
        location_desirability_weight=float(data['location_desirability_weight']),
        data_enrichment_weight=float(data['data_enrichment_weight']),
    )

    rescored = scoring_engine.bulk_rescore(user_id=user_id)

    logger.info(
        "Updated scoring weights for user %s, rescored %d properties",
        user_id, rescored,
    )

    result = _serialize_scoring_weights(weights)
    result['leads_rescored'] = rescored

    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Legacy Redirect Blueprint — /api/leads/* → /api/properties/* (HTTP 301)
# ---------------------------------------------------------------------------

@leads_legacy_bp.route('/', methods=['GET'])
def legacy_list_properties():
    return redirect(url_for('properties.list_properties', **request.args), 301)


@leads_legacy_bp.route('/<int:lead_id>', methods=['GET'])
def legacy_get_property(lead_id):
    return redirect(url_for('properties.get_property', lead_id=lead_id), 301)


@leads_legacy_bp.route('/<int:lead_id>/analyze', methods=['POST'])
def legacy_analyze_property(lead_id):
    return redirect(url_for('properties.analyze_property', lead_id=lead_id), 308)


@leads_legacy_bp.route('/views/previously-warm', methods=['GET'])
def legacy_view_previously_warm():
    return _redirect_view_to_queue('queue.get_previously_warm')


@leads_legacy_bp.route('/views/needs-review', methods=['GET'])
def legacy_view_needs_review():
    return _redirect_view_to_queue('queue.get_needs_review')


@leads_legacy_bp.route('/views/follow-up-overdue', methods=['GET'])
def legacy_view_follow_up_overdue():
    return _redirect_view_to_queue('queue.get_follow_up_overdue')


@leads_legacy_bp.route('/views/no-next-action', methods=['GET'])
def legacy_view_no_next_action():
    return _redirect_view_to_queue('queue.get_no_next_action')


@leads_legacy_bp.route('/views/do-not-contact', methods=['GET'])
def legacy_view_do_not_contact():
    return _redirect_view_to_queue('queue.get_do_not_contact')


@leads_legacy_bp.route('/views/missing-property-match', methods=['GET'])
def legacy_view_missing_property_match():
    return _redirect_view_to_queue('queue.get_missing_property_match')


@leads_legacy_bp.route('/scoring/weights', methods=['GET'])
def legacy_get_scoring_weights():
    return redirect(url_for('properties.get_scoring_weights', **request.args), 301)


@leads_legacy_bp.route('/scoring/weights', methods=['PUT'])
def legacy_update_scoring_weights():
    return redirect(url_for('properties.update_scoring_weights'), 308)


# ---------------------------------------------------------------------------
# Backward-compatibility alias — other modules that import lead_bp
# ---------------------------------------------------------------------------

# lead_bp is kept as an alias so existing imports don't break during transition.
lead_bp = properties_bp
