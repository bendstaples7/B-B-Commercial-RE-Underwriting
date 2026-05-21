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
    """Return the number of open LeadTask records for the given lead."""
    return LeadTask.query.filter_by(lead_id=lead_id, status='open').count()


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
        # Priority 2
        if lead.lead_status in ('suppressed', 'nurture'):
            return None
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
            return 'enrich_data'  # Req 22.1: no address → enrich_data, not resolve_match
        # Priority 5
        if has_property_match and not lead.analysis_complete:
            return 'analyze_property'
        # Priority 6
        if lead.follow_up_overdue:
            return 'follow_up_now'
        # Priority 7
        if lead.is_warm:
            return 'follow_up_now'
        # Priority 8
        if lead.analysis_complete and lead.lead_score >= 70:
            open_tasks = _count_open_tasks(lead.id)
            if open_tasks == 0:
                return 'ready_for_outreach'
        # Priority 9
        if lead.data_completeness_score < 50:
            return 'enrich_data'
        # Priority 10
        if lead.lead_status in ('active', 'new'):
            open_tasks = _count_open_tasks(lead.id)
            if open_tasks == 0:
                return 'create_task'
        # Priority 11 (default)
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
