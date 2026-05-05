"""Lead management API endpoints.

Provides endpoints for listing, filtering, and retrieving leads,
starting analysis sessions from leads, and managing scoring weights.
"""
import logging
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError
from sqlalchemy import or_

from app import db, limiter
from app.models import (
    AnalysisSession,
    Lead,
    LeadAuditTrail,
    MarketingListMember,
    ScoringWeights,
    WorkflowStep,
)
from app.services.lead_scoring_engine import LeadScoringEngine

logger = logging.getLogger(__name__)

lead_bp = Blueprint('leads', __name__)

scoring_engine = LeadScoringEngine()

# ---------------------------------------------------------------------------
# Allowed filter / sort values
# ---------------------------------------------------------------------------

ALLOWED_SORT_FIELDS = {'lead_score', 'created_at', 'property_street'}
ALLOWED_SORT_ORDERS = {'asc', 'desc'}
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


# ---------------------------------------------------------------------------
# Error handling decorator (mirrors routes.py pattern)
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


def _serialize_lead_summary(lead):
    """Serialize a Lead for list views — includes all spreadsheet fields."""
    return {
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
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'notes': lead.notes,
        'needs_skip_trace': lead.needs_skip_trace,
        'skip_tracer': lead.skip_tracer,
        'date_skip_traced': lead.date_skip_traced.isoformat() if lead.date_skip_traced else None,
        'date_added_to_hubspot': lead.date_added_to_hubspot.isoformat() if lead.date_added_to_hubspot else None,
        'up_next_to_mail': lead.up_next_to_mail,
        'mailer_history': lead.mailer_history,
        'lead_score': lead.lead_score,
        'data_source': lead.data_source,
        'created_at': lead.created_at.isoformat() if lead.created_at else None,
        'updated_at': lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _serialize_lead_detail(lead):
    """Serialize a Lead with full detail for the detail view."""
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
        # Owner information
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'ownership_type': lead.ownership_type,
        'acquisition_date': lead.acquisition_date.isoformat() if lead.acquisition_date else None,
        'owner_2_first_name': lead.owner_2_first_name,
        'owner_2_last_name': lead.owner_2_last_name,
        # Contact information
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
        # Research tracking
        'source': lead.source,
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
        'created_at': weights.created_at.isoformat() if weights.created_at else None,
        'updated_at': weights.updated_at.isoformat() if weights.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@lead_bp.route('/', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def list_leads():
    """List leads with pagination, filtering, and sorting.

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 20, max 100)
    property_type : str — filter by property type (exact match)
    city : str — filter by mailing city (case-insensitive)
    state : str — filter by mailing state (case-insensitive)
    zip : str — filter by mailing zip (exact match)
    owner_name : str — filter by owner name (case-insensitive partial match)
    score_min : float — minimum lead score
    score_max : float — maximum lead score
    marketing_list_id : int — filter by marketing list membership
    sort_by : str — one of lead_score, created_at, property_street
    sort_order : str — asc or desc (default desc)
    """
    args = request.args
    page, per_page = _parse_pagination(args)

    query = Lead.query

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
        query = query.filter(or_(
            Lead.owner_first_name.ilike(f'%{owner_name}%'),
            Lead.owner_last_name.ilike(f'%{owner_name}%'),
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

    return jsonify({
        'leads': [_serialize_lead_summary(lead) for lead in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }), 200


@lead_bp.route('/<int:lead_id>', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_lead(lead_id):
    """Get full lead detail including score, enrichment records, and analysis links."""
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Lead not found',
            'message': f'Lead {lead_id} does not exist',
        }), 404

    return jsonify(_serialize_lead_detail(lead)), 200


@lead_bp.route('/<int:lead_id>/analyze', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def analyze_lead(lead_id):
    """Create an AnalysisSession pre-populated from lead data.

    Request body
    ------------
    user_id : str (required)

    Returns the new session details.
    """
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Lead not found',
            'message': f'Lead {lead_id} does not exist',
        }), 404

    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({
            'error': 'Validation error',
            'message': 'user_id is required',
        }), 400

    # Create a new AnalysisSession
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
        "Created analysis session %s from lead %d for user %s",
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


@lead_bp.route('/scoring/weights', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_scoring_weights():
    """Get current scoring weights for a user.

    Query parameters
    ----------------
    user_id : str (default "default")
    """
    user_id = request.args.get('user_id', 'default')
    weights = scoring_engine.get_weights(user_id)
    return jsonify(_serialize_scoring_weights(weights)), 200


@lead_bp.route('/scoring/weights', methods=['PUT'])
@limiter.limit("10 per minute")
@handle_errors
def update_scoring_weights():
    """Update scoring weights and trigger bulk rescore.

    Request body
    ------------
    user_id : str (required)
    property_characteristics_weight : float (required)
    data_completeness_weight : float (required)
    owner_situation_weight : float (required)
    location_desirability_weight : float (required)
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    user_id = data.get('user_id')
    if not user_id:
        return jsonify({
            'error': 'Validation error',
            'message': 'user_id is required',
        }), 400

    required_weight_fields = [
        'property_characteristics_weight',
        'data_completeness_weight',
        'owner_situation_weight',
        'location_desirability_weight',
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

    # update_weights validates sum == 1.0 and non-negative
    weights = scoring_engine.update_weights(
        user_id=user_id,
        property_characteristics_weight=float(data['property_characteristics_weight']),
        data_completeness_weight=float(data['data_completeness_weight']),
        owner_situation_weight=float(data['owner_situation_weight']),
        location_desirability_weight=float(data['location_desirability_weight']),
    )

    # Trigger bulk rescore in the background.
    # In a production setup this would be enqueued as a Celery task.
    # For now we call it synchronously so the API remains functional
    # without requiring a running Celery worker.
    rescored = scoring_engine.bulk_rescore(user_id=user_id)

    logger.info(
        "Updated scoring weights for user %s, rescored %d leads",
        user_id, rescored,
    )

    result = _serialize_scoring_weights(weights)
    result['leads_rescored'] = rescored

    return jsonify(result), 200
