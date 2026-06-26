"""Action Engine Service — deterministic recommended action computation."""
import logging

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.models.lead_crm_flags_view import LeadCRMFlagsView

logger = logging.getLogger(__name__)


TASK_TYPE_TO_RECOMMENDED_ACTION = {
    'run_property_analysis': 'analyze_property',
    'match_hubspot_deal': 'resolve_match',
    'skip_trace_owner': 'enrich_data',
    'add_to_mail_batch': 'ready_for_outreach',
    'call_owner_today': 'follow_up_now',
    'research_missing_pin': 'resolve_match',
}

RECOMMENDED_ACTION_METADATA = {
    'enrich_data': {
        'label': 'Enrich Data',
        'explanation': 'This lead is missing key data needed to evaluate it. Add contact info, property details, or run a skip trace to improve data completeness.',
    },
    'resolve_match': {
        'label': 'Resolve Property Match',
        'explanation': 'No property record has been matched to this lead. Search for the property or research the PIN to enable analysis.',
    },
    'analyze_property': {
        'label': 'Analyze Property',
        'explanation': 'A property match exists but no analysis has been run. Run a property analysis to get an ARV estimate and investment scenarios.',
    },
    'follow_up_now': {
        'label': 'Follow Up Now',
        'explanation': 'This lead has prior engagement or an overdue follow-up. Reach out now to keep the conversation warm.',
    },
    'ready_for_outreach': {
        'label': 'Ready for Outreach',
        'explanation': 'This lead has a high score and complete analysis. It is ready for direct outreach — call, mail, or add to a marketing batch.',
    },
    'add_contact_info': {
        'label': 'Add Contact Info',
        'explanation': 'No phone or email is on file for this lead. Add contact information or run a skip trace before attempting outreach.',
    },
    'create_task': {
        'label': 'Create a Task',
        'explanation': 'This lead has no open tasks and no specific next action. Create a task to define the next concrete step.',
    },
    'nurture': {
        'label': 'Quick actions',
        'explanation': '',
    },
    'suppress': {
        'label': 'Suppress',
        'explanation': 'This lead does not meet investment criteria. Suppress it to remove it from active queues.',
    },
    'do_not_contact': {
        'label': 'Do Not Contact',
        'explanation': 'This lead has requested no contact. No outreach actions are permitted.',
    },
}


def _count_open_tasks(lead_id: int) -> int:
    """Return the number of open tasks for the given lead.

    Counts both native LeadTask records and HubSpot-imported tasks linked
    via task_associations, so the action engine sees the full picture.
    """
    from sqlalchemy import text as _text
    native = LeadTask.query.filter_by(lead_id=lead_id, status='open').count()
    hs = db.session.execute(_text("""
        SELECT COUNT(*) FROM tasks t
        JOIN task_associations ta ON ta.task_id = t.id
        WHERE ta.target_type = 'lead' AND ta.target_id = :lid
          AND t.status IN ('open', 'overdue')
          AND t.source = 'hubspot_import'
        UNION ALL
        SELECT COUNT(*) FROM tasks
        WHERE lead_id = :lid
          AND status IN ('open', 'overdue')
          AND source = 'hubspot_import'
    """), {'lid': lead_id}).fetchall()
    # Sum both union rows and deduplicate by taking max (avoids double-counting)
    hs_counts = [r[0] for r in hs]
    hs_total = max(hs_counts) if hs_counts else 0
    return native + hs_total


def _has_overdue_hubspot_task(lead_id: int) -> bool:
    """Return True when the lead has an overdue HubSpot-imported task."""
    from sqlalchemy import text as _hs_text
    from datetime import datetime as _dt

    try:
        row = db.session.execute(_hs_text("""
            SELECT 1 FROM tasks t
            JOIN task_associations ta ON ta.task_id = t.id
            WHERE ta.target_type = 'lead' AND ta.target_id = :lid
              AND t.status IN ('open', 'overdue')
              AND (t.due_date <= :now OR (t.due_date IS NULL AND t.status = 'overdue'))
              AND t.source = 'hubspot_import'
            LIMIT 1
        """), {'lid': lead_id, 'now': _dt.utcnow()}).fetchone()
        if not row:
            row = db.session.execute(_hs_text("""
                SELECT 1 FROM tasks
                WHERE lead_id = :lid
                  AND status IN ('open', 'overdue')
                  AND (due_date <= :now OR (due_date IS NULL AND status = 'overdue'))
                  AND source = 'hubspot_import'
                LIMIT 1
            """), {'lid': lead_id, 'now': _dt.utcnow()}).fetchone()
        return row is not None
    except Exception as exc:
        logger.warning(
            "action_engine: overdue HubSpot task query failed for lead_id=%s: %s",
            lead_id, exc,
        )
        return False


def _resolve_crm_flags(lead):
    """Return (has_phone, has_email, has_property_match) for the lead."""
    try:
        flags = LeadCRMFlagsView.query.filter_by(lead_id=lead.id).first()
        if flags:
            return (
                flags.has_phone_computed,
                flags.has_email_computed,
                flags.has_property_match_computed,
            )
    except Exception:
        pass
    return lead.has_phone, lead.has_email, lead.has_property_match


def evaluate_recommended_action(lead) -> tuple[str | None, str, dict]:
    """
    Evaluate the action engine and return (action, winning_rule, signals).

    winning_rule is a stable identifier for the rule that fired (used in
    timeline metadata and API responses).
    """
    # Priority 1
    if lead.lead_status == 'do_not_contact':
        return None, 'do_not_contact', {'lead_status': 'do_not_contact'}
    # Priority 2
    if lead.lead_status in ('suppressed', 'deprioritize', 'deal_won', 'deal_lost'):
        return None, 'terminal_status', {'lead_status': lead.lead_status}
    # Priority 2.5
    if lead.lead_status in ('skip_trace', 'awaiting_skip_trace'):
        return (
            'add_contact_info',
            'skip_trace_status',
            {'lead_status': lead.lead_status, 'requires_skip_trace': True},
        )
    # Priority 3
    has_phone, has_email, has_property_match = _resolve_crm_flags(lead)
    if not has_phone and not has_email:
        return (
            'add_contact_info',
            'no_contact_info',
            {'has_phone': False, 'has_email': False},
        )
    # Priority 4
    if not has_property_match and lead.property_street:
        return (
            'resolve_match',
            'no_property_match_with_address',
            {'has_property_match': False, 'property_street': lead.property_street},
        )
    if not has_property_match and not lead.property_street:
        return (
            'enrich_data',
            'no_property_match_no_address',
            {'has_property_match': False, 'property_street': lead.property_street},
        )
    # Priority 5
    has_overdue_hs_task = _has_overdue_hubspot_task(lead.id)
    if lead.follow_up_overdue or has_overdue_hs_task:
        signals = {
            'follow_up_overdue': bool(lead.follow_up_overdue),
            'has_overdue_hs_task': has_overdue_hs_task,
        }
        return 'follow_up_now', 'follow_up_overdue', signals
    # Priority 6
    if lead.is_warm:
        return 'follow_up_now', 'is_warm', {'is_warm': True}
    # Priority 7
    open_tasks = _count_open_tasks(lead.id)
    if lead.lead_score >= 70 and open_tasks == 0:
        return (
            'ready_for_outreach',
            'high_score_no_tasks',
            {'lead_score': lead.lead_score, 'open_task_count': open_tasks},
        )
    # Priority 8
    if open_tasks == 0:
        return (
            'create_task',
            'no_tasks_create_one',
            {'lead_status': lead.lead_status, 'open_task_count': open_tasks},
        )
    # Priority 9
    return (
        'nurture',
        'has_open_tasks',
        {'open_task_count': open_tasks, 'lead_score': lead.lead_score},
    )


class ActionEngineService:
    """Deterministic rule engine that assigns Recommended_Action to leads."""

    @staticmethod
    def compute_recommended_action(lead) -> str | None:
        """
        Deterministic rule engine. Evaluates rules in priority order.
        Returns the first matching Recommended_Action, or None for
        suppressed/do_not_contact leads.
        """
        action, _winning_rule, _signals = evaluate_recommended_action(lead)
        return action

    @staticmethod
    def get_winning_rule_signals(lead) -> dict:
        """Return signal fields for the winning rule on this lead's current RA."""
        _action, _winning_rule, signals = evaluate_recommended_action(lead)
        return signals

    @staticmethod
    def recompute_and_persist(lead_id: int):
        """
        Fetch lead, run the engine, persist recommended_action, and append a
        recommended_action_changed timeline entry only when the value changes.
        Returns the updated Lead.
        """
        from datetime import datetime, timezone

        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        previous_action = lead.recommended_action
        new_action, winning_rule, signals = evaluate_recommended_action(lead)

        if new_action != previous_action:
            lead.recommended_action = new_action
            db.session.add(lead)

            # Append timeline entry only when value changes
            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type='recommended_action_changed',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor='System',
                summary=f"Recommended action changed from '{previous_action}' to '{new_action}'.",
                event_metadata={
                    'previous_action': previous_action,
                    'new_action': new_action,
                    'winning_rule': winning_rule,
                    'lead_score': lead.lead_score,
                    'is_warm': lead.is_warm,
                    'signals': signals,
                },
            )
            db.session.add(entry)
            db.session.commit()

        return lead

    @staticmethod
    def bulk_recompute(lead_ids: list[int] | None = None) -> int:
        """
        Batch recomputation of recommended actions.

        If lead_ids is None, processes all leads.
        Processes in chunks of 500 to avoid memory issues.
        Returns the total count of leads processed.

        Target: 10,000 leads in 60 seconds.
        """
        CHUNK_SIZE = 500
        total_processed = 0

        if lead_ids is None:
            # Process all leads in chunks using offset-based pagination
            offset = 0
            while True:
                chunk = Lead.query.order_by(Lead.id).offset(offset).limit(CHUNK_SIZE).all()
                if not chunk:
                    break
                for lead in chunk:
                    try:
                        ActionEngineService.recompute_and_persist(lead.id)
                        total_processed += 1
                    except Exception as exc:
                        db.session.rollback()
                        logger.error("Failed to recompute lead %s: %s", lead.id, exc, exc_info=True)
                offset += CHUNK_SIZE
        else:
            # Process specific lead IDs in chunks
            for i in range(0, len(lead_ids), CHUNK_SIZE):
                chunk_ids = lead_ids[i:i + CHUNK_SIZE]
                for lead_id in chunk_ids:
                    try:
                        ActionEngineService.recompute_and_persist(lead_id)
                        total_processed += 1
                    except Exception as exc:
                        db.session.rollback()
                        logger.error("Failed to recompute lead %s: %s", lead_id, exc, exc_info=True)

        return total_processed
