"""Heal skip_trace leads that already have a complete owner mailing address.

These leads were often stuck by the unify-skip-trace migration (undated
``awaiting_skip_trace_handoff``) and/or HubSpot ``Awaiting Skip Trace`` pull:
``needs_skip_trace=True`` blocked scoring promotion even though mailing was
already complete and the sale was outside the recent-sale hold window.

Canonical heal:
1. Complete open skip-trace handoffs (system handoffs by default)
2. Clear ``needs_skip_trace``
3. Promote to ``mailing_no_contact_made`` via the same residential/mailable gate
4. Timeline + optional rescore
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services import scoring_rubric as rubric
from app.services.lead_scoring_engine import (
    _is_commercial_lead,
    promote_skip_trace_to_mailing_if_eligible,
)
from app.services.lead_task_service import complete_native_task_mirror
from app.services.open_letter_contact_mapper import is_owner_mailable_lead

logger = logging.getLogger(__name__)

HEAL_ACTOR = 'heal_mailable_skip_trace'
HEAL_REASON = 'mailable_skip_trace_heal'
SYSTEM_HANDOFF_WORKFLOW_KEY = 'awaiting_skip_trace_handoff'


class SkipTraceMailableHealService:
    """Promote residential mailable skip_trace leads off active skip work."""

    def candidate_query(self):
        """Base query: active skip work with non-empty mailing street (SQL prefilter)."""
        return (
            Lead.query.filter(
                Lead.lead_status == 'skip_trace',
                Lead.needs_skip_trace.is_(True),
                Lead.mailing_address.isnot(None),
                db.func.trim(Lead.mailing_address) != '',
            )
            .order_by(Lead.id)
        )

    def _open_skip_trace_tasks(self, lead_id: int) -> list[LeadTask]:
        return (
            LeadTask.query.filter(
                LeadTask.lead_id == lead_id,
                LeadTask.task_type == 'skip_trace_owner',
                LeadTask.status == 'open',
            )
            .order_by(LeadTask.id.asc())
            .all()
        )

    def _is_system_handoff(self, task: LeadTask) -> bool:
        return (task.workflow_key or '') == SYSTEM_HANDOFF_WORKFLOW_KEY

    def is_heal_candidate(
        self,
        lead: Lead,
        *,
        include_manual: bool = False,
    ) -> bool:
        if lead.lead_status != 'skip_trace':
            return False
        if not bool(getattr(lead, 'needs_skip_trace', False)):
            return False
        if _is_commercial_lead(lead):
            return False
        if rubric.is_recently_sold(lead):
            return False
        if not is_owner_mailable_lead(lead):
            return False
        # Mid-hold should already have needs_skip_trace=False; belt-and-suspenders.
        from app.services.skip_trace_enqueue import SkipTraceEnqueue
        if SkipTraceEnqueue._find_open_future_recent_sale_hold(lead.id) is not None:
            return False

        if include_manual:
            return True

        open_tasks = self._open_skip_trace_tasks(lead.id)
        if not open_tasks:
            # Orphan needs flag with no open skip work — safe to clear + promote.
            return True
        # Default: only system unify / awaiting handoffs (not intentional research tasks).
        return any(self._is_system_handoff(t) for t in open_tasks)

    def list_candidates(
        self,
        *,
        limit: int | None = None,
        include_manual: bool = False,
    ) -> list[Lead]:
        q = self.candidate_query()
        if limit is not None:
            q = q.limit(max(limit * 3, limit))  # over-fetch; Python filter may drop some
        leads = q.all()
        out = [
            lead for lead in leads
            if self.is_heal_candidate(lead, include_manual=include_manual)
        ]
        if limit is not None:
            return out[:limit]
        return out

    def heal_lead(
        self,
        lead: Lead,
        *,
        actor: str = HEAL_ACTOR,
        commit: bool = True,
        rescore: bool = True,
        include_manual: bool = False,
    ) -> dict[str, Any]:
        """Heal one lead. Returns a result dict; no-ops when not eligible.

        ``healed`` is True only when status was promoted to mailing.
        ``needs_cleared`` is True whenever the needs flag was cleared.
        """
        if not self.is_heal_candidate(lead, include_manual=include_manual):
            return {
                'lead_id': lead.id,
                'healed': False,
                'needs_cleared': False,
                'promoted': False,
                'reason': 'not_eligible',
                'lead_status': lead.lead_status,
                'needs_skip_trace': bool(getattr(lead, 'needs_skip_trace', False)),
            }

        open_handoffs = self._open_skip_trace_tasks(lead.id)
        if include_manual:
            to_complete = open_handoffs
        else:
            to_complete = [t for t in open_handoffs if self._is_system_handoff(t)]

        now = datetime.now(timezone.utc)
        completed_task_ids: list[int] = []
        for task in to_complete:
            task.status = 'completed'
            task.completed_at = now
            db.session.add(task)
            complete_native_task_mirror(task, now)
            completed_task_ids.append(task.id)
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='task_completed',
                occurred_at=now,
                source='system',
                actor=actor,
                summary=(
                    f"Task completed: {task.title or 'Awaiting skip trace'} "
                    f"(mailable skip-trace heal)"
                ),
                event_metadata={
                    'task_id': task.id,
                    'task_type': task.task_type,
                    'reason': HEAL_REASON,
                    'workflow_key': task.workflow_key,
                },
            ))

        lead.needs_skip_trace = False
        previous = promote_skip_trace_to_mailing_if_eligible(lead)
        promoted = previous is not None
        if promoted:
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='status_changed',
                occurred_at=now,
                source='system',
                actor=actor,
                summary=(
                    f"Status changed from '{previous}' to 'mailing_no_contact_made' "
                    f"(residential lead has mailing address; skip handoff cleared)."
                ),
                event_metadata={
                    'previous_status': previous,
                    'new_status': 'mailing_no_contact_made',
                    'reason': HEAL_REASON,
                    'completed_task_ids': completed_task_ids,
                },
            ))
        else:
            # needs cleared but promote refused (race / incomplete address after check)
            logger.info(
                'heal cleared needs_skip_trace without promote lead_id=%s status=%s',
                lead.id,
                lead.lead_status,
            )

        db.session.add(lead)
        if commit:
            db.session.commit()
            if rescore and promoted:
                try:
                    from app.services.lead_refresh import refresh_lead_scoring
                    refresh_lead_scoring(lead.id)
                except Exception as exc:
                    logger.warning(
                        'heal rescore failed lead_id=%s: %s', lead.id, exc,
                    )

        return {
            'lead_id': lead.id,
            'healed': promoted,
            'needs_cleared': True,
            'promoted': promoted,
            'lead_status': lead.lead_status,
            'needs_skip_trace': bool(lead.needs_skip_trace),
            'completed_task_ids': completed_task_ids,
            'property_street': lead.property_street,
            'mailing_address': lead.mailing_address,
        }

    def heal_all(
        self,
        *,
        actor: str = HEAL_ACTOR,
        commit: bool = False,
        limit: int | None = None,
        rescore: bool = True,
        include_manual: bool = False,
    ) -> dict[str, Any]:
        candidates = self.list_candidates(
            limit=limit, include_manual=include_manual,
        )
        results: list[dict[str, Any]] = []
        if not commit:
            for lead in candidates:
                open_count = LeadTask.query.filter(
                    LeadTask.lead_id == lead.id,
                    LeadTask.task_type == 'skip_trace_owner',
                    LeadTask.status == 'open',
                ).count()
                results.append({
                    'lead_id': lead.id,
                    'healed': False,
                    'needs_cleared': False,
                    'promoted': False,
                    'dry_run': True,
                    'lead_status': lead.lead_status,
                    'needs_skip_trace': True,
                    'open_handoffs': open_count,
                    'property_street': lead.property_street,
                    'mailing_address': lead.mailing_address,
                })
            return {
                'mode': 'dry-run',
                'candidate_count': len(candidates),
                'healed_count': 0,
                'promoted_count': 0,
                'needs_cleared_count': 0,
                'results': results,
            }

        healed = 0
        promoted = 0
        needs_cleared = 0
        for lead in candidates:
            try:
                result = self.heal_lead(
                    lead,
                    actor=actor,
                    commit=True,
                    rescore=rescore,
                    include_manual=include_manual,
                )
                results.append(result)
                if result.get('healed'):
                    healed += 1
                if result.get('promoted'):
                    promoted += 1
                if result.get('needs_cleared'):
                    needs_cleared += 1
            except Exception as exc:
                db.session.rollback()
                logger.exception('heal failed lead_id=%s', lead.id)
                results.append({
                    'lead_id': lead.id,
                    'healed': False,
                    'needs_cleared': False,
                    'promoted': False,
                    'reason': 'error',
                    'error': str(exc),
                })

        return {
            'mode': 'apply',
            'candidate_count': len(candidates),
            'healed_count': healed,
            'promoted_count': promoted,
            'needs_cleared_count': needs_cleared,
            'results': results,
        }
