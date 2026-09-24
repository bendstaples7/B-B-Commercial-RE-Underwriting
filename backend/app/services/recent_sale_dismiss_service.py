"""Dismiss incorrect recent-sale holds (wrong unit / wrong PIN sale)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.services.lead_task_service import complete_native_task_mirror

logger = logging.getLogger(__name__)


def clear_recent_sale_hold_tasks(
    lead_id: int,
    *,
    actor: str = 'anonymous',
    reason: str = 'dismiss_recent_sale',
    commit: bool = True,
) -> list[int]:
    """Complete open ``recent_sale_hold`` tasks for a lead. Returns task ids."""
    now = datetime.now(timezone.utc)
    tasks = (
        LeadTask.query
        .filter_by(
            lead_id=lead_id,
            status='open',
            workflow_key='recent_sale_hold',
        )
        .all()
    )
    completed_ids: list[int] = []
    for task in tasks:
        task.status = 'completed'
        task.completed_at = now
        complete_native_task_mirror(task, now)
        db.session.add(LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_completed',
            occurred_at=now,
            source='manual',
            actor=actor,
            summary=f'Task completed: {task.title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'reason': reason,
            },
        ))
        completed_ids.append(task.id)
    if commit and completed_ids:
        db.session.commit()
    return completed_ids


def dismiss_incorrect_recent_sale(
    lead: Lead,
    *,
    actor: str = 'anonymous',
    reason: str = 'not_this_unit',
    clear_pin: bool = True,
) -> dict[str, Any]:
    """Clear sale fields + lift recent-sale hold after a false-positive sale.

    Typical case: building-level GIS matched an arbitrary condo PIN and stamped
    that unit's sale onto a different door. Clears sale dates, optionally the
    PIN, completes open ``recent_sale_hold`` tasks, and re-enables skip-trace
    work when the lead is still in the skip-trace pipeline.
    """
    from app.services.lead_merge_utils import situs_unit_token_from_parts
    from app.services.lead_refresh import refresh_lead_scoring
    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    before = {
        'most_recent_sale': lead.most_recent_sale,
        'acquisition_date': (
            lead.acquisition_date.isoformat()
            if getattr(lead, 'acquisition_date', None) is not None
            else None
        ),
        'most_recent_sale_price': lead.most_recent_sale_price,
        'county_assessor_pin': lead.county_assessor_pin,
        'lead_status': lead.lead_status,
        'needs_skip_trace': bool(getattr(lead, 'needs_skip_trace', False)),
    }

    lead.most_recent_sale = None
    lead.acquisition_date = None
    lead.most_recent_sale_price = None
    pin_cleared = False
    unit_token = situs_unit_token_from_parts(
        lead.property_street,
        getattr(lead, 'address_2', None),
    )
    # Clear PIN when the situs names a unit, or the caller explicitly says
    # the PIN itself is wrong — not for a bare accidental dismiss on SFH.
    if clear_pin and (unit_token or reason == 'wrong_pin_sale'):
        if lead.county_assessor_pin:
            pin_cleared = True
        lead.county_assessor_pin = None
        lead.has_property_match = False

    completed_ids = clear_recent_sale_hold_tasks(
        lead.id,
        actor=actor,
        reason=reason,
        commit=False,
    )

    # Mid-hold parks often sit in skip_trace with needs=False. After dismissing
    # a false sale, resume skip-trace work rather than leaving a mute hold.
    if lead.lead_status in ('skip_trace', 'deprioritize'):
        if lead.lead_status == 'deprioritize':
            lead.lead_status = 'skip_trace'
        lead.needs_skip_trace = True

    now = datetime.now(timezone.utc)
    db.session.add(LeadTimelineEntry(
        lead_id=lead.id,
        event_type='property_overview_changed',
        occurred_at=now,
        source='manual',
        actor=actor,
        summary='Dismissed incorrect recent sale'[:500],
        event_metadata={
            'reason': reason,
            'cleared': before,
            'pin_cleared': pin_cleared,
            'completed_hold_task_ids': completed_ids,
        },
    ))
    db.session.add(lead)
    db.session.commit()

    if lead.lead_status == 'skip_trace' and lead.needs_skip_trace:
        try:
            SkipTraceEnqueue().enqueue(
                lead.id,
                actor=actor,
                reason='Recent sale dismissed — verify owner',
            )
        except Exception:
            logger.exception(
                'Could not enqueue skip trace after dismissing sale for lead %s',
                lead.id,
            )

    refresh_lead_scoring(lead.id)
    db.session.refresh(lead)

    return {
        'lead_id': lead.id,
        'cleared_sale': True,
        'pin_cleared': pin_cleared,
        'completed_hold_task_ids': completed_ids,
        'lead_status': lead.lead_status,
        'recommended_action': lead.recommended_action,
        'needs_skip_trace': bool(lead.needs_skip_trace),
        'most_recent_sale': lead.most_recent_sale,
        'county_assessor_pin': lead.county_assessor_pin,
    }
