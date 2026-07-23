"""Bidirectional mapping between HubSpot deal stage labels and platform lead_status."""
from __future__ import annotations

import datetime as dt

from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry

# HubSpot pipeline display label → platform lead_status
HS_STAGE_TO_LEAD_STATUS: dict[str, str] = {
    'Skip Trace': 'skip_trace',
    # Legacy HubSpot stage — platform unified on skip_trace only.
    'Awaiting Skip Trace': 'skip_trace',
    'Mailing, no contact made': 'mailing_no_contact_made',
    'Mailing, contact made, no interest': 'mailing_contacted_no_interest',
    'Mailing, contact made, interested': 'mailing_contacted_interested',
    'Negotiating Remote': 'negotiating_remote',
    'In Person Appointment': 'in_person_appointment',
    'Offer Delivered': 'offer_delivered',
    'Deprioritize': 'deprioritize',
    'Deal Won': 'deal_won',
    'Deal Lost': 'deal_lost',
}

# Platform → HubSpot (one canonical label per status)
LEAD_STATUS_TO_HS_STAGE: dict[str, str] = {
    'skip_trace': 'Skip Trace',
    'mailing_no_contact_made': 'Mailing, no contact made',
    'mailing_contacted_no_interest': 'Mailing, contact made, no interest',
    'mailing_contacted_interested': 'Mailing, contact made, interested',
    'negotiating_remote': 'Negotiating Remote',
    'in_person_appointment': 'In Person Appointment',
    'offer_delivered': 'Offer Delivered',
    'deprioritize': 'Deprioritize',
    'deal_won': 'Deal Won',
    'deal_lost': 'Deal Lost',
}


def hubspot_stage_label_for_lead_status(lead_status: str | None) -> str | None:
    """Return the HubSpot deal stage display label for a platform lead_status."""
    if not lead_status:
        return None
    return LEAD_STATUS_TO_HS_STAGE.get(lead_status)


def lead_status_from_hubspot_stage(stage_label: str | None) -> str | None:
    """Return platform lead_status for a HubSpot deal stage display label."""
    if not stage_label:
        return None
    return HS_STAGE_TO_LEAD_STATUS.get(stage_label)


def _as_utc_aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def manual_status_change_wins(lead: Lead) -> bool:
    """True when a manual status change should override HubSpot stage pull.

    A recent manual ``status_changed`` timeline entry (after ``last_hubspot_sync_at``)
    means the platform user intentionally set the status and HubSpot pull must not
    revert it.
    """
    latest_manual = (
        LeadTimelineEntry.query.filter_by(
            lead_id=lead.id,
            event_type='status_changed',
            source='manual',
        )
        .order_by(LeadTimelineEntry.occurred_at.desc())
        .first()
    )
    if latest_manual is None:
        return False

    manual_at = _as_utc_aware(latest_manual.occurred_at)
    sync_at = _as_utc_aware(lead.last_hubspot_sync_at)
    if sync_at is None:
        return True
    return manual_at >= sync_at
