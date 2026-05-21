"""CallLogService — native call and note logging for leads."""
from datetime import datetime, date, timezone

from app import db
from app.models import Lead, LeadTimelineEntry
from app.exceptions import (
    DoNotContactViolationError,
    LeadTaskValidationError,
)

VALID_CALL_OUTCOMES = frozenset(['answered', 'voicemail', 'no_answer', 'busy', 'wrong_number'])


class CallLogService:
    """Handles logging calls and notes on leads."""

    def log_call(
        self,
        lead_id: int,
        outcome: str,
        duration_minutes: int | None,
        notes: str | None,
        actor: str = 'anonymous',
    ) -> LeadTimelineEntry:
        """Log a call on a lead.

        - Validates outcome is one of the valid values
        - Validates duration 1–999 if provided
        - Raises DoNotContactViolationError if lead is DNC
        - Updates signals based on outcome:
            answered → update last_contact_date
            voicemail/no_answer → increment unanswered_call_count
            wrong_number → set has_phone=False
        - Appends call_logged timeline entry
        - Triggers RA recomputation
        - Auto-transitions lead_status from 'new' → 'active'
        """
        if outcome not in VALID_CALL_OUTCOMES:
            raise LeadTaskValidationError(
                f"Invalid call outcome '{outcome}'. Must be one of: {', '.join(sorted(VALID_CALL_OUTCOMES))}",
                field='outcome',
            )

        if duration_minutes is not None and not (1 <= duration_minutes <= 999):
            raise LeadTaskValidationError(
                "Call duration must be between 1 and 999 minutes.",
                field='duration_minutes',
            )

        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        if lead.lead_status == 'do_not_contact':
            raise DoNotContactViolationError(lead_id)

        # Update signals based on outcome
        if outcome == 'answered':
            lead.last_contact_date = date.today()
        elif outcome in ('voicemail', 'no_answer'):
            lead.unanswered_call_count = (lead.unanswered_call_count or 0) + 1
        elif outcome == 'wrong_number':
            lead.has_phone = False

        # Auto-transition new → active
        if lead.lead_status == 'new':
            lead.lead_status = 'active'

        db.session.add(lead)

        # Build summary
        summary_parts = [f"Call logged: {outcome}"]
        if duration_minutes:
            summary_parts.append(f"{duration_minutes} min")
        if notes:
            summary_parts.append(notes[:200])
        summary = '. '.join(summary_parts)[:500]

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='call_logged',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=summary,
            event_metadata={
                'outcome': outcome,
                'duration_minutes': duration_minutes,
                'notes': notes,
            },
        )
        db.session.add(entry)
        db.session.commit()

        # Trigger RA recomputation
        try:
            from app.services.action_engine_service import ActionEngineService
            ActionEngineService.recompute_and_persist(lead_id)
        except Exception:
            pass

        return entry

    def log_note(
        self,
        lead_id: int,
        body: str,
        actor: str = 'anonymous',
    ) -> LeadTimelineEntry:
        """Log a note on a lead.

        - Validates body 1–5,000 chars
        - Raises DoNotContactViolationError if lead is DNC
        - Appends note_added timeline entry
        - Triggers RA recomputation
        - Auto-transitions lead_status from 'new' → 'active'
        """
        if not body or not body.strip():
            raise LeadTaskValidationError("Note body cannot be empty.", field='body')

        if len(body) > 5000:
            raise LeadTaskValidationError(
                "Note body cannot exceed 5,000 characters.",
                field='body',
            )

        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        if lead.lead_status == 'do_not_contact':
            raise DoNotContactViolationError(lead_id)

        # Auto-transition new → active
        if lead.lead_status == 'new':
            lead.lead_status = 'active'
            db.session.add(lead)

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=body[:500],
            event_metadata={'body': body},
        )
        db.session.add(entry)
        db.session.commit()

        # Trigger RA recomputation
        try:
            from app.services.action_engine_service import ActionEngineService
            ActionEngineService.recompute_and_persist(lead_id)
        except Exception:
            pass

        return entry
