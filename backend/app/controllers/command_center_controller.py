"""Command Center API endpoints.

Provides endpoints for the Actionable Lead Command Center feature,
including recommended action retrieval with signal breakdown.

Blueprint: command_center_bp, prefix /api/leads
"""
import logging
import os
from functools import wraps

from flask import Blueprint, jsonify, g, request
from marshmallow import ValidationError

from app.api_utils import require_auth
from app.exceptions import RealEstateAnalysisException
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.schemas import (
    LeadTaskCreateSchema, LeadTaskUpdateSchema, LeadTaskSnoozeSchema,
    LogNoteSchema, LogCallSchema, LeadStatusUpdateSchema,
    ParkLeadSchema, DoNotContactSchema, ReactivateLeadSchema,
    LeadTimelineEntrySchema,
)
from app.services.lead_task_service import LeadTaskService
from app.services.lead_timeline_service import LeadTimelineService
from app.services.call_log_service import CallLogService
from app.services.recommended_action_metadata import (
    RECOMMENDED_ACTION_METADATA,
    get_recommended_action_display,
    get_winning_rule_label,
)
from app.services.outreach_method_service import resolve_outreach_contact
from app.services.lead_scoring_engine import LeadScoringEngine
from app.services.mail_task_lifecycle_service import (
    recent_sale_mail_eligible_date,
    resolve_mail_queue_status,
)
from app.services.open_letter_contact_mapper import is_owner_mailable_lead
from app.services.scoring_rubric import (
    contacts_likely_prior_owner,
    contacts_stale_since,
    display_most_recent_sale,
    resolve_sale_date_meta,
)
from app.services.plugins.cook_county_assessor import list_parcel_sale_history

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rescore helper — called after any status change so the pipeline stage bonus
# is immediately reflected in lead_score without waiting for a nightly batch.
# ---------------------------------------------------------------------------

def _format_lead_score(value) -> str | None:
    """Format a lead_score for timeline copy (one decimal)."""
    if value is None:
        return None
    try:
        return f'{float(value):.1f}'
    except (TypeError, ValueError):
        return None


def _status_change_summary(
    old_status: str | None,
    new_status: str,
    reason: str = '',
    *,
    previous_score=None,
    new_score=None,
    include_score: bool = False,
) -> str:
    """Build status_changed timeline summary, optionally with score delta."""
    if reason:
        summary = f"Status changed from '{old_status}' to '{new_status}'. {reason}"
    else:
        summary = f"Status changed from '{old_status}' to '{new_status}'."
    if not include_score:
        return summary
    prev_s = _format_lead_score(previous_score)
    new_s = _format_lead_score(new_score)
    if prev_s is None and new_s is None:
        return summary
    if (
        previous_score is not None
        and new_score is not None
        and abs(float(previous_score) - float(new_score)) < 0.05
    ):
        return f"{summary} Score unchanged ({new_s or prev_s})."
    left = prev_s if prev_s is not None else '—'
    right = new_s if new_s is not None else '—'
    return f"{summary} Score {left} → {right}."


def _rescore_after_status_change(lead_id: int) -> None:
    """Refresh lead_score + recommended_action after a pipeline stage change.

    Delegates to the unified, error-isolated ``refresh_lead_scoring`` helper so
    a status change immediately updates BOTH the pipeline-stage bonus in
    ``lead_score`` AND the ``recommended_action`` (instead of letting the score
    go stale until the nightly bulk rescore). The helper recomputes the score
    first, then the action, and never raises — the nightly beat task remains
    the safety net.
    """
    from app.services.lead_refresh import refresh_lead_scoring
    refresh_lead_scoring(lead_id)

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


def _serialize_timeline_entry(entry: LeadTimelineEntry) -> dict:
    """Serialize a timeline entry for API responses with resolved actor display name."""
    data = LeadTimelineEntrySchema().dump(entry)
    data['actor'] = _resolve_actor(entry.actor)
    return data


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


def _require_lead_read_access(lead: Lead):
    """Return a 404 response when the caller cannot read this lead."""
    from app.controllers.property_controller import _current_user_is_admin

    if _current_user_is_admin():
        return None
    current_user_id = getattr(g, 'user_id', None)
    is_authenticated = current_user_id and current_user_id != 'anonymous'
    if not is_authenticated or lead.owner_user_id != current_user_id:
        return jsonify({
            'error': 'Not found',
            'message': f'Lead {lead.id} not found',
        }), 404
    return None


def _load_authorized_lead(lead_id: int):
    """Load a lead and apply the owner/admin access gate used by Command Center."""
    lead = Lead.query.get(lead_id)
    if lead is None:
        return None, (jsonify({'error': 'Not found', 'message': f'Lead {lead_id} not found'}), 404)
    denied = _require_lead_read_access(lead)
    if denied is not None:
        return None, denied
    return lead, None


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
    """Return signals for the winning rule — delegated to LeadScoringEngine."""
    return LeadScoringEngine.get_winning_rule_signals(lead)


def _get_action_decision(lead):
    return LeadScoringEngine.get_action_decision(lead)


def _get_queue_service_for_cc():
    """QueueService scoped like queue_controller (admin sees all)."""
    from app.controllers.property_controller import _current_user_is_admin
    from app.services.queue_service import QueueService

    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        return QueueService(owner_user_id=None)
    if _current_user_is_admin():
        return QueueService(owner_user_id=None)
    return QueueService(owner_user_id=user_id)


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
    contact_method = lead.recommended_contact_method
    display = get_recommended_action_display(
        ra,
        contact_method,
        lead=lead,
    )
    signals = _get_winning_rule_signals(lead)
    if contact_method:
        signals = {**signals, 'recommended_contact_method': contact_method}

    return jsonify({
        'recommended_action': ra,
        'recommended_contact_method': contact_method,
        'label': display.get('label'),
        'explanation': display.get('explanation'),
        'signals': signals,
        'outreach_contact': resolve_outreach_contact(lead, contact_method),
    }), 200


@command_center_bp.route('/<int:lead_id>/command-center', methods=['GET'])
@handle_errors
@require_auth
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

    denied = _require_lead_read_access(lead)
    if denied is not None:
        return denied

    # Clear review_required flag when command center is opened
    if lead.review_required:
        lead.review_required = False
        from app import db
        db.session.add(lead)
        db.session.commit()

    # Do not auto-sync HubSpot on Command Center GET. Sync-on-read can complete
    # open LeadTasks as a side effect of opening a lead or cache invalidation,
    # which breaks the next-action chain. Historical catch-up stays on Celery
    # Beat / webhooks / explicit POST .../hubspot-sync.
    from app.services.hubspot_deal_sync_service import HubSpotDealSyncService

    if (
        lead.recommended_action == 'add_contact_info'
        and is_owner_mailable_lead(lead)
    ):
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead_id)
        lead = Lead.query.get(lead_id)

    _hs_health = HubSpotDealSyncService.get_lead_sync_health(lead_id)

    from app.services.scoring_rubric import build_data_quality_breakdown
    from app import db as _db
    data_quality_breakdown = build_data_quality_breakdown(lead)
    # Always serve live completeness so the sidebar is never stuck at the
    # never-written column default of 0.
    data_completeness_score = data_quality_breakdown['total']
    # Winning-rule explanation reads lead.data_completeness_score — align the
    # in-memory value with the live breakdown before computing the decision.
    if lead.data_completeness_score != data_completeness_score:
        lead.data_completeness_score = data_completeness_score
        _db.session.add(lead)
        _db.session.commit()
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead_id)
        lead = Lead.query.get(lead_id)
        data_quality_breakdown = build_data_quality_breakdown(lead)
        data_completeness_score = data_quality_breakdown['total']

    # Display next step + "why" from one live decision so label/explanation
    # cannot disagree with a stale persisted recommended_action column.
    decision_action, winning_rule, winning_signals = _get_action_decision(lead)
    ra = decision_action if decision_action is not None else lead.recommended_action
    contact_method = winning_signals.get('recommended_contact_method')
    if contact_method is None and ra == lead.recommended_action:
        contact_method = lead.recommended_contact_method
    ra_display = get_recommended_action_display(
        ra,
        contact_method,
        lead=lead,
        winning_rule=winning_rule,
    )
    open_tasks = _lead_task_service.list_open(lead_id)
    timeline_entries, timeline_total = _lead_timeline_service.get_page(lead_id, page=1, per_page=25)

    queue_svc = _get_queue_service_for_cc()
    # Ready-to-mail membership is owner-scoped (queued-by this owner), not viewer.
    mail_user_id = lead.owner_user_id or getattr(g, 'user_id', None)
    if not mail_user_id or mail_user_id == 'anonymous':
        mail_user_id = None
    work_queues = queue_svc.membership_for_lead(lead_id, mail_user_id=mail_user_id)

    # ------------------------------------------------------------------
    # Collect phones: relational contact_phones + flat columns (structured)
    # ------------------------------------------------------------------
    from sqlalchemy import text as _text
    from app.services.phone_confidence_service import PhoneConfidenceService

    all_phones = PhoneConfidenceService.build_phones_payload(lead_id, lead)

    # Open Tasks are LeadTask-only (including HubSpot-imported rows with
    # hubspot_task_id). The CRM ``tasks`` UNION was removed in Phase 3.
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
              AND (pc.role IS NULL OR pc.role <> 'former_owner')
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
    # (has an overdue HubSpot-imported LeadTask)
    # ------------------------------------------------------------------
    from datetime import date as _date_cls
    _today = _date_cls.today()
    overdue_task = (
        LeadTask.query
        .filter(
            LeadTask.lead_id == lead_id,
            LeadTask.status == 'open',
            LeadTask.hubspot_task_id.isnot(None),
            LeadTask.due_date.isnot(None),
            LeadTask.due_date <= _today,
        )
        .order_by(LeadTask.due_date.asc())
        .first()
    )
    has_overdue_hubspot_task = overdue_task is not None
    overdue_task_title = overdue_task.title if overdue_task else None
    overdue_task_due = overdue_task.due_date.isoformat() if overdue_task and overdue_task.due_date else None
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
               hd.raw_payload->'properties'->>'dealstage' AS dealstage,
               NULLIF(TRIM(hd.raw_payload->'properties'->>'deal_source'), '') AS deal_source,
               NULLIF(TRIM(hd.raw_payload->'properties'->>'description'), '') AS deal_description
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
                    # Read-only HubSpot stage mirror; editable status is lead_status.
                    lead.hubspot_deal_stage = live_deal_stage
                    _db.session.add(lead)
                    _db.session.commit()

    # Deal context — lead column first; fill blanks from HubSpot deal_source and
    # sheet ``source`` as equal peers (description is tertiary Listsource signal).
    from app.services.helpers.deal_source import resolve_blank_deal_source

    deal_source = (lead.deal_source or '').strip() or None
    deal_description = (lead.deal_description or '').strip() or None
    cached_source = None
    cached_description = None
    if row:
        cached_source = row[2] if len(row) > 2 else None
        cached_description = row[3] if len(row) > 3 else None
        if not deal_description and cached_description:
            deal_description = cached_description
            lead.deal_description = cached_description
            _db.session.add(lead)
            _db.session.commit()

    resolved = resolve_blank_deal_source(
        current=deal_source,
        hubspot_deal_source=cached_source,
        sheet_source=lead.source,
        deal_description=deal_description or cached_description,
    )
    if resolved and resolved != deal_source:
        deal_source = resolved
        lead.deal_source = resolved
        _db.session.add(lead)
        _db.session.commit()

    # Interaction table is frozen for Command Center — HubSpot activity history
    # lives on LeadTimelineEntry via HubSpotTimelineImportService. Do not UNION
    # or inject Interaction rows into the CC timeline payload.

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

    hubspot_sync = HubSpotDealSyncService.get_lead_sync_health(lead_id)

    # Relational contacts (primary first) — people / address-like only going forward.
    # Organizations (LLCs) are linked separately via property_organization_links.
    from app.services.contact_service import ContactService
    from app.services.entity_resolution_service import EntityResolutionService
    from app.models.organization import Organization
    from app.models.property_organization_link import PropertyOrganizationLink

    contacts_payload = ContactService().get_ordered_contacts_payload(lead_id)
    related_properties = ContactService().get_related_properties(lead_id)

    from app.services.owner_snapshot_service import (
        ensure_stale_owner_snapshot,
        list_past_owners_payload,
    )
    try:
        snap = ensure_stale_owner_snapshot(lead, commit=False)
        if snap is not None:
            _db.session.commit()
    except Exception:  # noqa: BLE001 — never block command center
        logger.exception(
            'ensure_stale_owner_snapshot failed for lead %s', lead_id,
        )
        try:
            _db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
    past_owners_payload = list_past_owners_payload(lead_id)
    contacts_stale = contacts_likely_prior_owner(lead)
    stale_since = contacts_stale_since(lead)

    org_rows = (
        _db.session.query(Organization, PropertyOrganizationLink)
        .join(
            PropertyOrganizationLink,
            PropertyOrganizationLink.organization_id == Organization.id,
        )
        .filter(PropertyOrganizationLink.property_id == lead_id)
        .order_by(PropertyOrganizationLink.id.asc())
        .all()
    )
    organizations_payload = []
    for org, link in org_rows:
        person_name, person_role = EntityResolutionService.resolved_person_for_org(org)
        organizations_payload.append({
            'id': org.id,
            'name': org.name,
            'org_type': org.org_type,
            'status': org.status,
            'role': link.role,
            'link_id': link.id,
            'entity_lookup_status': org.entity_lookup_status,
            'entity_lookup_person_found': org.entity_lookup_person_found,
            'entity_lookup_checked_at': (
                org.entity_lookup_checked_at.isoformat()
                if org.entity_lookup_checked_at else None
            ),
            'entity_lookup_error': org.entity_lookup_error,
            'jurisdiction': org.jurisdiction,
            'file_number': org.file_number,
            'registered_office_address': org.registered_office_address,
            'registered_agent_name': org.registered_agent_name,
            'resolved_person_name': person_name,
            'resolved_person_role': person_role,
        })

    is_mailable = is_owner_mailable_lead(lead)
    mail_eligible_date = recent_sale_mail_eligible_date(lead)
    from app.services.cook_county_enrichment_service import is_cook_county_lead

    return jsonify({
        'id': lead.id,
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'owner_2_first_name': lead.owner_2_first_name,
        'owner_2_last_name': lead.owner_2_last_name,
        'contacts': contacts_payload,
        'contacts_likely_prior_owner': contacts_stale,
        'contacts_stale_since': stale_since,
        'past_owners': past_owners_payload,
        'organizations': organizations_payload,
        'related_properties': related_properties,
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
        'is_cook_county_eligible': is_cook_county_lead(lead),
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
        'deal_source': deal_source,
        'deal_description': deal_description,
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
        'most_recent_sale_display': display_most_recent_sale(lead),
        'most_recent_sale_price': getattr(lead, 'most_recent_sale_price', None),
        'sale_date_meta': resolve_sale_date_meta(lead),
        'sale_history': list_parcel_sale_history(
            getattr(lead, 'county_assessor_pin', None),
            limit=50,
            lead=lead,
            cache_only=True,
        ),
        'is_mailable': is_mailable,
        'mail_eligible': is_mailable and mail_eligible_date is None,
        'mail_ineligible_reason': (
            'recently_sold'
            if mail_eligible_date is not None
            else (
                'invalid_owner_address'
                if not is_mailable
                else None
            )
        ),
        'mail_eligible_date': (
            mail_eligible_date.isoformat()
            if mail_eligible_date is not None
            else None
        ),
        'address_2': lead.address_2,
        'returned_addresses': lead.returned_addresses,
        # Research / workflow tracking
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'needs_skip_trace': lead.needs_skip_trace,
        'skip_tracer': lead.skip_tracer,
        'date_skip_traced': lead.date_skip_traced.isoformat() if lead.date_skip_traced else None,
        'up_next_to_mail': lead.up_next_to_mail,
        'mail_queue_status': resolve_mail_queue_status(lead),
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
        'condo_risk_status': getattr(lead, 'condo_risk_status', None),
        'building_sale_possible': getattr(lead, 'building_sale_possible', None),
        'condo_analysis_id': getattr(lead, 'condo_analysis_id', None),
        'assessor_class': getattr(lead, 'assessor_class', None),
        'data_completeness_score': data_completeness_score,
        'data_quality_breakdown': data_quality_breakdown,
        'work_queues': work_queues,
        'analysis_session_id': lead.analysis_session_id,
        'last_contact_date': lead.last_contact_date.isoformat() if lead.last_contact_date else None,
        'last_hubspot_sync_at': lead.last_hubspot_sync_at.isoformat() if lead.last_hubspot_sync_at else None,
        'hubspot_deal_stage': live_deal_stage or lead.hubspot_deal_stage,
        'hubspot_has_confirmed_deal': hubspot_sync['hubspot_has_confirmed_deal'],
        'hubspot_sync_stale': hubspot_sync['hubspot_sync_stale'],
        'hubspot_deal_last_updated_at': hubspot_sync['hubspot_deal_last_updated_at'],
        'review_required': lead.review_required,
        'review_reason': lead.review_reason,
        'quick_briefing': lead.quick_briefing if isinstance(lead.quick_briefing, dict) else None,
        'recommended_action': {
            'value': ra,
            'recommended_contact_method': contact_method,
            'label': ra_display.get('label'),
            'explanation': ra_display.get('explanation'),
            'winning_rule': winning_rule,
            'winning_rule_label': get_winning_rule_label(winning_rule),
            'outreach_contact': resolve_outreach_contact(lead, contact_method),
            'signals': {
                **winning_signals,
                **({'recommended_contact_method': contact_method} if contact_method else {}),
            },
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
                'source': 'hubspot' if t.hubspot_task_id else 'native',
                'hubspot_task_id': t.hubspot_task_id,
            }
            for t in open_tasks
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
                ) + (
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
            'total': timeline_total + (1 if lead.mailer_history else 0),
            'page': 1,
            'per_page': 25,
        },
        # Interaction is frozen for CC — HubSpot activities use LeadTimelineEntry.
        # Kept empty for backward-compatible clients that still read the key.
        'hubspot_interactions': [],
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
@require_auth
@handle_errors
def update_status(lead_id: int):
    """
    PATCH /api/leads/<lead_id>/status

    Update the lead_status of a lead. Handles DNC and suppressed special cases
    consistently with their dedicated actions.
    Appends a status_changed timeline entry. Triggers RA recomputation for
    non-terminal statuses.
    """
    from app import db
    import datetime as _dt

    data = LeadStatusUpdateSchema().load(request.get_json() or {})
    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    denied = _require_lead_read_access(lead)
    if denied is not None:
        return denied

    old_status = lead.lead_status
    new_status = data['status']
    reason = data.get('reason') or ''
    actor_raw = getattr(g, 'user_id', None) or data.get('actor') or 'anonymous'
    previous_score = lead.lead_score

    lead.lead_status = new_status

    # Entering the skip-trace pipeline means skip work is still needed. Without
    # this flag, scoring's residential mailing promotion immediately reverts
    # manual awaiting_skip_trace / skip_trace changes when a mailing address exists.
    if new_status in ('skip_trace', 'awaiting_skip_trace'):
        lead.needs_skip_trace = True

    # Match the dedicated DNC action: DNC always cancels open next-action work,
    # regardless of whether it came from Quick Actions or the status selector.
    if new_status in ('do_not_contact', 'suppressed'):
        lead.recommended_action = None
    if new_status == 'do_not_contact':
        LeadTask.query.filter_by(lead_id=lead_id, status='open').update(
            {'status': 'cancelled'},
        )

    db.session.add(lead)

    # Append status_changed timeline entry — store raw actor_raw (canonical user_id)
    # so the DB retains the canonical ID; _resolve_actor is called at read/serialization time.
    # Score delta is filled in after rescoring (below) when applicable.
    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='status_changed',
        occurred_at=_dt.datetime.now(_dt.timezone.utc),
        source='manual',
        actor=actor_raw,
        summary=_status_change_summary(old_status, new_status, reason),
        event_metadata={
            'previous_status': old_status,
            'new_status': new_status,
            'reason': reason or None,
            'previous_score': float(previous_score) if previous_score is not None else None,
        },
    )
    db.session.add(entry)
    db.session.commit()

    from app.services.queue_order_cache import queue_order_cache
    queue_order_cache.clear()

    # Rescore first, then recompute RA (inside _rescore_after_status_change)
    # so the action reflects the updated score. Enrich the timeline entry with
    # the score delta so Activity history shows how the change moved the score.
    if new_status not in ('do_not_contact', 'suppressed'):
        _rescore_after_status_change(lead_id)
        db.session.refresh(lead)
        new_score = lead.lead_score
        entry.summary = _status_change_summary(
            old_status,
            new_status,
            reason,
            previous_score=previous_score,
            new_score=new_score,
            include_score=True,
        )
        meta = dict(entry.event_metadata or {})
        meta['previous_score'] = float(previous_score) if previous_score is not None else None
        meta['new_score'] = float(new_score) if new_score is not None else None
        entry.event_metadata = meta
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(entry, 'event_metadata')
        db.session.add(entry)
        db.session.commit()

    try:
        from app.services.hubspot_writeback_service import HubSpotWriteBackService
        HubSpotWriteBackService().push_deal_stage_for_lead(lead_id, new_status)
    except Exception as exc:
        logger.warning(
            'HubSpot stage push after status change failed for lead %s: %s',
            lead_id, exc,
        )

    db.session.refresh(entry)
    return jsonify({
        'lead_status': lead.lead_status,
        'recommended_action': lead.recommended_action,
        'lead_score': lead.lead_score,
        'timeline_entry': _serialize_timeline_entry(entry),
    }), 200


@command_center_bp.route('/<int:lead_id>/move-to-skip-trace', methods=['POST'])
@handle_errors
@require_auth
def move_to_skip_trace(lead_id: int):
    """Complete the current task and atomically hand the lead to skip trace."""
    _lead, denied = _load_authorized_lead(lead_id)
    if denied is not None:
        return denied

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    elif not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    complete_task_id = data.get('complete_task_id')
    if complete_task_id is not None:
        try:
            complete_task_id = int(complete_task_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'complete_task_id must be an integer'}), 400

    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    result = SkipTraceEnqueue().move_to_skip_trace(
        lead_id,
        actor=getattr(g, 'user_id', 'anonymous'),
        complete_task_id=complete_task_id,
    )

    try:
        from app.services.hubspot_writeback_service import HubSpotWriteBackService
        HubSpotWriteBackService().push_deal_stage_for_lead(lead_id, 'skip_trace')
    except Exception as exc:
        logger.warning(
            'HubSpot stage push after skip-trace handoff failed for lead %s: %s',
            lead_id,
            exc,
        )

    return jsonify(result), 200


@command_center_bp.route('/<int:lead_id>/adjust-for-recent-sale', methods=['POST'])
@handle_errors
@require_auth
def adjust_for_recent_sale(lead_id: int):
    """Move the selected/earliest task to two years after the latest sale."""
    lead, denied = _load_authorized_lead(lead_id)
    if denied is not None:
        return denied

    raw_body = request.get_data(cache=True)
    if not raw_body:
        data = {}
    else:
        data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    task_id = data.get('task_id')
    if task_id is not None:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'task_id must be an integer'}), 400

    from app.services.mail_task_lifecycle_service import (
        adjust_earliest_task_for_recent_sale,
    )

    try:
        result = adjust_earliest_task_for_recent_sale(
            lead,
            actor=getattr(g, 'user_id', 'anonymous'),
            task_id=task_id,
            hubspot_task_id=data.get('hubspot_task_id'),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409

    return jsonify(result), 200


@command_center_bp.route('/<int:lead_id>/tasks', methods=['POST'])
@handle_errors
@require_auth
def create_task(lead_id: int):
    """
    POST /api/leads/<lead_id>/tasks

    Create a new LeadTask for a lead.
    """
    _lead, denied = _load_authorized_lead(lead_id)
    if denied is not None:
        return denied
    data = LeadTaskCreateSchema().load(request.get_json() or {})
    actor = getattr(g, 'user_id', 'anonymous')
    # Skip-trace handoff must go through SkipTraceEnqueue so needs_skip_trace
    # is set alongside the open skip_trace_owner task (canonical writer).
    if data.get('task_type') == 'skip_trace_owner':
        from app.services.skip_trace_enqueue import SkipTraceEnqueue
        task = SkipTraceEnqueue().enqueue(
            lead_id,
            actor=actor,
            reason=data.get('title') or 'Run skip trace on owner',
            due_date=data.get('due_date'),
            recompute_action=False,
        )
        if task is None:
            return jsonify({'error': 'Lead not found'}), 404
    else:
        # Pass recompute_action=False: refresh_lead_scoring below recomputes the
        # recommended_action itself (after rescoring), so letting the service ALSO
        # recompute would do it twice (duplicate DB work / timeline churn).
        task = _lead_task_service.create(lead_id, data, actor=actor, recompute_action=False)
    # Refresh lead_score + recommended_action exactly once: rescore first (so a
    # stale score is corrected) then recompute the action on the fresh score.
    from app.services.lead_refresh import refresh_lead_scoring
    refresh_lead_scoring(lead_id)
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
@require_auth
def update_task(lead_id: int, task_id: int):
    """
    PATCH /api/leads/<lead_id>/tasks/<task_id>

    Snooze (if new_due_date present) or update a task's title/due_date.
    HubSpot-imported tasks also best-effort sync title/due date to HubSpot.
    """
    _lead, denied = _load_authorized_lead(lead_id)
    if denied is not None:
        return denied
    from app import db
    from app.services.hubspot_task_completion_service import (
        mirror_crm_task_from_lead_task,
        sync_hubspot_task_properties,
    )

    actor = getattr(g, 'user_id', 'anonymous')
    body = request.get_json() or {}
    title_changed = False
    due_changed = False
    clear_due_date = False
    if 'new_due_date' in body:
        data = LeadTaskSnoozeSchema().load(body)
        task = _lead_task_service.snooze(task_id, lead_id, data['new_due_date'], actor=actor)
        due_changed = True
    else:
        data = LeadTaskUpdateSchema().load(body)
        task = LeadTask.query.filter_by(id=task_id, lead_id=lead_id).first()
        if task is None:
            return jsonify({'error': 'Not found'}), 404
        if 'title' in data:
            task.title = data['title']
            title_changed = True
        if 'due_date' in data:
            clear_due_date = data['due_date'] is None
            task.due_date = data['due_date']
            due_changed = True
        db.session.add(task)
        db.session.commit()

    # Capture fields before optional mirror rollback can expire the ORM instance.
    task_id_out = task.id
    task_title = task.title
    task_status = task.status
    task_due_date = task.due_date
    hubspot_task_id = task.hubspot_task_id

    hubspot_synced = None
    if hubspot_task_id and (title_changed or due_changed):
        try:
            mirror_crm_task_from_lead_task(task)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning(
                'mirror_crm_task_from_lead_task failed for hubspot_task_id=%s: %s',
                hubspot_task_id,
                exc,
            )

        hubspot_synced = sync_hubspot_task_properties(
            str(hubspot_task_id),
            title=task_title if title_changed else None,
            due_date=None if clear_due_date else (task_due_date if due_changed else None),
            clear_due_date=clear_due_date,
        )

    # Refresh lead_score + recommended_action after the task change (due-date
    # / snooze changes can affect follow-up overdue state and the action).
    from app.services.lead_refresh import refresh_lead_scoring
    refresh_lead_scoring(lead_id)
    payload = {
        'id': task_id_out,
        'title': task_title,
        'status': task_status,
        'due_date': task_due_date.isoformat() if task_due_date else None,
    }
    if hubspot_synced is not None:
        payload['hubspot_synced'] = hubspot_synced
    return jsonify(payload), 200


@command_center_bp.route('/<int:lead_id>/tasks/<int:task_id>/complete', methods=['POST'])
@handle_errors
@require_auth
def complete_task(lead_id: int, task_id: int):
    """
    POST /api/leads/<lead_id>/tasks/<task_id>/complete

    Mark a LeadTask as completed.
    """
    _lead, denied = _load_authorized_lead(lead_id)
    if denied is not None:
        return denied
    actor = getattr(g, 'user_id', 'anonymous')
    # recompute_action=False — refresh_lead_scoring below owns the single
    # recommended_action recompute (after rescoring), avoiding a double recompute.
    task = _lead_task_service.complete(task_id, lead_id, actor=actor, recompute_action=False)
    # Refresh lead_score + recommended_action exactly once per operation.
    from app.services.lead_refresh import refresh_lead_scoring
    refresh_lead_scoring(lead_id)
    return jsonify({
        'id': task.id,
        'status': task.status,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
    }), 200


@command_center_bp.route('/<int:lead_id>/briefing', methods=['POST'])
@handle_errors
@require_auth
def generate_lead_briefing(lead_id: int):
    """
    POST /api/leads/<lead_id>/briefing

    On-demand Gemini briefing: five short keep-in-mind bullets from timeline,
    open tasks, and lead context. Persists latest on the lead; Refresh revises
    from the previous briefing when one exists.
    """
    lead, err = _load_authorized_lead(lead_id)
    if err is not None:
        return err

    from app.services.lead_briefing_service import LeadBriefingService

    result = LeadBriefingService().generate(lead.id, persist=True)
    return jsonify(result), 200


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
@require_auth
@handle_errors
def log_note(lead_id: int):
    """
    POST /api/leads/<lead_id>/notes

    Log a free-text note on a lead.
    """
    data = LogNoteSchema().load(request.get_json() or {})
    actor = g.user_id
    entry = _call_log_service.log_note(
        lead_id,
        data['body'],
        actor=actor,
        contact_id=data.get('contact_id'),
        contact_email_id=data.get('contact_email_id'),
        email_address=data.get('email_address'),
        email_label=data.get('email_label'),
        subject=data.get('subject'),
    )
    return jsonify(_serialize_timeline_entry(entry)), 201


@command_center_bp.route('/<int:lead_id>/calls', methods=['POST'])
@require_auth
@handle_errors
def log_call(lead_id: int):
    """
    POST /api/leads/<lead_id>/calls

    Log a call on a lead with outcome, optional duration, and optional notes.
    """
    data = LogCallSchema().load(request.get_json() or {})
    actor = g.user_id
    entry = _call_log_service.log_call(
        lead_id,
        data['outcome'],
        data.get('duration_minutes'),
        data.get('notes'),
        actor=actor,
        contact_id=data.get('contact_id'),
        contact_phone_id=data.get('contact_phone_id'),
        phone_number=data.get('phone_number'),
        phone_label=data.get('phone_label'),
        mail_campaign_id=data.get('mail_campaign_id'),
        complete_task_id=data.get('complete_task_id'),
        follow_up=data.get('follow_up'),
    )
    return jsonify(_serialize_timeline_entry(entry)), 201


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

    # Rescore first, then recompute RA (inside _rescore_after_status_change).
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

    # Rescore first, then recompute RA (inside _rescore_after_status_change).
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


@command_center_bp.route('/<int:lead_id>/hubspot-sync', methods=['POST'])
@require_auth
@handle_errors
def sync_lead_from_hubspot(lead_id: int):
    """POST /api/leads/<lead_id>/hubspot-sync

    Re-fetch confirmed HubSpot deal(s) from the API and sync stage/status
    onto the lead. Works without Celery (local dev) and in production.
    """
    from app.controllers.property_controller import _current_user_is_admin
    from app.services.hubspot_deal_sync_service import HubSpotDealSyncService

    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    if not _current_user_is_admin():
        current_user_id = getattr(g, 'user_id', None)
        if not current_user_id or current_user_id == 'anonymous' or lead.owner_user_id != current_user_id:
            return jsonify({'error': 'Not found'}), 404

    try:
        # Explicit user/admin sync may pull tasks; open LeadTasks stay protected
        # by LeadTaskService.upsert_from_hubspot (next-action SoT).
        result = HubSpotDealSyncService().refresh_and_enrich_lead(
            lead_id,
            include_tasks=True,
        )
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 500

    if not result.get('synced'):
        reason = result.get('reason', 'sync_failed')
        if reason == 'no_confirmed_deal':
            return jsonify({'error': reason}), 404
        return jsonify({'error': reason}), 422

    health = HubSpotDealSyncService.get_lead_sync_health(lead_id)
    return jsonify({**result, **health}), 200


@command_center_bp.route('/<int:lead_id>/sale-date-verification', methods=['POST'])
@require_auth
@handle_errors
def verify_sale_date(lead_id: int):
    """Verify sale-date fields through Cook County enrichment.

    Enqueues the canonical one-lead Cook County task when workers are available.
    In local/dev with Redis but no worker, runs synchronously so the user can
    verify one lead without waiting for Celery.
    """
    from app.controllers.property_controller import _current_user_is_admin
    from app.services.cook_county_enrichment_service import (
        enrich_cook_county_lead,
        enqueue_cook_county_enrichment,
        ensure_automated_data_sources,
    )

    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    if not _current_user_is_admin():
        current_user_id = getattr(g, 'user_id', None)
        if not current_user_id or current_user_id == 'anonymous' or lead.owner_user_id != current_user_id:
            return jsonify({'error': 'Not found'}), 404

    ensure_automated_data_sources()

    workers_available = False
    try:
        from celery_worker import celery as celery_app
        inspect = celery_app.control.inspect(timeout=0.75)
        workers_available = bool(inspect and inspect.ping())
    except Exception:
        workers_available = False

    queued = False
    ran_sync = False
    summary = None
    if workers_available:
        queued = enqueue_cook_county_enrichment(lead_id)

    if not queued:
        flask_env = os.getenv('FLASK_ENV', 'production')
        if flask_env in ('development', 'testing'):
            summary = enrich_cook_county_lead(lead_id)
            ran_sync = True
        else:
            return jsonify({
                'lead_id': lead_id,
                'queued': False,
                'ran_sync': False,
                'error': 'workers_unavailable',
                'message': (
                    'Verification could not be queued because no background workers '
                    'are available. Try again shortly.'
                ),
            }), 503

    from app import db as _db
    _db.session.refresh(lead)

    message = (
        'Verification queued.'
        if queued
        else ('Sale date verified.' if ran_sync else '')
    )
    if ran_sync and summary is not None:
        if summary.get('skipped'):
            reason = summary.get('skip_reason') or 'unknown'
            if reason == 'not_eligible':
                message = 'Not eligible for Cook County enrichment.'
            elif reason == 'lead_not_found':
                message = 'Lead not found.'
            else:
                message = f'Verification skipped ({reason}).'
    elif not queued and not ran_sync:
        message = 'Verification could not be queued or run.'

    return jsonify({
        'lead_id': lead_id,
        'queued': queued,
        'ran_sync': ran_sync,
        'summary': summary,
        'message': message,
        'county_assessor_pin': lead.county_assessor_pin,
        'most_recent_sale_display': display_most_recent_sale(lead),
        'most_recent_sale_price': getattr(lead, 'most_recent_sale_price', None),
        'sale_date_meta': resolve_sale_date_meta(lead),
    }), 200


@command_center_bp.route('/<int:lead_id>/hubspot-tasks/<int:task_id>/done', methods=['POST'])
@require_auth
@handle_errors
def mark_hubspot_task_done(lead_id: int, task_id: int):
    """
    POST /api/leads/<lead_id>/hubspot-tasks/<task_id>/done

    Mark a HubSpot-imported LeadTask completed locally and best-effort in HubSpot.
    ``task_id`` is the LeadTask id by default. Pass ``id_namespace=crm_task``
    (query or JSON body) for legacy CRM ``tasks.id`` / ``hs-{id}`` clients.
    """
    from app.controllers.property_controller import _current_user_is_admin
    from app.services.hubspot_task_completion_service import complete_hubspot_task

    lead = Lead.query.get(lead_id)
    if lead is None:
        return jsonify({'error': 'Not found'}), 404

    if not _current_user_is_admin():
        current_user_id = getattr(g, 'user_id', None)
        if not current_user_id or current_user_id == 'anonymous' or lead.owner_user_id != current_user_id:
            return jsonify({'error': 'Not found'}), 404

    body = request.get_json(silent=True) or {}
    id_namespace = (
        request.args.get('id_namespace')
        or body.get('id_namespace')
        or 'lead_task'
    )
    actor = getattr(g, 'user_id', 'anonymous')
    result = complete_hubspot_task(
        lead_id, task_id, actor=actor, id_namespace=str(id_namespace),
    )
    if not result.completed:
        return jsonify({
            'error': 'Not found',
            'message': f'Task {task_id} not found or already completed for lead {lead_id}',
        }), 404

    return jsonify({
        'task_id': task_id,
        'status': 'completed',
        'hubspot_synced': result.hubspot_synced,
        'hubspot_task_id': result.hubspot_task_id,
    }), 200
