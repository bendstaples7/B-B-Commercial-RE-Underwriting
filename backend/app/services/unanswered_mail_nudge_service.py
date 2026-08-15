"""User nudge after unanswered call streak — do not auto-convert to Direct Mail."""
from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.mail_task_lifecycle_service import complete_tasks_superseded_by_mail
from app.services.lead_refresh import refresh_lead_scoring

UNANSWERED_MAIL_NUDGE_THRESHOLD = 3


def unanswered_mail_nudge_owed(lead: Lead) -> bool:
    """True when the lead should show the Keep calling / Switch to Direct Mail dialog."""
    unanswered = int(getattr(lead, 'unanswered_call_count', 0) or 0)
    if unanswered < UNANSWERED_MAIL_NUDGE_THRESHOLD:
        return False
    if not getattr(lead, 'has_phone', False):
        return False
    if getattr(lead, 'prefer_direct_mail', False):
        return False
    dismissed = getattr(lead, 'unanswered_mail_nudge_dismissed_count', None)
    if dismissed is not None and int(dismissed) >= unanswered:
        return False
    return True


def dismiss_unanswered_mail_nudge(lead_id: int, *, actor: str = 'anonymous') -> Lead:
    lead = db.session.get(Lead, lead_id)
    if lead is None:
        raise ValueError(f'Lead {lead_id} not found')
    unanswered = int(lead.unanswered_call_count or 0)
    lead.unanswered_mail_nudge_dismissed_count = unanswered
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary='Chose Keep calling after unanswered-mail nudge',
            event_metadata={
                'unanswered_mail_nudge': 'keep_calling',
                'unanswered_call_count': unanswered,
            },
        ),
    )
    db.session.commit()
    return lead


def switch_to_direct_mail_from_nudge(lead_id: int, *, actor: str = 'anonymous') -> Lead:
    """User-confirmed convert: sticky mail preference + supersede open call tasks.

    Does **not** write ``recommended_action`` / ``recommended_contact_method`` —
    those stay owned by ``LeadScoringEngine`` via ``refresh_lead_scoring``.
    ``prefer_direct_mail`` makes ``evaluate_contact_method`` return ``direct_mail``.
    """
    lead = db.session.get(Lead, lead_id)
    if lead is None:
        raise ValueError(f'Lead {lead_id} not found')

    unanswered = int(lead.unanswered_call_count or 0)
    lead.unanswered_mail_nudge_dismissed_count = unanswered
    lead.prefer_direct_mail = True

    complete_tasks_superseded_by_mail(lead_id, actor=actor, commit=False)

    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary='Chose Switch to Direct Mail after unanswered-mail nudge',
            event_metadata={
                'unanswered_mail_nudge': 'switch_to_direct_mail',
                'unanswered_call_count': unanswered,
                'prefer_direct_mail': True,
            },
        ),
    )
    db.session.commit()
    refresh_lead_scoring(lead_id)
    db.session.refresh(lead)
    return lead
