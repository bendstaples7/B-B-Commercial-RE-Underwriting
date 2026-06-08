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
        'label': 'Nurture',
        'explanation': 'This lead does not meet criteria for immediate action. Park it in the nurture pipeline and revisit when conditions change.',
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


class ActionEngineService:
    """Deterministic rule engine that assigns Recommended_Action to leads."""

    @staticmethod
    def compute_recommended_action(lead) -> str | None:
        """
        Deterministic rule engine. Evaluates rules in priority order.
        Returns the first matching Recommended_Action, or None for
        suppressed/do_not_contact leads.
        """
        # Priority 1
        if lead.lead_status == 'do_not_contact':
            return None
        # Priority 2 — statuses that suppress all outreach actions
        if lead.lead_status in ('suppressed', 'deprioritize', 'deal_won', 'deal_lost'):
            return None
        # Priority 2.5 — skip trace statuses always need contact info first, regardless of
        # what has_phone/has_email says.  Being in skip_trace/awaiting_skip_trace means the
        # existing contact info is insufficient and a skip trace is required before outreach.
        if lead.lead_status in ('skip_trace', 'awaiting_skip_trace'):
            return 'add_contact_info'
        # Priority 3 — resolve has_phone/has_email/has_property_match from view, fall back to stored columns
        try:
            flags = LeadCRMFlagsView.query.filter_by(lead_id=lead.id).first()
            has_phone = flags.has_phone_computed if flags else lead.has_phone
            has_email = flags.has_email_computed if flags else lead.has_email
            has_property_match = flags.has_property_match_computed if flags else lead.has_property_match
        except Exception:
            has_phone = lead.has_phone
            has_email = lead.has_email
            has_property_match = lead.has_property_match
        if not has_phone and not has_email:
            return 'add_contact_info'
        # Priority 4
        if not has_property_match and lead.property_street:
            return 'resolve_match'
        if not has_property_match and not lead.property_street:
            return 'enrich_data'  # no address at all — need more data before outreach
        # Priority 5 — follow-up overdue (native task OR overdue HubSpot task)
        # Note: skip_trace/awaiting_skip_trace leads are intercepted at Priority 2.5
        # and never reach here, so no guard is needed.
        has_overdue_hs_task = False
        try:
            from sqlalchemy import text as _hs_text
            from datetime import datetime as _dt
            row = db.session.execute(_hs_text("""
                SELECT 1 FROM tasks t
                JOIN task_associations ta ON ta.task_id = t.id
                WHERE ta.target_type = 'lead' AND ta.target_id = :lid
                  AND t.status IN ('open', 'overdue')
                  AND (t.due_date IS NULL OR t.due_date <= :now)
                  AND t.source = 'hubspot_import'
                LIMIT 1
            """), {'lid': lead.id, 'now': _dt.utcnow()}).fetchone()
            if not row:
                row = db.session.execute(_hs_text("""
                    SELECT 1 FROM tasks
                    WHERE lead_id = :lid
                      AND status IN ('open', 'overdue')
                      AND (due_date IS NULL OR due_date <= :now)
                      AND source = 'hubspot_import'
                    LIMIT 1
                """), {'lid': lead.id, 'now': _dt.utcnow()}).fetchone()
            has_overdue_hs_task = row is not None
        except Exception as exc:
            logger.warning(
                "action_engine: overdue HubSpot task query failed for lead_id=%s: %s",
                lead.id, exc,
            )
            # Leave has_overdue_hs_task=False — don't raise so the rest of the
            # engine can still produce a meaningful action for this lead.
        if lead.follow_up_overdue or has_overdue_hs_task:
            return 'follow_up_now'
        # Priority 6 — warm lead
        if lead.is_warm:
            return 'follow_up_now'
        # Priority 7 — high score lead with no open tasks → ready for outreach
        if lead.lead_score >= 70:
            open_tasks = _count_open_tasks(lead.id)
            if open_tasks == 0:
                return 'ready_for_outreach'
        # Priority 8 — has contact info, property matched, no tasks → create a task
        open_tasks = _count_open_tasks(lead.id)
        if open_tasks == 0:
            return 'create_task'
        # Priority 9 (default)
        return 'nurture'

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
        new_action = ActionEngineService.compute_recommended_action(lead)

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
