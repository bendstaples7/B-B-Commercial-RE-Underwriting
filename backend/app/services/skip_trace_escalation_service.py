"""Skip-trace escalation after undeliverable mail (invalid_address / Failed).

Single writer for the multi-source ladder: next unused source → skip_trace,
or exhausted queue when every connected source has been tried this cycle.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import db
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.skip_trace_attempt import SkipTraceAttempt
from app.services.skip_trace_source_registry import SkipTraceSourceRegistry

logger = logging.getLogger(__name__)


class SkipTraceEscalationService:
    """Escalate invalid mail outcomes into the skip-trace source ladder."""

    def __init__(self):
        self._registry = SkipTraceSourceRegistry()

    def escalate_from_invalid_mail(
        self,
        lead_id: int,
        *,
        actor: str,
        mail_queue_item_id: int | None = None,
        olc_order_id: str | None = None,
        validation_error: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Handle MailQueueItem → invalid_address (or OLC Failed undeliverable).

        Returns a summary dict: action in (assigned_next_source, exhausted, noop).
        """
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            return {'lead_id': lead_id, 'action': 'noop', 'reason': 'lead_not_found'}

        if lead.skip_trace_exhausted_at is not None:
            return {
                'lead_id': lead_id,
                'action': 'noop',
                'reason': 'already_exhausted',
            }

        # Already assigned a next source with an open handoff — do not duplicate
        if (
            lead.skip_trace_next_source_id
            and lead.lead_status == 'skip_trace'
            and lead.needs_skip_trace
        ):
            from app.models.lead_task import LeadTask
            open_handoff = (
                LeadTask.query
                .filter_by(lead_id=lead_id, task_type='skip_trace_owner', status='open')
                .first()
            )
            if open_handoff is not None:
                return {
                    'lead_id': lead_id,
                    'action': 'noop',
                    'reason': 'already_escalated',
                    'source_id': lead.skip_trace_next_source_id,
                }

        cycle = int(getattr(lead, 'skip_trace_cycle', None) or 1)
        self._mark_last_completed_failed_address(
            lead,
            cycle=cycle,
            mail_queue_item_id=mail_queue_item_id,
            olc_order_id=olc_order_id,
        )

        used = self._used_source_ids(lead_id, cycle)
        sources = self._registry.list_sources(enabled_only=True)
        next_src = next((s for s in sources if s['id'] not in used), None)

        if next_src is None:
            return self._mark_exhausted(
                lead,
                actor=actor,
                validation_error=validation_error,
                commit=commit,
            )

        return self._assign_next_source(
            lead,
            source=next_src,
            cycle=cycle,
            actor=actor,
            mail_queue_item_id=mail_queue_item_id,
            olc_order_id=olc_order_id,
            validation_error=validation_error,
            commit=commit,
        )

    def record_source_completed(
        self,
        lead_id: int,
        *,
        source_id: str | None = None,
        actor: str = 'system',
        commit: bool = False,
    ) -> SkipTraceAttempt | None:
        """Stamp the active/next source as completed; update skip_tracer display.

        Does not advance ``skip_trace_cycle`` — the cycle resets only when an
        exhausted ladder is cleared (new sources / manual retry).
        """
        lead = Lead.query.get(lead_id)
        if lead is None:
            return None
        cycle = int(getattr(lead, 'skip_trace_cycle', None) or 1)
        sid = (source_id or lead.skip_trace_next_source_id or '').strip()
        if not sid:
            sources = self._registry.list_sources(enabled_only=True)
            sid = sources[0]['id'] if sources else 'manual_default'
        src = self._registry.get_source(sid) or {
            'id': sid,
            'label': sid,
        }

        attempt = (
            SkipTraceAttempt.query
            .filter_by(lead_id=lead_id, cycle=cycle, source_id=sid, outcome='started')
            .order_by(SkipTraceAttempt.id.desc())
            .first()
        )
        now = datetime.now(timezone.utc)
        if attempt is None:
            attempt = SkipTraceAttempt(
                lead_id=lead_id,
                cycle=cycle,
                source_id=src['id'],
                source_label=src.get('label') or src['id'],
                started_at=now,
                trigger='manual_move',
                outcome='started',
            )
            db.session.add(attempt)
        attempt.outcome = 'completed'
        attempt.completed_at = now
        lead.skip_tracer = attempt.source_label
        lead.skip_trace_next_source_id = None
        lead.skip_trace_exhausted_at = None
        db.session.add(lead)
        if commit:
            db.session.commit()
        return attempt

    def clear_exhausted_for_retry(self, lead_id: int, *, actor: str = 'system') -> Lead | None:
        """Clear exhausted flag and advance cycle so prior attempts no longer count."""
        lead = Lead.query.get(lead_id)
        if lead is None:
            return None
        lead.skip_trace_exhausted_at = None
        lead.skip_trace_cycle = int(getattr(lead, 'skip_trace_cycle', None) or 1) + 1
        lead.skip_trace_next_source_id = None
        db.session.add(lead)
        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='system',
            actor=actor,
            summary='Skip-trace exhausted queue cleared — new source cycle started',
            event_metadata={'reason': 'skip_trace_cycle_reset'},
            is_deleted=False,
        ))
        return lead

    def list_attempts_for_lead(self, lead_id: int) -> list[dict[str, Any]]:
        rows = (
            SkipTraceAttempt.query
            .filter_by(lead_id=lead_id)
            .order_by(SkipTraceAttempt.cycle.asc(), SkipTraceAttempt.id.asc())
            .all()
        )
        return [
            {
                'id': r.id,
                'cycle': r.cycle,
                'source_id': r.source_id,
                'source_label': r.source_label,
                'outcome': r.outcome,
                'trigger': r.trigger,
                'started_at': r.started_at.isoformat() if r.started_at else None,
                'completed_at': r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]

    def _used_source_ids(self, lead_id: int, cycle: int) -> set[str]:
        rows = (
            SkipTraceAttempt.query
            .filter(
                SkipTraceAttempt.lead_id == lead_id,
                SkipTraceAttempt.cycle == cycle,
                SkipTraceAttempt.outcome.in_(('completed', 'failed_address')),
            )
            .all()
        )
        return {r.source_id for r in rows}

    def _mark_last_completed_failed_address(
        self,
        lead: Lead,
        *,
        cycle: int,
        mail_queue_item_id: int | None,
        olc_order_id: str | None,
    ) -> None:
        """Attribute this undeliverable to the last completed source in this cycle."""
        prior = (
            SkipTraceAttempt.query
            .filter(
                SkipTraceAttempt.lead_id == lead.id,
                SkipTraceAttempt.cycle == cycle,
                SkipTraceAttempt.outcome == 'completed',
            )
            .order_by(SkipTraceAttempt.id.desc())
            .first()
        )
        if prior is None:
            return
        exists = (
            SkipTraceAttempt.query
            .filter_by(
                lead_id=lead.id,
                cycle=cycle,
                source_id=prior.source_id,
                outcome='failed_address',
            )
            .first()
        )
        if exists is not None:
            return
        # Flip completed → failed_address so the source counts as used
        prior.outcome = 'failed_address'
        prior.completed_at = datetime.now(timezone.utc)
        prior.trigger = 'invalid_mail'
        if mail_queue_item_id is not None:
            prior.mail_queue_item_id = mail_queue_item_id
        if olc_order_id:
            prior.olc_order_id = olc_order_id
        db.session.add(prior)
    def _assign_next_source(
        self,
        lead: Lead,
        *,
        source: dict[str, Any],
        cycle: int,
        actor: str,
        mail_queue_item_id: int | None,
        olc_order_id: str | None,
        validation_error: str | None,
        commit: bool,
    ) -> dict[str, Any]:
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        lead.skip_trace_next_source_id = source['id']
        lead.skip_trace_exhausted_at = None
        db.session.add(lead)

        started = (
            SkipTraceAttempt.query
            .filter_by(
                lead_id=lead.id,
                cycle=cycle,
                source_id=source['id'],
                outcome='started',
            )
            .first()
        )
        if started is None:
            db.session.add(SkipTraceAttempt(
                lead_id=lead.id,
                cycle=cycle,
                source_id=source['id'],
                source_label=source['label'],
                started_at=datetime.now(timezone.utc),
                outcome='started',
                trigger='invalid_mail',
                mail_queue_item_id=mail_queue_item_id,
                olc_order_id=olc_order_id,
            ))

        label = source['label']
        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='system',
            actor=actor,
            summary=f'Skip trace — try {label} after undeliverable mail',
            event_metadata={
                'reason': 'invalid_mail_escalation',
                'source_id': source['id'],
                'source_label': label,
                'mail_queue_item_id': mail_queue_item_id,
                'olc_order_id': olc_order_id,
                'validation_error': (validation_error or '')[:300] or None,
            },
            is_deleted=False,
        ))

        # Move / ensure skip_trace handoff (idempotent when already there)
        enqueue = SkipTraceEnqueue()
        try:
            move_result = enqueue.move_to_skip_trace(
                lead.id,
                actor=actor,
                commit=False,
                reason='invalid_mail_escalation',
            )
        except Exception:
            logger.exception(
                'skip-trace escalation move failed for lead %s; rolling back assignment',
                lead.id,
            )
            db.session.rollback()
            return {
                'lead_id': lead.id,
                'action': 'move_failed',
                'source_id': source['id'],
                'source_label': label,
                'error': True,
            }

        self._retitle_open_handoff(lead.id, label)

        if commit:
            db.session.commit()
            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache
            try:
                refresh_lead_scoring(lead.id)
            except Exception:
                logger.exception('refresh after skip-trace escalation failed lead=%s', lead.id)
            queue_order_cache.clear()

            pending_hs = move_result.get('pending_hubspot_ids') or []
            handoff_clear = move_result.get('handoff_clear_ids') or []
            if pending_hs:
                from app.services.hubspot_task_completion_service import (
                    sync_pending_hubspot_completions,
                )
                sync_pending_hubspot_completions(list(pending_hs))
            if handoff_clear:
                from app.services.hubspot_task_completion_service import (
                    sync_hubspot_task_properties,
                )
                for hs_id in handoff_clear:
                    sync_hubspot_task_properties(
                        hs_id,
                        title=f'Skip trace — {label}',
                        clear_due_date=True,
                    )

        return {
            'lead_id': lead.id,
            'action': 'assigned_next_source',
            'source_id': source['id'],
            'source_label': label,
            'move': move_result,
        }

    def _mark_exhausted(
        self,
        lead: Lead,
        *,
        actor: str,
        validation_error: str | None,
        commit: bool,
    ) -> dict[str, Any]:
        lead.skip_trace_exhausted_at = datetime.now(timezone.utc)
        lead.skip_trace_next_source_id = None
        db.session.add(lead)
        db.session.add(LeadTimelineEntry(
            lead_id=lead.id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='system',
            actor=actor,
            summary='Skip-trace sources exhausted — added to investigate queue',
            event_metadata={
                'reason': 'skip_trace_exhausted',
                'validation_error': (validation_error or '')[:300] or None,
            },
            is_deleted=False,
        ))
        if commit:
            db.session.commit()
        return {
            'lead_id': lead.id,
            'action': 'exhausted',
        }

    @staticmethod
    def _retitle_open_handoff(lead_id: int, source_label: str) -> None:
        from app.models.lead_task import LeadTask

        task = (
            LeadTask.query
            .filter_by(lead_id=lead_id, task_type='skip_trace_owner', status='open')
            .order_by(LeadTask.id.desc())
            .first()
        )
        if task is None:
            return
        title = f'Skip trace — {source_label}'
        if task.title != title:
            task.title = title
            db.session.add(task)
