"""Command Center API endpoints.

Provides endpoints for the Actionable Lead Command Center feature,
including recommended action retrieval with signal breakdown.

Blueprint: command_center_bp, prefix /api/leads
"""
import logging
import re
from functools import wraps

from flask import Blueprint, jsonify, g, request
from marshmallow import ValidationError

from app.exceptions import RealEstateAnalysisException
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.schemas import (
    LeadTaskCreateSchema, LeadTaskUpdateSchema, LeadTaskSnoozeSchema,
    LogNoteSchema, LogCallSchema, LeadStatusUpdateSchema,
    ParkLeadSchema, DoNotContactSchema, ReactivateLeadSchema,
)
from app.services.lead_task_service import LeadTaskService
from app.services.lead_timeline_service import LeadTimelineService
from app.services.call_log_service import CallLogService
from app.services.action_engine_service import ActionEngineService, RECOMMENDED_ACTION_METADATA
from app.services.lead_scoring_engine import LeadScoringEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rescore helper — called after any status change so the pipeline stage bonus
# is immediately reflected in lead_score without waiting for a nightly batch.
# ---------------------------------------------------------------------------

def _rescore_after_status_change(lead_id: int) -> None:
    """Recompute lead_score and recommended_action after a pipeline stage change.

    The LeadScoringEngine._pipeline_stage_bonus varies per status, so score
    must be refreshed whenever lead_status is written.  Failures are non-fatal
    because the nightly bulk_rescore beat task is the safety net.
    """
    try:
        engine = LeadScoringEngine()
        engine.bulk_rescore(lead_ids=[lead_id])
        logger.info("_rescore_after_status_change: rescored lead_id=%d", lead_id)
    except Exception as exc:
        logger.warning(
            "_rescore_after_status_change: rescore failed for lead_id=%d: %s",
            lead_id, exc,
        )

command_center_bp = Blueprint('command_center', __name__)

# ---------------------------------------------------------------------------
# HubSpot pipeline stage label cache
# Translates internal stage IDs (e.g. 'closedlost') to portal display labels
# (e.g. 'Negotiating Remote'). Refreshed at most once every 5 minutes.
# ---------------------------------------------------------------------------
import time as _time

_stage_label_cache: dict = {}
_stage_label_cache_ts: float = 0.0
_STAGE_CACHE_TTL = 300  # seconds — successful refresh
_STAGE_CACHE_FAILURE_TTL = 30  # seconds — back-off after a failed refresh

# Keywords in lead.notes that suggest contact was made with the owner.
# Used to detect conflicts between notes content and lead_status.
_CONTACT_KEYWORDS = (
    'contact made', 'contacted', 'spoke with', 'spoke to', 'called',
    'reached out', 'talked to', 'talked with', 'answered', 'connected',
    'responded', 'replied', 'met with', 'meeting', 'email response',
)

# Statuses that imply no contact has been made
_NO_CONTACT_STATUSES = frozenset({'mailing_no_contact_made'})


def _detect_notes_status_conflict(notes: str | None, lead_status: str | None) -> bool:
    """Return True when lead.notes implies contact was made but status says otherwise.

    Checks for contact-indicating keywords in the notes text against a set of
    statuses that mean no contact has been made. Case-insensitive.
    """
    if not notes or not lead_status:
        return False
    if lead_status not in _NO_CONTACT_STATUSES:
        return False
    notes_lower = notes.lower()
    return any(kw in notes_lower for kw in _CONTACT_KEYWORDS)


def _resolve_actor(user_id_or_label: str | None, _cache: dict | None = None) -> str:
    """Resolve a user_id UUID to a human-readable display name.

    Looks up the User record by user_id and returns display_name if found,
    falls back to email, then the raw value. Non-UUID values (e.g. 'System',
    'HubSpot', 'anonymous') are returned as-is.

    Pass a dict as `_cache` to avoid repeated DB lookups within a single request
    (e.g. when resolving multiple actor IDs on a timeline page). The cache is
    keyed by user_id and stores the resolved display label.
    """
    if not user_id_or_label or user_id_or_label in ('anonymous', 'System', 'HubSpot'):
        return user_id_or_label or 'anonymous'
    # UUID format: 8-4-4-4-12 hex characters
    import re as _re
    if not _re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                     user_id_or_label, _re.IGNORECASE):
        return user_id_or_label  # not a UUID — return as-is
    if _cache is not None and user_id_or_label in _cache:
        return _cache[user_id_or_label]
    from app.models.user import User as _User
    user = _User.query.filter_by(user_id=user_id_or_label).first()
    resolved = (user.display_name or user.email) if user else user_id_or_label
    if _cache is not None:
        _cache[user_id_or_label] = resolved
    return resolved


def _resolve_actors_batch(user_ids: list[str]) -> dict[str, str]:
    """Batch-resolve a list of user_id UUIDs to display labels in one DB query.

    Returns a dict mapping each user_id to its resolved display label.
    Non-UUID values pass through unchanged. Use this before serializing
    a page of timeline entries to avoid N+1 queries.
    """
    import re as _re
    uuid_pattern = _re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        _re.IGNORECASE,
    )
    result: dict[str, str] = {}
    uuids = [uid for uid in set(user_ids) if uid and uuid_pattern.match(uid)]
    if uuids:
        from app.models.user import User as _User
        users = _User.query.filter(_User.user_id.in_(uuids)).all()
        found = {u.user_id: (u.display_name or u.email) for u in users}
        for uid in uuids:
            result[uid] = found.get(uid, uid)
    # Pass-through non-UUID values unchanged
    for uid in user_ids:
        if uid not in result:
            result[uid] = uid or 'anonymous'
    return result


def _get_stage_label(stage_id: str) -> str:
    """Translate a HubSpot deal stage ID to its portal display label.

    Falls back to the raw stage_id if the API call fails or the ID is unknown.
    Cache is refreshed at most every 5 minutes on success, 30 seconds on failure.
    """
    global _stage_label_cache, _stage_label_cache_ts
    now = _time.monotonic()
    if now - _stage_label_cache_ts > _STAGE_CACHE_TTL:
        try:
            from app.models.hubspot_config import HubSpotConfig as _HubSpotConfig
            from app.services.hubspot_client_service import HubSpotClientService as _HCS
            _config = _HubSpotConfig.query.order_by(_HubSpotConfig.id.desc()).first()
            if _config:
                _stage_label_cache = _HCS(_config).fetch_pipeline_stage_labels("deals")
                _stage_label_cache_ts = now
            else:
                # No config — defer next attempt by failure TTL
                logger.debug("_get_stage_label: no HubSpot config found")
                _stage_label_cache_ts = now - (_STAGE_CACHE_TTL - _STAGE_CACHE_FAILURE_TTL)
        except Exception as _exc:
            logger.debug("_get_stage_label: could not refresh stage map: %s", _exc)
            # Advance timestamp by failure TTL to avoid hammering the API on every request
            _stage_label_cache_ts = now - (_STAGE_CACHE_TTL - _STAGE_CACHE_FAILURE_TTL)
    return _stage_label_cache.get(stage_id, stage_id)

# ---------------------------------------------------------------------------
# Module-level service instances
# ---------------------------------------------------------------------------

_lead_task_service = LeadTaskService()
_lead_timeline_service = LeadTimelineService()
_call_log_service = CallLogService()


# ---------------------------------------------------------------------------
# Error handling decorator (mirrors property_controller.py pattern)
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
        except RealEstateAnalysisException as e:
            logger.warning("%s: %s", e.__class__.__name__, e.message)
            return jsonify({
                'error': e.__class__.__name__,
                'message': e.message,
                **e.payload,
            }), e.status_code
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
# Signal extraction helpers
# ---------------------------------------------------------------------------

def _get_winning_rule_signals(lead) -> dict:
    """
    Return the signal fields relevant to the winning rule that produced the
    lead's current recommended_action.

    Mirrors the 11-priority rule chain in ActionEngineService so the caller
    can see exactly which signals caused the current RA to be assigned.
    """
    ra = lead.recommended_action

    # Priority 1 — DNC
    if lead.lead_status == 'do_not_contact':
        return {'lead_status': 'do_not_contact'}

    # Priority 2 — suppressed / deprioritize / terminal (RA is None for these)
    if lead.lead_status in ('suppressed', 'deprioritize', 'deal_won', 'deal_lost'):
        return {'lead_status': lead.lead_status}

    # Priority 2.5 — skip trace statuses always need contact info
    if lead.lead_status in ('skip_trace', 'awaiting_skip_trace'):
        return {'lead_status': lead.lead_status, 'requires_skip_trace': True}

    # Priority 3 — no contact info
    if not lead.has_phone and not lead.has_email:
        return {'has_phone': False, 'has_email': False}

    # Priority 4 — no property match
    if not lead.has_property_match:
        return {
            'has_property_match': False,
            'property_street': lead.property_street,
        }

    # Priority 5 — follow-up overdue
    if lead.follow_up_overdue:
        return {'follow_up_overdue': True}

    # Priority 6 — warm lead
    if lead.is_warm:
        return {'is_warm': True}

    # Priority 7 — ready for outreach (high score + no open tasks)
    if lead.lead_score >= 70:
        open_tasks = LeadTask.query.filter_by(lead_id=lead.id, status='open').count()
        if open_tasks == 0:
            return {
                'lead_score': lead.lead_score,
            }

    # Priority 8 — has contact info, property matched, no tasks
    open_tasks = LeadTask.query.filter_by(lead_id=lead.id, status='open').count()
    if open_tasks == 0:
        return {'lead_status': lead.lead_status}

    # Priority 10 — active pipeline lead with no open tasks → create_task
    if lead.lead_status not in ('do_not_contact', 'suppressed', 'deprioritize', 'deal_won', 'deal_lost'):
        return {'lead_status': lead.lead_status}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@command_center_bp.route('/<int:lead_id>/recommended-action', methods=['GET'])
@handle_errors
def get_recommended_action(lead_id: int):
    """
    GET /api/leads/<lead_id>/recommended-action

    Returns the current recommended_action for a lead along with its
    human-readable label, explanation, and the signal fields that caused
    the winning rule to fire.

    Response schema (RecommendedActionResponseSchema — added in task 7.2):
    {
        "recommended_action": str | null,
        "label": str | null,
        "explanation": str | null,
        "signals": dict
    }
    """
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found', 'message': f'Lead {lead_id} not found'}), 404

    ra = lead.recommended_action
    metadata = RECOMMENDED_ACTION_METADATA.get(ra, {}) if ra else {}
    signals = _get_winning_rule_signals(lead)

    return jsonify({
        'recommended_action': ra,
        'label': metadata.get('label'),
        'explanation': metadata.get('explanation'),
        'signals': signals,
    }), 200


@command_center_bp.route('/<int:lead_id>/command-center', methods=['GET'])
@handle_errors
def get_command_center(lead_id: int):
    """
    GET /api/leads/<lead_id>/command-center

    Returns the full command center payload for a lead, including recommended
    action, open tasks, and the first page of the timeline.
    Clears the review_required flag when the command center is opened.
    """
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found', 'message': f'Lead {lead_id} not found'}), 404

    # Clear review_required flag when command center is opened
    if lead.review_required:
        lead.review_required = False
        from app import db
        db.session.add(lead)
        db.session.commit()

    ra = lead.recommended_action
    ra_metadata = RECOMMENDED_ACTION_METADATA.get(ra, {}) if ra else {}
    open_tasks = _lead_task_service.list_open(lead_id)
    timeline_entries, timeline_total = _lead_timeline_service.get_page(lead_id, page=1, per_page=25)

    # ------------------------------------------------------------------
    # Collect phones: flat columns + relational contact_phones table
    # ------------------------------------------------------------------
    from app import db as _db
    from sqlalchemy import text as _text

    # ------------------------------------------------------------------
    # Fetch HubSpot tasks linked to this lead (via task_associations or
    # direct lead_id FK) so they appear alongside native tasks in the UI.
    # Only tasks with source='hubspot_import' are shown as HubSpot tasks.
    # These are read-only — the user cannot complete/snooze them here.
    # ------------------------------------------------------------------
    hubspot_task_rows = _db.session.execute(_text("""
        SELECT t.id, t.title, t.status, t.due_date, t.created_at
        FROM tasks t
        JOIN task_associations ta ON ta.task_id = t.id
        WHERE ta.target_type = 'lead' AND ta.target_id = :lead_id
          AND t.status IN ('open', 'overdue')
          AND t.source = 'hubspot_import'
        UNION
        SELECT id, title, status, due_date, created_at
        FROM tasks
        WHERE lead_id = :lead_id
          AND status IN ('open', 'overdue')
          AND source = 'hubspot_import'
        ORDER BY due_date ASC NULLS LAST
    """), {'lead_id': lead_id}).fetchall()

    flat_phones = [
        p for p in [lead.phone_1, lead.phone_2, lead.phone_3,
                    lead.phone_4, lead.phone_5, lead.phone_6, lead.phone_7]
        if p and p.strip()
    ]
    relational_phones = [
        row[0] for row in _db.session.execute(_text("""
            SELECT cp.value FROM contact_phones cp
            JOIN property_contacts pc ON pc.contact_id = cp.contact_id
            WHERE pc.property_id = :lead_id
        """), {'lead_id': lead_id}).fetchall()
        if row[0]
    ]
    # Merge, deduplicate preserving order
    seen_phones: set = set()
    all_phones = []
    for p in flat_phones + relational_phones:
        normalized = p.strip()
        if normalized and normalized not in seen_phones:
            seen_phones.add(normalized)
            all_phones.append(normalized)

    # ------------------------------------------------------------------
    # Collect emails: flat columns + relational contact_emails table
    # ------------------------------------------------------------------
    flat_emails = [
        e for e in [lead.email_1, lead.email_2, lead.email_3,
                    lead.email_4, lead.email_5]
        if e and e.strip()
    ]
    relational_emails = [
        row[0] for row in _db.session.execute(_text("""
            SELECT ce.value FROM contact_emails ce
            JOIN property_contacts pc ON pc.contact_id = ce.contact_id
            WHERE pc.property_id = :lead_id
        """), {'lead_id': lead_id}).fetchall()
        if row[0]
    ]
    seen_emails: set = set()
    all_emails = []
    for e in flat_emails + relational_emails:
        normalized = e.strip().lower()
        if normalized and normalized not in seen_emails:
            seen_emails.add(normalized)
            all_emails.append(e.strip())

    # ------------------------------------------------------------------
    # Determine if this lead is in Today's Action queue
    # (has an overdue HubSpot task via task_associations or direct lead_id)
    # ------------------------------------------------------------------
    from datetime import datetime as _datetime_cls
    from datetime import datetime as _dt_cls
    _now = _dt_cls.utcnow()
    overdue_task_row = _db.session.execute(_text("""
        SELECT t.id, t.title, t.due_date
        FROM tasks t
        JOIN task_associations ta ON ta.task_id = t.id
        WHERE ta.target_type = 'lead' AND ta.target_id = :lead_id
          AND t.status IN ('open', 'overdue')
          AND t.due_date <= :now
        LIMIT 1
    """), {'lead_id': lead_id, 'now': _now}).fetchone()
    if not overdue_task_row:
        overdue_task_row = _db.session.execute(_text("""
            SELECT id, title, due_date FROM tasks
            WHERE lead_id = :lead_id AND status IN ('open', 'overdue') AND due_date <= :now
            LIMIT 1
        """), {'lead_id': lead_id, 'now': _now}).fetchone()
    has_overdue_hubspot_task = overdue_task_row is not None
    overdue_task_title = overdue_task_row[1] if overdue_task_row else None
    overdue_task_due = overdue_task_row[2].isoformat() if overdue_task_row and overdue_task_row[2] else None
    source = lead.source
    hubspot_deal_name = None
    # Look up live deal data for ANY lead that has a confirmed HubSpot deal
    # match — not just hubspot_import leads.  A lead imported from any source
    # (Driving for Dollars, DuPage GIS, Google Sheets, …) may later be
    # matched to a HubSpot deal, and that live stage/name should always show.
    # The stage is read from properties.dealstage (nested JSON), not the
    # top-level key which is always null in the stored payload structure.
    # Stage IDs are translated to display labels via the portal's pipeline API.
    row = _db.session.execute(_text("""
        SELECT hd.raw_payload->'properties'->>'dealname' AS dealname,
               hd.raw_payload->'properties'->>'dealstage' AS dealstage
        FROM hubspot_deals hd
        JOIN hubspot_matches hm ON hm.hubspot_id = hd.hubspot_id
            AND hm.hubspot_record_type = 'deal'
        WHERE hm.internal_record_id = :lead_id
            AND hm.internal_record_type = 'lead'
            AND hm.status = 'confirmed'
        LIMIT 1
    """), {'lead_id': lead_id}).fetchone()
    # Live deal data takes precedence over the stale stored column.
    # Translate the raw stage ID to the portal's display label.
    live_deal_stage = None
    if row:
        if row[0]:
            hubspot_deal_name = row[0]
        if row[1]:
            raw_stage_id = row[1]
            # Translate stage ID to display label using a module-level cache
            # (refreshed every 5 minutes to pick up portal changes without
            # hitting the HubSpot API on every request).
            live_deal_stage = _get_stage_label(raw_stage_id)
            # Only persist when we got a genuine translation (not the fallback
            # where the cache returned the raw ID unchanged). Persisting the raw
            # ID would overwrite a previously stored human-readable label.
            if live_deal_stage and live_deal_stage != raw_stage_id:
                if lead.hubspot_deal_stage != live_deal_stage:
                    lead.hubspot_deal_stage = live_deal_stage
                    _db.session.add(lead)
                    _db.session.commit()

    # ------------------------------------------------------------------
    # HubSpot interactions (calls, emails, notes from HubSpot import)
    # ------------------------------------------------------------------
    hs_interactions = _db.session.execute(_text("""
        SELECT i.interaction_type, i.occurred_at, i.body, i.source
        FROM interactions i
        JOIN interaction_associations ia ON ia.interaction_id = i.id
        WHERE ia.target_type = 'lead' AND ia.target_id = :lead_id
        ORDER BY i.occurred_at DESC
        LIMIT 50
    """), {'lead_id': lead_id}).fetchall()

    # ------------------------------------------------------------------
    # Marketing list membership
    # ------------------------------------------------------------------
    marketing_memberships = _db.session.execute(_text("""
        SELECT ml.name, mlm.outreach_status, mlm.added_at, mlm.status_updated_at
        FROM marketing_list_members mlm
        JOIN marketing_lists ml ON ml.id = mlm.marketing_list_id
        WHERE mlm.lead_id = :lead_id
        ORDER BY mlm.added_at DESC
    """), {'lead_id': lead_id}).fetchall()

    return jsonify({
        'id': lead.id,
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'owner_2_first_name': lead.owner_2_first_name,
        'owner_2_last_name': lead.owner_2_last_name,
        # Property details
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'property_type': lead.property_type,
        'bedrooms': lead.bedrooms,
        'bathrooms': lead.bathrooms,
        'square_footage': lead.square_footage,
        'year_built': lead.year_built,
        'county_assessor_pin': lead.county_assessor_pin,
        # Mailing address
        'mailing_address': lead.mailing_address,
        'mailing_city': lead.mailing_city,
        'mailing_state': lead.mailing_state,
        'mailing_zip': lead.mailing_zip,
        # Contact info — flat columns (kept for backward compat) + merged lists
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
        # Merged deduplicated lists (flat + relational)
        'phones': all_phones,
        'emails': all_emails,
        # Ownership
        'ownership_type': lead.ownership_type,
        'acquisition_date': lead.acquisition_date.isoformat() if lead.acquisition_date else None,
        # Source / metadata
        'source': source,
        'hubspot_deal_name': hubspot_deal_name,
        'lead_category': lead.lead_category,
        'notes': lead.notes,
        # Flag when lead.notes content implies contact was made but status says otherwise.
        # Used by the frontend to show a warning banner nudging the user to update status.
        'notes_status_conflict': _detect_notes_status_conflict(lead.notes, lead.lead_status),
        'date_added_to_hubspot': lead.date_added_to_hubspot.isoformat() if lead.date_added_to_hubspot else None,
        # Overdue HubSpot task — drives Today's Action queue membership
        'has_overdue_hubspot_task': has_overdue_hubspot_task,
        'overdue_task_title': overdue_task_title,
        'overdue_task_due': overdue_task_due,
        # Additional property fields
        'lot_size': lead.lot_size,
        'units': lead.units,
        'units_allowed': lead.units_allowed,
        'zoning': lead.zoning,
        'tax_bill_2021': lead.tax_bill_2021,
        'most_recent_sale': lead.most_recent_sale,
        'address_2': lead.address_2,
        'returned_addresses': lead.returned_addresses,
        # Research / workflow tracking
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'needs_skip_trace': lead.needs_skip_trace,
        'skip_tracer': lead.skip_tracer,
        'date_skip_traced': lead.date_skip_traced.isoformat() if lead.date_skip_traced else None,
        'up_next_to_mail': lead.up_next_to_mail,
        'mailer_history': lead.mailer_history,
        'data_source': lead.data_source,
        'created_at': lead.created_at.isoformat() if lead.created_at else None,
        # Outreach signals
        'socials': lead.socials,
        'unanswered_call_count': lead.unanswered_call_count,
        'follow_up_date': lead.follow_up_date.isoformat() if lead.follow_up_date else None,
        'suppression_flag': lead.suppression_flag,
        # Scores / flags
        'lead_score': lead.lead_score,
        'lead_status': lead.lead_status,
        'has_property_match': lead.has_property_match,
        'has_phone': lead.has_phone,
        'has_email': lead.has_email,
        'is_warm': lead.is_warm,
        'follow_up_overdue': lead.follow_up_overdue,
        'analysis_complete': lead.analysis_complete,
        'data_completeness_score': lead.data_completeness_score,
        'analysis_session_id': lead.analysis_session_id,
        'last_contact_date': lead.last_contact_date.isoformat() if lead.last_contact_date else None,
        'last_hubspot_sync_at': lead.last_hubspot_sync_at.isoformat() if lead.last_hubspot_sync_at else None,
        'hubspot_deal_stage': live_deal_stage or lead.hubspot_deal_stage,
        'review_required': lead.review_required,
        'review_reason': lead.review_reason,
        'recommended_action': {
            'value': ra,
            'label': ra_metadata.get('label'),
            'explanation': ra_metadata.get('explanation'),
            'signals': _get_winning_rule_signals(lead),
        },
        'open_tasks': [
            {
                'id': t.id,
                'task_type': t.task_type,
                'title': t.title,
                'status': t.status,
                'due_date': t.due_date.isoformat() if t.due_date else None,
                'created_at': t.created_at.isoformat(),
                'completed_at': t.completed_at.isoformat() if t.completed_at else None,
                'created_by': t.created_by,
                'source': 'native',
            }
            for t in open_tasks
        ] + [
            {
                'id': f'hs-{row[0]}',  # prefix to avoid ID collision with native tasks
                'task_type': 'custom',
                'title': row[1] or 'HubSpot Task',
                'status': row[2],
                'due_date': row[3].strftime('%Y-%m-%d') if row[3] else None,
                'created_at': row[4].isoformat() if row[4] else None,
                'completed_at': None,
                'created_by': 'HubSpot',
                'source': 'hubspot',
            }
            for row in hubspot_task_rows
        ],
        'timeline': {
            'entries': sorted(
                [
                    # Pre-resolve all actor UUIDs in one batch query to avoid N+1
                    # The batch result is computed just before the list comprehension
                ] if False else
                (lambda actor_cache: [
                    {
                        'id': e.id,
                        'event_type': e.event_type,
                        'occurred_at': e.occurred_at.isoformat(),
                        'source': e.source,
                        'actor': _resolve_actor(e.actor, actor_cache),
                        'summary': e.summary,
                        'metadata': e.event_metadata,
                        'hubspot_activity_id': e.hubspot_activity_id,
                    }
                    for e in timeline_entries
                ])(
                    # Build the actor cache once for the whole page
                    _resolve_actors_batch([e.actor for e in timeline_entries if e.actor])
                ) + [
                    # Inject HubSpot interactions as synthetic timeline entries
                    {
                        'id': -(i + 1),  # negative IDs to avoid collision
                        'event_type': row[0] or 'hubspot_activity',
                        'occurred_at': row[1].isoformat() if row[1] else '',
                        'source': 'hubspot_import',
                        'actor': 'HubSpot',
                        'summary': re.sub(r'<[^>]+>', ' ', row[2] or '').strip()[:500] if row[2] else '',
                        'metadata': None,
                        'hubspot_activity_id': None,
                    }
                    for i, row in enumerate(hs_interactions)
                ] + (
                    # Inject mailer history as a single timeline entry if present
                    [{
                        'id': -9999,
                        'event_type': 'mailer_history',
                        'occurred_at': lead.created_at.isoformat() if lead.created_at else '',
                        'source': 'manual',
                        'actor': 'System',
                        'summary': f"Mailer history: {lead.mailer_history}",
                        'metadata': None,
                        'hubspot_activity_id': None,
                    }] if lead.mailer_history else []
                ),
                key=lambda e: e['occurred_at'],
                reverse=True,
            ),
            'total': timeline_total + len(hs_interactions) + (1 if lead.mailer_history else 0),
            'page': 1,
            'per_page': 25,
        },
        # HubSpot interaction history (calls, emails, notes)
        'hubspot_interactions': [
            {
                'type': row[0],
                'occurred_at': row[1].isoformat() if row[1] else None,
                'body': row[2],
                'source': row[3],
            }
            for row in hs_interactions
        ],
        # Marketing list membership
        'marketing_memberships': [
            {
                'list_name': row[0],
                'outreach_status': row[1],
                'added_at': row[2].isoformat() if row[2] else None,
                'status_updated_at': row[3].isoformat() if row[3] else None,
            }
            for row in marketing_memberships
        ],
    }), 200


@command_center_bp.route('/<int:lead_id>/status', methods=['PATCH'])
@handle_errors
def update_status(lead_id: int):
    """
    PATCH /api/leads/<lead_id>/status

    Update the lead_status of a lead. Handles DNC and suppressed special cases
    (null RA, cancel open tasks). Appends a status_changed timeline entry.
    Triggers RA recomputation for non-terminal statuses.
    """
    from app import db
    import datetime as _dt

    data = LeadStatusUpdateSchema().load(request.get_json() or {})
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    old_status = lead.lead_status
    new_status = data['status']
    reason = data.get('reason') or ''
    actor_raw = getattr(g, 'user_id', None) or data.get('actor') or 'anonymous'

    lead.lead_status = new_status

    # DNC special case: set RA to null, cancel all open tasks
    if new_status == 'do_not_contact':
        lead.recommended_action = None
        LeadTask.query.filter_by(lead_id=lead_id, status='open').update({'status': 'cancelled'})
    elif new_status == 'suppressed':
        lead.recommended_action = None

    db.session.add(lead)

    # Build summary — include reason when provided (Requirements 2.5)
    if reason:
        summary = f"Status changed from '{old_status}' to '{new_status}'. {reason}"
    else:
        summary = f"Status changed from '{old_status}' to '{new_status}'."

    # Append status_changed timeline entry — store raw actor_raw (canonical user_id)
    # so the DB retains the canonical ID; _resolve_actor is called at read/serialization time
    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor_raw,
        summary=summary,
        event_metadata={
            'previous_status': old_status,
            'new_status': new_status,
            'reason': reason or None,
        },
    )
    db.session.add(entry)
    db.session.commit()

    # Trigger RA recomputation (unless DNC/suppressed)
    if new_status not in ('do_not_contact', 'suppressed'):
        try:
            ActionEngineService.recompute_and_persist(lead_id)
        except Exception as exc:
            logger.exception(
                "ActionEngineService.recompute_and_persist failed for lead %s after status update: %s",
                lead_id, exc,
            )

    # Rescore — pipeline stage bonus changes with every status transition
    _rescore_after_status_change(lead_id)

    return jsonify({'lead_status': lead.lead_status, 'recommended_action': lead.recommended_action}), 200


@command_center_bp.route('/<int:lead_id>/tasks', methods=['POST'])
@handle_errors
def create_task(lead_id: int):
    """
    POST /api/leads/<lead_id>/tasks

    Create a new LeadTask for a lead.
    """
    data = LeadTaskCreateSchema().load(request.get_json() or {})
    actor = getattr(g, 'user_id', 'anonymous')
    task = _lead_task_service.create(lead_id, data, actor=actor)
    return jsonify({
        'id': task.id,
        'task_type': task.task_type,
        'title': task.title,
        'status': task.status,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'created_at': task.created_at.isoformat(),
        'created_by': task.created_by,
    }), 201


@command_center_bp.route('/<int:lead_id>/tasks/<int:task_id>', methods=['PATCH'])
@handle_errors
def update_task(lead_id: int, task_id: int):
    """
    PATCH /api/leads/<lead_id>/tasks/<task_id>

    Snooze (if new_due_date present) or update a task's title/due_date.
    """
    actor = getattr(g, 'user_id', 'anonymous')
    body = request.get_json() or {}
    if 'new_due_date' in body:
        data = LeadTaskSnoozeSchema().load(body)
        task = _lead_task_service.snooze(task_id, lead_id, data['new_due_date'], actor=actor)
    else:
        data = LeadTaskUpdateSchema().load(body)
        from app import db
        task = LeadTask.query.filter_by(id=task_id, lead_id=lead_id).first()
        if task is None:
            return jsonify({'error': 'Not found'}), 404
        if 'title' in data:
            task.title = data['title']
        if 'due_date' in data:
            task.due_date = data['due_date']
        db.session.add(task)
        db.session.commit()
    return jsonify({
        'id': task.id,
        'title': task.title,
        'status': task.status,
        'due_date': task.due_date.isoformat() if task.due_date else None,
    }), 200


@command_center_bp.route('/<int:lead_id>/tasks/<int:task_id>/complete', methods=['POST'])
@handle_errors
def complete_task(lead_id: int, task_id: int):
    """
    POST /api/leads/<lead_id>/tasks/<task_id>/complete

    Mark a LeadTask as completed.
    """
    actor = getattr(g, 'user_id', 'anonymous')
    task = _lead_task_service.complete(task_id, lead_id, actor=actor)
    return jsonify({
        'id': task.id,
        'status': task.status,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
    }), 200


@command_center_bp.route('/<int:lead_id>/timeline', methods=['GET'])
@handle_errors
def get_timeline(lead_id: int):
    """
    GET /api/leads/<lead_id>/timeline

    Returns a paginated page of timeline entries in reverse-chronological order.
    Clears the review_required flag when the timeline is viewed.
    """
    from app import db

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))

    # Clear review_required flag when timeline is viewed
    lead = Lead.query.get(lead_id)
    if lead and lead.review_required:
        lead.review_required = False
        db.session.add(lead)
        db.session.commit()

    entries, total = _lead_timeline_service.get_page(lead_id, page=page, per_page=per_page)
    actor_cache = _resolve_actors_batch([e.actor for e in entries if e.actor])
    return jsonify({
        'entries': [
            {
                'id': e.id,
                'event_type': e.event_type,
                'occurred_at': e.occurred_at.isoformat(),
                'source': e.source,
                'actor': _resolve_actor(e.actor, actor_cache),
                'summary': e.summary,
                'metadata': e.event_metadata,
                'hubspot_activity_id': e.hubspot_activity_id,
            }
            for e in entries
        ],
        'total': total,
        'page': page,
        'per_page': per_page,
    }), 200


@command_center_bp.route('/<int:lead_id>/notes', methods=['POST'])
@handle_errors
def log_note(lead_id: int):
    """
    POST /api/leads/<lead_id>/notes

    Log a free-text note on a lead.
    """
    data = LogNoteSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    entry = _call_log_service.log_note(lead_id, data['body'], actor=actor)
    return jsonify({
        'id': entry.id,
        'event_type': entry.event_type,
        'occurred_at': entry.occurred_at.isoformat(),
    }), 201


@command_center_bp.route('/<int:lead_id>/calls', methods=['POST'])
@handle_errors
def log_call(lead_id: int):
    """
    POST /api/leads/<lead_id>/calls

    Log a call on a lead with outcome, optional duration, and optional notes.
    """
    data = LogCallSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    entry = _call_log_service.log_call(
        lead_id,
        data['outcome'],
        data.get('duration_minutes'),
        data.get('notes'),
        actor=actor,
    )
    return jsonify({
        'id': entry.id,
        'event_type': entry.event_type,
        'occurred_at': entry.occurred_at.isoformat(),
    }), 201


@command_center_bp.route('/<int:lead_id>/do-not-contact', methods=['POST'])
@handle_errors
def do_not_contact(lead_id: int):
    """
    POST /api/leads/<lead_id>/do-not-contact

    Mark a lead as Do Not Contact. Sets RA to null and cancels all open tasks.
    """
    import datetime as _dt
    from app import db

    data = DoNotContactSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    old_status = lead.lead_status
    lead.lead_status = 'do_not_contact'
    lead.recommended_action = None
    LeadTask.query.filter_by(lead_id=lead_id, status='open').update({'status': 'cancelled'})

    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor,
        summary=f"Status changed from '{old_status}' to 'do_not_contact'.",
        event_metadata={'previous_status': old_status, 'new_status': 'do_not_contact'},
    )
    db.session.add(lead)
    db.session.add(entry)
    db.session.commit()

    _rescore_after_status_change(lead_id)

    return jsonify({'lead_status': 'do_not_contact', 'recommended_action': None}), 200


@command_center_bp.route('/<int:lead_id>/park', methods=['POST'])
@handle_errors
def park_lead(lead_id: int):
    """
    POST /api/leads/<lead_id>/park

    Park a lead by setting its status to 'nurture'. Optionally sets a
    reactivation_date (must be a future date, max 365 days from today).
    """
    import datetime as _dt
    from datetime import date, timedelta
    from app import db

    data = ParkLeadSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    reactivation_date = data.get('reactivation_date')

    if reactivation_date:
        today = date.today()
        if reactivation_date <= today:
            return jsonify({'error': 'reactivation_date must be a future date'}), 400
        if reactivation_date > today + timedelta(days=365):
            return jsonify({'error': 'reactivation_date cannot be more than 365 days from today'}), 400

    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    old_status = lead.lead_status
    lead.lead_status = 'deprioritize'
    if reactivation_date:
        lead.follow_up_date = reactivation_date

    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor,
        summary="Lead parked (status: deprioritize).",
        event_metadata={
            'previous_status': old_status,
            'new_status': 'deprioritize',
            'reactivation_date': reactivation_date.isoformat() if reactivation_date else None,
        },
    )
    db.session.add(lead)
    db.session.add(entry)
    db.session.commit()

    # Recompute RA — nurture leads get RA=null per Priority 2
    try:
        ActionEngineService.recompute_and_persist(lead_id)
    except Exception as exc:
        logger.exception(
            "ActionEngineService.recompute_and_persist failed for lead %s after park: %s",
            lead_id, exc,
        )

    _rescore_after_status_change(lead_id)

    return jsonify({'lead_status': 'deprioritize'}), 200


@command_center_bp.route('/<int:lead_id>/reactivate', methods=['POST'])
@handle_errors
def reactivate_lead(lead_id: int):
    """
    POST /api/leads/<lead_id>/reactivate

    Reactivate a DNC or suppressed lead by setting its status to 'active'.
    Triggers RA recomputation.
    """
    import datetime as _dt
    from app import db

    data = ReactivateLeadSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    old_status = lead.lead_status
    lead.lead_status = 'mailing_no_contact_made'

    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor,
        summary="Lead reactivated (status: mailing_no_contact_made).",
        event_metadata={'previous_status': old_status, 'new_status': 'mailing_no_contact_made'},
    )
    db.session.add(lead)
    db.session.add(entry)
    db.session.commit()

    try:
        ActionEngineService.recompute_and_persist(lead_id)
    except Exception as exc:
        logger.exception(
            "ActionEngineService.recompute_and_persist failed for lead %s after reactivation: %s",
            lead_id, exc,
        )

    _rescore_after_status_change(lead_id)

    return jsonify({'lead_status': 'mailing_no_contact_made', 'recommended_action': lead.recommended_action}), 200


@command_center_bp.route('/<int:lead_id>/suppress', methods=['POST'])
@handle_errors
def suppress_lead(lead_id: int):
    """
    POST /api/leads/<lead_id>/suppress

    Suppress a lead by setting its status to 'suppressed' and nulling the RA.
    """
    import datetime as _dt
    from app import db

    data = DoNotContactSchema().load(request.get_json() or {})
    actor = data.get('actor') or getattr(g, 'user_id', 'anonymous')
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    old_status = lead.lead_status
    lead.lead_status = 'suppressed'
    lead.recommended_action = None

    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor,
        summary="Lead suppressed.",
        event_metadata={'previous_status': old_status, 'new_status': 'suppressed'},
    )
    db.session.add(lead)
    db.session.add(entry)
    db.session.commit()

    _rescore_after_status_change(lead_id)

    return jsonify({'lead_status': 'suppressed', 'recommended_action': None}), 200


@command_center_bp.route('/<int:lead_id>/hubspot-tasks/<int:task_id>/done', methods=['POST'])
@handle_errors
def mark_hubspot_task_done(lead_id: int, task_id: int):
    """
    POST /api/leads/<lead_id>/hubspot-tasks/<task_id>/done

    Mark a HubSpot-imported task as completed — both locally and in HubSpot.
    Looks up the task's hubspot_task_id, calls PATCH /crm/v3/objects/tasks/<id>
    to set hs_task_status=COMPLETED, then marks it done in the local DB.

    If the HubSpot API call fails (no config, auth error, rate limit, etc.),
    the task is still marked done locally and a warning is noted in the timeline.
    """
    import datetime as _dt
    from app import db

    actor = getattr(g, 'user_id', 'anonymous')
    now = _dt.datetime.now(_dt.timezone.utc)

    # Atomically mark the task completed only if it is still open/overdue
    # and linked to this lead. UPDATE ... RETURNING eliminates the SELECT
    # then UPDATE race condition where two concurrent requests could both
    # pass the SELECT check and both write timeline entries.
    result = db.session.execute(
        db.text("""
            UPDATE tasks
            SET status = 'completed',
                updated_at = NOW(),
                completion_timestamp = NOW()
            WHERE id = :task_id
              AND status IN ('open', 'overdue')
              AND (
                lead_id = :lead_id
                OR EXISTS (
                    SELECT 1 FROM task_associations ta
                    WHERE ta.task_id = tasks.id
                      AND ta.target_type = 'lead'
                      AND ta.target_id = :lead_id
                )
              )
            RETURNING id, title, hubspot_task_id
        """),
        {'task_id': task_id, 'lead_id': lead_id}
    ).fetchone()

    if result is None:
        db.session.rollback()
        return jsonify({'error': 'Not found', 'message': f'Task {task_id} not found or already completed for lead {lead_id}'}), 404

    task_title = result[1]
    hubspot_task_id = result[2]

    # Commit the local status change BEFORE calling HubSpot so the DB write
    # is durable regardless of external call outcome.
    db.session.commit()

    # --- Attempt to sync completion back to HubSpot ---
    hubspot_synced = False
    hubspot_error = None
    if hubspot_task_id:
        try:
            from app.models.hubspot_config import HubSpotConfig as _HubSpotConfig
            from app.services.hubspot_client_service import HubSpotClientService as _HCS
            config = _HubSpotConfig.query.order_by(_HubSpotConfig.id.desc()).first()
            if config:
                _HCS(config).complete_task(hubspot_task_id)
                hubspot_synced = True
                logger.info("HubSpot task %s marked COMPLETED for lead %s", hubspot_task_id, lead_id)
            else:
                hubspot_error = 'HubSpot sync failed'
        except Exception as exc:
            # Log full exception to server logs; expose only a sanitized marker to the user
            logger.warning(
                "Failed to mark HubSpot task %s as completed for lead %s: %s",
                hubspot_task_id, lead_id, exc,
            )
            hubspot_error = 'HubSpot sync failed'

    # Build timeline summary based on sync outcome
    if hubspot_synced:
        summary = f"HubSpot task completed: {task_title}"
        metadata_note = 'Marked done in HubSpot and locally'
    elif hubspot_task_id and hubspot_error:
        summary = f"HubSpot task marked done locally: {task_title} (HubSpot sync failed)"
        metadata_note = 'Local only — HubSpot sync failed'
    else:
        summary = f"HubSpot task marked done locally: {task_title}"
        metadata_note = 'Marked done locally — no HubSpot config'

    # Store raw actor_raw (canonical user_id) — resolved to display_name at read time
    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='task_completed',
        occurred_at=now,
        source='manual',
        actor=actor,
        summary=summary,
        event_metadata={
            'task_id': task_id,
            'hubspot_task_id': hubspot_task_id,
            'title': task_title,
            'hubspot_synced': hubspot_synced,
            'note': metadata_note,
        },
    )
    db.session.add(entry)
    db.session.commit()

    # Trigger RA recomputation — lead may leave Today's Action queue
    try:
        ActionEngineService.recompute_and_persist(lead_id)
    except Exception as exc:
        logger.exception(
            "ActionEngineService.recompute_and_persist failed for lead %s after hubspot task done: %s",
            lead_id, exc,
        )

    return jsonify({
        'task_id': task_id,
        'status': 'completed',
        'hubspot_synced': hubspot_synced,
        'hubspot_task_id': hubspot_task_id,
    }), 200
