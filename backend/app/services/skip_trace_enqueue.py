"""SkipTraceEnqueue — handoff from entity resolution (and future owners) to skip-trace.

v1 creates the existing manual ``skip_trace_owner`` LeadTask and sets
``needs_skip_trace``. A future ``SkipTraceService`` vendor integration should
replace only the body of :meth:`SkipTraceEnqueue.enqueue` — callers stay the same.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, exists, or_, text

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.task import Task
from app.exceptions import ActionNotApplicableError
from app.services.action_eligibility import evaluate_move_to_skip_trace
from app.services.lead_task_service import (
    LeadTaskService,
    complete_native_task_mirror,
)

logger = logging.getLogger(__name__)


def clear_dated_due_chores_entering_skip_trace(
    lead_id: int,
    *,
    actor: str,
    reason: str = 'entered_skip_trace',
    today: date | None = None,
    now: datetime | None = None,
) -> tuple[list[int], set[str]]:
    """Complete dated-due non-handoff chores when a lead enters ``skip_trace``.

    Prevents leftover custom/follow-up tasks from re-entering Today's Action
    after status becomes ``skip_trace`` without going through Move to Skip Trace.
    Skips undated skip-trace handoffs and open ``recent_sale_hold`` tasks.

    Returns ``(completed_task_ids, pending_hubspot_task_ids)``.
    """
    as_of = today or date.today()
    completed_at = now or datetime.now(timezone.utc)
    open_tasks = (
        LeadTask.query
        .filter(
            LeadTask.lead_id == lead_id,
            LeadTask.status == "open",
        )
        .order_by(
            LeadTask.due_date.asc().nullslast(),
            LeadTask.id.asc(),
        )
        .all()
    )
    completed_ids: list[int] = []
    pending_hubspot_ids: set[str] = set()
    for task in open_tasks:
        if SkipTraceEnqueue._is_undated_skip_trace_handoff(task):
            continue
        if task.workflow_key == "recent_sale_hold":
            continue
        if task.due_date is None or task.due_date > as_of:
            continue
        completed_via_hubspot = False
        if task.hubspot_task_id:
            from app.services.hubspot_task_completion_service import (
                mark_hubspot_task_completed_local,
            )

            local_completion = mark_hubspot_task_completed_local(
                lead_id,
                task.id,
                actor=actor,
                reason=reason,
            )
            if local_completion is not None:
                completed_ids.append(task.id)
                if local_completion.hubspot_task_id:
                    pending_hubspot_ids.add(local_completion.hubspot_task_id)
                completed_via_hubspot = True
        if not completed_via_hubspot:
            SkipTraceEnqueue._complete_task_and_log(
                task, completed_at, actor, reason=reason,
            )
            completed_ids.append(task.id)
        if task.task_type == 'run_property_analysis':
            from app.services.analysis_completion_service import (
                mark_lead_analysis_complete,
            )
            mark_lead_analysis_complete(
                lead_id,
                source='manual',
                actor=actor,
                recompute_action=False,
                commit=False,
            )
    return completed_ids, pending_hubspot_ids


def _contact_display_name(contact_id: int) -> Optional[str]:
    contact = Contact.query.filter_by(id=contact_id).first()
    if contact is None:
        return None
    parts = [
        str(part).strip()
        for part in (contact.first_name, contact.last_name)
        if part and str(part).strip()
    ]
    return " ".join(parts) if parts else None


class SkipTraceEnqueue:
    """Queue a contact/lead for skip tracing without calling a skip-trace vendor."""

    def __init__(self, task_service: Optional[LeadTaskService] = None) -> None:
        self._tasks = task_service or LeadTaskService()

    def enqueue(
        self,
        lead_id: int,
        contact_id: Optional[int] = None,
        *,
        actor: str = "entity_resolution",
        reason: str = "Entity manager resolved — run skip trace on person",
        due_date: Optional[date] = None,
        recompute_action: bool = True,
    ) -> Optional[LeadTask]:
        """Enqueue skip-trace work for *lead_id* / optional *contact_id*.

        Idempotent for open ``skip_trace_owner`` tasks: returns the existing
        open task instead of creating a duplicate.
        """
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            logger.warning("SkipTraceEnqueue: lead %s not found", lead_id)
            return None

        existing = (
            LeadTask.query
            .filter_by(lead_id=lead_id, task_type="skip_trace_owner", status="open")
            .first()
        )
        if existing is not None:
            lead.needs_skip_trace = True
            if due_date is not None:
                existing.due_date = due_date
            db.session.commit()
            logger.info(
                "SkipTraceEnqueue: open skip_trace_owner task already exists "
                "task_id=%s lead_id=%s contact_id=%s",
                existing.id, lead_id, contact_id,
            )
            return existing

        title = reason
        if contact_id is not None:
            display_name = _contact_display_name(contact_id)
            suffix = display_name or f"contact_id={contact_id}"
            title = f"{reason} ({suffix})"
        if len(title) > 255:
            title = title[:255]

        lead.needs_skip_trace = True
        db.session.flush()

        task = self._tasks.create(
            lead_id,
            {
                "task_type": "skip_trace_owner",
                "title": title,
                "due_date": due_date,
            },
            actor=actor,
            recompute_action=recompute_action,
        )
        logger.info(
            "SkipTraceEnqueue: created skip_trace_owner task_id=%s lead_id=%s "
            "contact_id=%s",
            task.id, lead_id, contact_id,
        )
        return task

    def move_to_skip_trace(
        self,
        lead_id: int,
        *,
        actor: str,
        complete_task_id: Optional[int] = None,
        commit: bool = True,
        reason: str = 'quick_action_move_to_skip_trace',
    ) -> dict:
        """Atomically complete current work and hand the lead to skip trace.

        Pass ``commit=False`` when the caller owns the surrounding transaction
        (e.g. invalid-mail escalation inside campaign sync).
        """
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        eligibility = evaluate_move_to_skip_trace(lead)
        if eligibility.already_done:
            today = date.today()
            future_hold = self._find_open_future_recent_sale_hold(lead_id, today=today)
            # Mid-hold: never convert the dated hold into a handoff or force
            # needs_skip_trace=True — that ends the recent-sale park early.
            if future_hold is not None:
                now = datetime.now(timezone.utc)
                completed_task_ids_out, pending_hubspot_ids = (
                    clear_dated_due_chores_entering_skip_trace(
                        lead_id,
                        actor=actor,
                        reason='moved_to_skip_trace',
                        today=today,
                        now=now,
                    )
                )
                if completed_task_ids_out and commit:
                    db.session.commit()
                    if pending_hubspot_ids:
                        from app.services.hubspot_task_completion_service import (
                            sync_pending_hubspot_completions,
                        )
                        sync_pending_hubspot_completions(sorted(pending_hubspot_ids))
                return {
                    "lead_id": lead_id,
                    "lead_status": lead.lead_status,
                    "lead_score": lead.lead_score,
                    "recommended_action": lead.recommended_action,
                    "completed_task_id": (
                        completed_task_ids_out[-1] if completed_task_ids_out else None
                    ),
                    "completed_task_ids": completed_task_ids_out,
                    "skip_trace_task_id": future_hold.id,
                    "changed": bool(completed_task_ids_out),
                    "healed": False,
                    "already_done": True,
                    "reason_code": eligibility.reason_code,
                    "pending_hubspot_ids": (
                        sorted(pending_hubspot_ids) if not commit else []
                    ),
                    "handoff_clear_ids": [],
                }

            # Reuse shared helpers so leftover dated custom/follow-ups (not only
            # skip_trace_owner) leave Today's Action, matching a fresh move.
            now = datetime.now(timezone.utc)
            completed_task_ids_out, pending_hubspot_ids = (
                clear_dated_due_chores_entering_skip_trace(
                    lead_id,
                    actor=actor,
                    reason='moved_to_skip_trace',
                    today=today,
                    now=now,
                )
            )
            had_undated = self._find_undated_skip_trace_handoff(lead_id) is not None
            skip_trace_task, handoff_clear_ids, extra_hs = (
                self.ensure_awaiting_skip_trace_handoff(
                    lead_id, actor=actor, commit=False,
                )
            )
            pending_hubspot_ids.update(extra_hs)
            healed_handoff = (
                bool(completed_task_ids_out)
                or bool(handoff_clear_ids)
                or bool(extra_hs)
                or not had_undated
                or not lead.needs_skip_trace
            )

            if healed_handoff:
                lead.needs_skip_trace = True
                db.session.add(lead)
                if commit:
                    db.session.commit()
                    from app.services.lead_refresh import refresh_lead_scoring

                    refresh_lead_scoring(lead_id)
                    db.session.refresh(lead)
                    if pending_hubspot_ids:
                        from app.services.hubspot_task_completion_service import (
                            sync_pending_hubspot_completions,
                        )
                        sync_pending_hubspot_completions(sorted(pending_hubspot_ids))
                    if handoff_clear_ids:
                        from app.services.hubspot_task_completion_service import (
                            sync_hubspot_task_properties,
                        )
                        for hs_id in sorted(handoff_clear_ids):
                            sync_hubspot_task_properties(
                                hs_id,
                                title='Awaiting skip trace',
                                clear_due_date=True,
                            )
            return {
                "lead_id": lead_id,
                "lead_status": lead.lead_status,
                "lead_score": lead.lead_score,
                "recommended_action": lead.recommended_action,
                "completed_task_id": (
                    completed_task_ids_out[-1] if completed_task_ids_out else None
                ),
                "completed_task_ids": completed_task_ids_out,
                "skip_trace_task_id": skip_trace_task.id,
                "changed": healed_handoff,
                "healed": healed_handoff,
                "already_done": not healed_handoff,
                "reason_code": None if healed_handoff else eligibility.reason_code,
                "pending_hubspot_ids": (
                    sorted(pending_hubspot_ids) if not commit else []
                ),
                "handoff_clear_ids": (
                    sorted(handoff_clear_ids) if not commit else []
                ),
            }
        if not eligibility.ok:
            raise ActionNotApplicableError(
                'move_to_skip_trace',
                eligibility.reason_code or 'terminal_status',
                eligibility.message or 'Move to Skip Trace is not available',
                already_done=False,
            )

        now = datetime.now(timezone.utc)
        today = date.today()
        # Clear every dated-due non-handoff chore so multi-task leaks cannot
        # re-enter Today's Action after status becomes skip_trace.
        completed_task_ids_out, pending_hubspot_ids = (
            clear_dated_due_chores_entering_skip_trace(
                lead_id,
                actor=actor,
                reason='moved_to_skip_trace',
                today=today,
                now=now,
            )
        )
        # Also honor an explicit complete_task_id (may be undated — e.g. a
        # current "Review returned mail" chore) without completing the handoff.
        if complete_task_id is not None:
            candidate = (
                LeadTask.query
                .filter_by(id=complete_task_id, lead_id=lead_id)
                .first()
            )
            if (
                candidate is not None
                and candidate.status == "open"
                and not self._is_undated_skip_trace_handoff(candidate)
                and candidate.id not in completed_task_ids_out
            ):
                if candidate.hubspot_task_id:
                    from app.services.hubspot_task_completion_service import (
                        mark_hubspot_task_completed_local,
                    )

                    local_completion = mark_hubspot_task_completed_local(
                        lead_id,
                        candidate.id,
                        actor=actor,
                        reason="moved_to_skip_trace",
                    )
                    if local_completion is not None:
                        completed_task_ids_out.append(candidate.id)
                        if local_completion.hubspot_task_id:
                            pending_hubspot_ids.add(local_completion.hubspot_task_id)
                    else:
                        self._complete_task_and_log(candidate, now, actor)
                        completed_task_ids_out.append(candidate.id)
                else:
                    self._complete_task_and_log(candidate, now, actor)
                    completed_task_ids_out.append(candidate.id)
                if candidate.task_type == 'run_property_analysis':
                    from app.services.analysis_completion_service import (
                        mark_lead_analysis_complete,
                    )
                    mark_lead_analysis_complete(
                        lead_id,
                        source='manual',
                        actor=actor,
                        recompute_action=False,
                        commit=False,
                    )

        old_status = lead.lead_status
        lead.lead_status = "skip_trace"
        lead.needs_skip_trace = True
        if old_status != "skip_trace":
            summary_reason = (
                'after undeliverable mail'
                if reason == 'invalid_mail_escalation'
                else 'from quick actions'
            )
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="status_changed",
                occurred_at=now,
                source="manual" if reason == 'quick_action_move_to_skip_trace' else 'system',
                actor=actor,
                summary=(
                    f"Status changed from '{old_status}' to 'skip_trace'. "
                    f"Moved to skip trace {summary_reason}."
                ),
                event_metadata={
                    "previous_status": old_status,
                    "new_status": "skip_trace",
                    "reason": reason,
                },
            ))

        # Prefer an existing undated handoff; otherwise convert leftover open
        # skip_trace_owner rows, or create a fresh undated placeholder.
        skip_trace_task, handoff_clear_ids, extra_hs = (
            self.ensure_awaiting_skip_trace_handoff(
                lead_id, actor=actor, commit=False,
            )
        )
        pending_hubspot_ids.update(extra_hs)

        if commit:
            db.session.commit()

            if pending_hubspot_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_pending_hubspot_completions,
                )
                sync_pending_hubspot_completions(sorted(pending_hubspot_ids))
            if handoff_clear_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_hubspot_task_properties,
                )
                for hs_id in sorted(handoff_clear_ids):
                    sync_hubspot_task_properties(
                        hs_id,
                        title='Awaiting skip trace',
                        clear_due_date=True,
                    )

            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache

            refresh_lead_scoring(lead_id)
            db.session.refresh(lead)
            queue_order_cache.clear()
        return {
            "lead_id": lead_id,
            "lead_status": "skip_trace",
            "lead_score": lead.lead_score,
            "recommended_action": lead.recommended_action,
            "completed_task_id": (
                completed_task_ids_out[-1] if completed_task_ids_out else None
            ),
            "completed_task_ids": completed_task_ids_out,
            "skip_trace_task_id": skip_trace_task.id,
            "changed": True,
            "already_done": False,
            "reason_code": None,
            "pending_hubspot_ids": sorted(pending_hubspot_ids) if not commit else [],
            "handoff_clear_ids": sorted(handoff_clear_ids) if not commit else [],
        }

    def schedule_recent_sale(
        self,
        lead_id: int,
        *,
        due_date: date,
        actor: str = "recent_sale_reconciliation",
        commit: bool = True,
    ) -> dict:
        """Schedule owner re-verification for the end of a recent-sale hold.

        The lead does not enter skip trace until ``due_date``. The hourly task
        activator performs that transition when the two-year hold expires.
        """
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            return {'scheduled': False, 'task_id': None, 'changed': False}
        if lead.lead_status in {
            "deprioritize",
            "deal_won",
            "deal_lost",
            "suppressed",
            "do_not_contact",
        }:
            return {'scheduled': False, 'task_id': None, 'changed': False}

        today = date.today()
        # Hold already converted to undated handoff or released verify work —
        # do not flip awaiting_skip_trace back to the holding stage / recreate.
        existing_open = (
            LeadTask.query
            .filter_by(
                lead_id=lead_id,
                task_type="skip_trace_owner",
                status="open",
            )
            .order_by(LeadTask.due_date.asc().nullslast(), LeadTask.id.asc())
            .all()
        )
        for existing in existing_open:
            if self._is_undated_skip_trace_handoff(existing):
                return {
                    'scheduled': False,
                    'task_id': existing.id,
                    'changed': False,
                    'hubspot_task_ids': [],
                }
            if (
                existing.workflow_key is None
                and self._is_recent_sale_verify_title(existing.title)
            ):
                return {
                    'scheduled': False,
                    'task_id': existing.id,
                    'changed': False,
                    'hubspot_task_ids': [],
                }

        task = next(
            (
                t for t in existing_open
                if t.workflow_key == "recent_sale_hold"
            ),
            None,
        )
        # Matured hold with a due date that is still today/past and the
        # caller is not extending it — leave activation to convert the task.
        if (
            task is not None
            and task.due_date is not None
            and task.due_date <= today
            and due_date <= today
        ):
            return {
                'scheduled': False,
                'task_id': task.id,
                'changed': False,
                'hubspot_task_ids': [],
            }
        title = "Recent-sale hold ended — verify new owner and contact information"
        task_changed = (
            task is None
            or task.due_date != due_date
            or task.title != title
        )
        scheduled = task is None or task.due_date != due_date
        if task is None:
            task = self._tasks.create(
                lead_id,
                {
                    "task_type": "skip_trace_owner",
                    "title": title,
                    "due_date": due_date,
                },
                actor=actor,
                recompute_action=False,
                commit=False,
            )
            task.workflow_key = "recent_sale_hold"
            db.session.add(task)
        else:
            task.title = title
            task.due_date = due_date
            db.session.add(task)
        from app.services.hubspot_task_completion_service import (
            mirror_crm_task_from_lead_task,
        )
        hubspot_task_ids: set[str] = set()
        mirror_changed = mirror_crm_task_from_lead_task(
            task,
            hubspot_task_ids,
        )

        # ``skip_trace`` holds during the recent-sale window (needs_skip_trace=False).
        # When the hold matures, stay on ``skip_trace`` with needs_skip_trace=True.
        lead_changed = lead.needs_skip_trace or lead.lead_status != "skip_trace"
        lead.needs_skip_trace = False
        old_status = lead.lead_status
        lead.lead_status = "skip_trace"
        db.session.add(lead)

        if scheduled:
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="task_snoozed",
                occurred_at=datetime.now(timezone.utc),
                source="system",
                actor=actor,
                summary=(
                    "Skip trace scheduled for the end of the recent-sale hold "
                    f"on {due_date.isoformat()}."
                ),
                event_metadata={
                    "task_id": task.id,
                    "task_type": "skip_trace_owner",
                    "due_date": due_date.isoformat(),
                    "reason": "recent_sale_hold_expiration",
                },
            ))
        if old_status != "skip_trace":
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="status_changed",
                occurred_at=datetime.now(timezone.utc),
                source="system",
                actor=actor,
                summary=(
                    f"Status changed from '{old_status}' to 'skip_trace' "
                    "for the recent-sale holding period."
                ),
                event_metadata={
                    "previous_status": old_status,
                    "new_status": "skip_trace",
                    "reason": "recent_sale_hold",
                    "due_date": due_date.isoformat(),
                },
            ))

        from app.services.mail_task_lifecycle_service import (
            complete_obsolete_outreach_during_recent_sale_hold,
        )
        completed_outreach, obsolete_hs_ids = (
            complete_obsolete_outreach_during_recent_sale_hold(
                lead_id,
                actor=actor,
                commit=False,
            )
        )

        if commit:
            db.session.commit()
            if hubspot_task_ids:
                from app.services.mail_task_lifecycle_service import (
                    sync_recent_sale_hubspot_due_dates,
                )
                sync_recent_sale_hubspot_due_dates(hubspot_task_ids, due_date)
            if obsolete_hs_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_pending_hubspot_completions,
                )
                sync_pending_hubspot_completions(obsolete_hs_ids)
            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache

            refresh_lead_scoring(lead_id)
            queue_order_cache.clear()

        return {
            'scheduled': scheduled,
            'task_id': task.id,
            'changed': (
                task_changed
                or mirror_changed
                or lead_changed
                or bool(completed_outreach)
            ),
            'hubspot_task_ids': sorted(hubspot_task_ids),
            'completed_obsolete_outreach_ids': completed_outreach,
            'completed_obsolete_hubspot_task_ids': obsolete_hs_ids,
        }

    def activate_due_recent_sale_tasks(
        self,
        *,
        actor: str = "recent_sale_skip_trace_activation",
        commit: bool = True,
        limit: int | None = None,
    ) -> dict:
        """Move matured recent-sale tasks into active skip-trace work.

        Converts dated verify tasks into the undated ``Awaiting skip trace``
        handoff so leads leave Today's Action after the hold expires. Also
        heals already-released dated post-hold tasks stuck in the queue.
        """
        today = date.today()
        hold_query = (
            LeadTask.query
            .filter(
                LeadTask.task_type == "skip_trace_owner",
                LeadTask.status == "open",
                LeadTask.due_date.isnot(None),
                LeadTask.due_date <= today,
                LeadTask.workflow_key == "recent_sale_hold",
            )
            .order_by(LeadTask.due_date.asc(), LeadTask.id.asc())
        )
        if limit is not None:
            hold_query = hold_query.limit(limit)

        hold_tasks = hold_query.all()
        activated_ids: list[int] = []
        retired_task_ids: list[int] = []
        released_hold_task_ids: list[int] = []
        healed_task_ids: list[int] = []
        scoring_lead_ids: set[int] = set()
        hubspot_task_ids: set[str] = set()
        hubspot_handoff_clear_ids: set[str] = set()
        now = datetime.now(timezone.utc)

        # After merges, a future hold task can sit on a mailing-stage lead.
        # Keep deal stage aligned with the holding workflow.
        hold_status_synced, obsolete_hs_from_sync = (
            self._sync_status_for_future_recent_sale_holds(
                actor=actor,
                now=now,
                today=today,
                limit=None if limit is None else max(limit, 0),
            )
        )
        scoring_lead_ids.update(hold_status_synced)
        hubspot_task_ids.update(obsolete_hs_from_sync)
        hold_status_synced_ids = list(hold_status_synced)
        for task in hold_tasks:
            lead = Lead.query.filter_by(id=task.lead_id).with_for_update().first()
            if lead is None or lead.lead_status in {
                "deprioritize",
                "deal_won",
                "deal_lost",
                "suppressed",
                "do_not_contact",
            }:
                task.status = "completed"
                task.completed_at = now
                db.session.add(task)
                if task.hubspot_task_id:
                    hubspot_task_ids.add(str(task.hubspot_task_id))
                if task.mirror_task_id:
                    mirror = db.session.get(Task, task.mirror_task_id)
                    if mirror is not None and mirror.hubspot_task_id:
                        hubspot_task_ids.add(str(mirror.hubspot_task_id))
                complete_native_task_mirror(task, now)
                retired_task_ids.append(task.id)
                continue
            if lead.lead_status != "skip_trace" or not lead.needs_skip_trace:
                old_status = lead.lead_status
                status_changed = lead.lead_status != "skip_trace"
                lead.lead_status = "skip_trace"
                lead.needs_skip_trace = True
                db.session.add(lead)
                if status_changed:
                    db.session.add(LeadTimelineEntry(
                        lead_id=lead.id,
                        event_type="status_changed",
                        occurred_at=now,
                        source="system",
                        actor=actor,
                        summary=(
                            f"Status changed from '{old_status}' to 'skip_trace' "
                            "when the recent-sale hold expired."
                        ),
                        event_metadata={
                            "previous_status": old_status,
                            "new_status": "skip_trace",
                            "reason": "recent_sale_hold_expired",
                            "task_id": task.id,
                        },
                    ))
                activated_ids.append(lead.id)
            else:
                lead.needs_skip_trace = True
                db.session.add(lead)
            self._convert_to_awaiting_handoff(task, hubspot_handoff_clear_ids)
            released_hold_task_ids.append(task.id)
            scoring_lead_ids.add(lead.id)

        # Heal already-released dated verify tasks (e.g. workflow_key cleared
        # but due date left open — still in Today's Action).
        remaining = None if limit is None else max(limit - len(hold_tasks), 0)
        if remaining is None or remaining > 0:
            healed = self._heal_dated_post_hold_skip_trace_tasks(
                actor=actor,
                now=now,
                today=today,
                limit=remaining,
                exclude_task_ids=set(released_hold_task_ids + retired_task_ids),
                hubspot_handoff_clear_ids=hubspot_handoff_clear_ids,
            )
            healed_task_ids.extend(healed["healed_task_ids"])
            activated_ids.extend(healed["activated_lead_ids"])
            scoring_lead_ids.update(healed["scoring_lead_ids"])

        remaining_stale = None if limit is None else max(
            limit - len(hold_tasks) - len(healed_task_ids),
            0,
        )
        stale_healed_lead_ids: list[int] = []
        if remaining_stale is None or remaining_stale > 0:
            stale = self._heal_post_hold_stale_contact_leads(
                actor=actor,
                now=now,
                limit=remaining_stale,
                exclude_lead_ids=set(activated_ids) | scoring_lead_ids,
                hubspot_handoff_clear_ids=hubspot_handoff_clear_ids,
                hubspot_completion_ids=hubspot_task_ids,
            )
            stale_healed_lead_ids = stale["activated_lead_ids"]
            activated_ids.extend(stale_healed_lead_ids)
            scoring_lead_ids.update(stale["scoring_lead_ids"])

        processed_lead_ids = list(dict.fromkeys(
            [task.lead_id for task in hold_tasks]
            + list(scoring_lead_ids)
        ))

        if commit and (
            activated_ids
            or retired_task_ids
            or released_hold_task_ids
            or healed_task_ids
            or stale_healed_lead_ids
            or hold_status_synced_ids
        ):
            db.session.commit()
            if hubspot_task_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_pending_hubspot_completions,
                )
                sync_pending_hubspot_completions(sorted(hubspot_task_ids))
            if hubspot_handoff_clear_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_hubspot_task_properties,
                )
                for hs_id in sorted(hubspot_handoff_clear_ids):
                    sync_hubspot_task_properties(
                        hs_id,
                        title='Awaiting skip trace',
                        clear_due_date=True,
                    )
            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache

            for lead_id in scoring_lead_ids:
                refresh_lead_scoring(lead_id)
            queue_order_cache.clear()

        return {
            "activated_lead_count": len(activated_ids),
            "activated_lead_ids": activated_ids,
            "retired_task_count": len(retired_task_ids),
            "retired_task_ids": retired_task_ids,
            "released_hold_task_ids": released_hold_task_ids,
            "healed_task_ids": healed_task_ids,
            "stale_contact_healed_lead_ids": stale_healed_lead_ids,
            "hold_status_synced_lead_ids": hold_status_synced_ids,
            "processed_task_count": (
                len(hold_tasks) + len(healed_task_ids) + len(stale_healed_lead_ids)
            ),
            "processed_lead_ids": processed_lead_ids,
        }

    def list_awaiting_skip_trace_due_leak_ids(
        self,
        *,
        today: date | None = None,
        limit: int | None = None,
        exclude_lead_ids: set[int] | None = None,
    ) -> list[int]:
        """Lead IDs in skip_trace (active) with a dated open task due today/earlier.

        These leak into Today's Action via custom chores instead of the undated
        skip-trace handoff. Mid-hold rows (``needs_skip_trace=False``) are excluded.
        """
        today = today or date.today()
        due_open = exists().where(
            and_(
                LeadTask.lead_id == Lead.id,
                LeadTask.status == "open",
                LeadTask.due_date.isnot(None),
                LeadTask.due_date <= today,
                or_(
                    LeadTask.workflow_key.is_(None),
                    LeadTask.workflow_key != "recent_sale_hold",
                ),
            )
        )
        query = (
            Lead.query
            .filter(
                Lead.lead_status == "skip_trace",
                Lead.needs_skip_trace.is_(True),
                due_open,
            )
            .with_entities(Lead.id)
            .order_by(Lead.id.asc())
        )
        if exclude_lead_ids:
            query = query.filter(~Lead.id.in_(exclude_lead_ids))
        if limit is not None:
            query = query.limit(max(limit, 0))
        return [row[0] for row in query.all()]

    def promote_awaiting_skip_trace_due_leaks(
        self,
        *,
        actor: str = "awaiting_skip_trace_due_leak_promote",
        commit: bool = True,
        limit: int | None = None,
        exclude_lead_ids: set[int] | None = None,
    ) -> dict:
        """Heal skip_trace + dated-due leaks into an undated handoff.

        Uses :meth:`move_to_skip_trace` (already-done path clears dated chores and
        ensures an undated handoff). When ``commit`` is False, returns candidate
        IDs only.
        """
        candidate_ids = self.list_awaiting_skip_trace_due_leak_ids(
            limit=limit,
            exclude_lead_ids=exclude_lead_ids,
        )
        if not commit:
            return {
                "promoted_lead_count": 0,
                "promoted_lead_ids": [],
                "failed_lead_ids": [],
                "candidate_lead_ids": candidate_ids,
                "candidate_lead_count": len(candidate_ids),
            }

        promoted_ids: list[int] = []
        failed_ids: list[int] = []
        for lead_id in candidate_ids:
            lead = Lead.query.filter_by(id=lead_id).first()
            if lead is None or lead.lead_status != "skip_trace":
                continue
            try:
                result = self.move_to_skip_trace(lead_id, actor=actor)
            except Exception as exc:
                db.session.rollback()
                logger.warning(
                    "promote skip-trace due leak failed lead_id=%s: %s",
                    lead_id,
                    exc,
                )
                failed_ids.append(lead_id)
                continue
            if result.get("lead_status") == "skip_trace":
                promoted_ids.append(lead_id)

        return {
            "promoted_lead_count": len(promoted_ids),
            "promoted_lead_ids": promoted_ids,
            "failed_lead_ids": failed_ids,
            "candidate_lead_ids": candidate_ids,
            "candidate_lead_count": len(candidate_ids),
        }

    def _sync_status_for_future_recent_sale_holds(
        self,
        *,
        actor: str,
        now: datetime,
        today: date,
        limit: int | None,
    ) -> tuple[set[int], list[str]]:
        """Align lead_status to skip_trace and clear obsolete outreach on hold.

        Returns ``(scoring_lead_ids, hubspot_completion_ids)``.
        """
        hard_terminal = {
            "deprioritize",
            "deal_won",
            "deal_lost",
            "suppressed",
            "do_not_contact",
        }
        query = (
            LeadTask.query
            .filter(
                LeadTask.task_type == "skip_trace_owner",
                LeadTask.status == "open",
                LeadTask.due_date.isnot(None),
                LeadTask.due_date > today,
                LeadTask.workflow_key == "recent_sale_hold",
            )
            .order_by(LeadTask.due_date.asc(), LeadTask.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)

        from app.services.mail_task_lifecycle_service import (
            complete_obsolete_outreach_during_recent_sale_hold,
        )

        scoring_lead_ids: set[int] = set()
        hubspot_completion_ids: list[str] = []
        for task in query.all():
            lead = Lead.query.filter_by(id=task.lead_id).with_for_update().first()
            if lead is None or lead.lead_status in hard_terminal:
                continue

            status_changed = False
            needs_cleared = False
            if lead.lead_status != "skip_trace":
                old_status = lead.lead_status
                lead.lead_status = "skip_trace"
                # Hold period: skip work is not yet needed (flag stays False).
                lead.needs_skip_trace = False
                db.session.add(lead)
                db.session.add(LeadTimelineEntry(
                    lead_id=lead.id,
                    event_type="status_changed",
                    occurred_at=now,
                    source="system",
                    actor=actor,
                    summary=(
                        f"Status changed from '{old_status}' to 'skip_trace' "
                        "to match an open recent-sale hold task."
                    ),
                    event_metadata={
                        "previous_status": old_status,
                        "new_status": "skip_trace",
                        "reason": "recent_sale_hold_status_sync",
                        "task_id": task.id,
                    },
                ))
                status_changed = True
                # Clear leftover dated custom/follow-ups so hold status cannot
                # re-enter Today's Action via stale May chores.
                _, cleared_hs = clear_dated_due_chores_entering_skip_trace(
                    lead.id,
                    actor=actor,
                    reason='recent_sale_hold_status_sync',
                    today=today,
                    now=now,
                )
                hubspot_completion_ids.extend(cleared_hs)
            elif lead.needs_skip_trace:
                lead.needs_skip_trace = False
                db.session.add(lead)
                needs_cleared = True

            completed_ids, obsolete_hs = (
                complete_obsolete_outreach_during_recent_sale_hold(
                    lead.id,
                    actor=actor,
                    commit=False,
                )
            )
            hubspot_completion_ids.extend(obsolete_hs)
            if status_changed or completed_ids or needs_cleared:
                scoring_lead_ids.add(lead.id)
        return scoring_lead_ids, hubspot_completion_ids

    def _heal_dated_post_hold_skip_trace_tasks(
        self,
        *,
        actor: str,
        now: datetime,
        today: date,
        limit: int | None,
        exclude_task_ids: set[int],
        hubspot_handoff_clear_ids: set[str] | None = None,
    ) -> dict:
        """Convert stuck dated post-hold verify tasks into undated handoffs."""
        query = (
            LeadTask.query
            .filter(
                LeadTask.task_type == "skip_trace_owner",
                LeadTask.status == "open",
                LeadTask.due_date.isnot(None),
                LeadTask.due_date <= today,
                LeadTask.workflow_key.is_(None),
            )
            .order_by(LeadTask.due_date.asc(), LeadTask.id.asc())
        )
        if exclude_task_ids:
            query = query.filter(~LeadTask.id.in_(exclude_task_ids))
        if limit is not None:
            query = query.limit(limit)

        healed_task_ids: list[int] = []
        activated_lead_ids: list[int] = []
        scoring_lead_ids: set[int] = set()
        for task in query.all():
            if self._is_undated_skip_trace_handoff(task):
                continue
            if not self._is_recent_sale_verify_title(task.title):
                continue
            lead = Lead.query.filter_by(id=task.lead_id).with_for_update().first()
            if lead is None or lead.lead_status in {
                "deprioritize",
                "deal_won",
                "deal_lost",
                "suppressed",
                "do_not_contact",
            }:
                continue
            if lead.lead_status != "skip_trace" or not lead.needs_skip_trace:
                old_status = lead.lead_status
                status_changed = lead.lead_status != "skip_trace"
                lead.lead_status = "skip_trace"
                lead.needs_skip_trace = True
                db.session.add(lead)
                if status_changed:
                    db.session.add(LeadTimelineEntry(
                        lead_id=lead.id,
                        event_type="status_changed",
                        occurred_at=now,
                        source="system",
                        actor=actor,
                        summary=(
                            f"Status changed from '{old_status}' to 'skip_trace' "
                            "when healing a matured recent-sale skip-trace task."
                        ),
                        event_metadata={
                            "previous_status": old_status,
                            "new_status": "skip_trace",
                            "reason": "recent_sale_hold_heal",
                            "task_id": task.id,
                        },
                    ))
                activated_lead_ids.append(lead.id)
            else:
                lead.needs_skip_trace = True
                db.session.add(lead)
            self._convert_to_awaiting_handoff(task, hubspot_handoff_clear_ids)
            healed_task_ids.append(task.id)
            scoring_lead_ids.add(lead.id)

        return {
            "healed_task_ids": healed_task_ids,
            "activated_lead_ids": activated_lead_ids,
            "scoring_lead_ids": scoring_lead_ids,
        }

    def _heal_post_hold_stale_contact_leads(
        self,
        *,
        actor: str,
        now: datetime,
        limit: int | None,
        exclude_lead_ids: set[int],
        hubspot_handoff_clear_ids: set[str] | None = None,
        hubspot_completion_ids: set[str] | None = None,
    ) -> dict:
        """Move past-hold prior-owner leads into skip-trace handoff.

        Covers mailing-status (and similar) leads that never had a
        ``recent_sale_hold`` task — scoring already says confirm ownership via
        ``contacts_need_post_hold_verification``, but stage/tasks were left unchanged.
        """
        from app.services import scoring_rubric as rubric

        terminal = {
            "deprioritize",
            "deal_won",
            "deal_lost",
            "suppressed",
            "do_not_contact",
        }
        # Oversample then filter in Python (sale dates are mixed string/date).
        fetch_limit = 500 if limit is None else max(limit * 8, limit)
        query = (
            Lead.query
            .filter(
                ~Lead.lead_status.in_(terminal),
                or_(
                    and_(
                        Lead.most_recent_sale.isnot(None),
                        Lead.most_recent_sale != "",
                    ),
                    Lead.acquisition_date.isnot(None),
                ),
                or_(
                    Lead.lead_status != "skip_trace",
                    Lead.needs_skip_trace.is_(False),
                ),
            )
            .order_by(Lead.id.desc())
        )
        if exclude_lead_ids:
            query = query.filter(~Lead.id.in_(exclude_lead_ids))
        candidates = query.limit(fetch_limit).all()

        activated_lead_ids: list[int] = []
        scoring_lead_ids: set[int] = set()
        for lead in candidates:
            if limit is not None and len(activated_lead_ids) >= limit:
                break
            if not rubric.contacts_need_post_hold_verification(lead):
                continue
            if (
                lead.lead_status == "skip_trace"
                and lead.needs_skip_trace
                and self._find_undated_skip_trace_handoff(lead.id) is not None
            ):
                continue

            locked = Lead.query.filter_by(id=lead.id).with_for_update().first()
            if locked is None or locked.lead_status in terminal:
                continue
            if not rubric.contacts_need_post_hold_verification(locked):
                continue
            if (
                locked.lead_status == "skip_trace"
                and locked.needs_skip_trace
                and self._find_undated_skip_trace_handoff(locked.id) is not None
            ):
                continue

            old_status = locked.lead_status
            if (
                locked.lead_status != "skip_trace"
                or not locked.needs_skip_trace
            ):
                status_changed = locked.lead_status != "skip_trace"
                locked.lead_status = "skip_trace"
                locked.needs_skip_trace = True
                db.session.add(locked)
                if status_changed:
                    db.session.add(LeadTimelineEntry(
                        lead_id=locked.id,
                        event_type="status_changed",
                        occurred_at=now,
                        source="system",
                        actor=actor,
                        summary=(
                            f"Status changed from '{old_status}' to "
                            "'skip_trace' when post-hold prior-owner "
                            "contacts needed skip-trace confirmation."
                        ),
                        event_metadata={
                            "previous_status": old_status,
                            "new_status": "skip_trace",
                            "reason": "post_hold_stale_contacts_heal",
                        },
                    ))
            else:
                locked.needs_skip_trace = True
                db.session.add(locked)

            self._ensure_awaiting_skip_trace_handoff(
                locked.id,
                actor=actor,
                hubspot_handoff_clear_ids=hubspot_handoff_clear_ids,
                hubspot_completion_ids=hubspot_completion_ids,
            )
            activated_lead_ids.append(locked.id)
            scoring_lead_ids.add(locked.id)

        return {
            "activated_lead_ids": activated_lead_ids,
            "scoring_lead_ids": scoring_lead_ids,
        }

    def _ensure_awaiting_skip_trace_handoff(
        self,
        lead_id: int,
        *,
        actor: str,
        hubspot_handoff_clear_ids: set[str] | None = None,
        hubspot_completion_ids: set[str] | None = None,
    ) -> LeadTask:
        """Create or normalize an undated Awaiting skip trace handoff task."""
        handoff = self._find_undated_skip_trace_handoff(lead_id)
        if handoff is None:
            open_skip = (
                LeadTask.query
                .filter_by(
                    lead_id=lead_id,
                    task_type="skip_trace_owner",
                    status="open",
                )
                .order_by(LeadTask.due_date.asc().nullslast(), LeadTask.id.asc())
                .first()
            )
            if open_skip is not None:
                self._convert_to_awaiting_handoff(open_skip, hubspot_handoff_clear_ids)
                handoff = open_skip
            else:
                handoff = self._tasks.create(
                    lead_id,
                    {
                        "task_type": "skip_trace_owner",
                        "title": "Awaiting skip trace",
                        "due_date": None,
                    },
                    actor=actor,
                    recompute_action=False,
                    commit=False,
                )
                handoff.workflow_key = "awaiting_skip_trace_handoff"
                db.session.add(handoff)
        extra_hs = self._retire_extra_open_skip_trace_owners(
            lead_id,
            keep_id=handoff.id,
            actor=actor,
        )
        if hubspot_completion_ids is not None:
            hubspot_completion_ids.update(extra_hs)
        return handoff

    def ensure_awaiting_skip_trace_handoff(
        self,
        lead_id: int,
        *,
        actor: str,
        commit: bool = False,
    ) -> tuple[LeadTask, set[str], set[str]]:
        """Guarantee an undated handoff when active skip work is needed.

        Shared by ``move_to_skip_trace`` and the Command Center status selector.
        Rules:
        - Reuse an existing undated handoff when present.
        - Never convert or retire a **future** ``recent_sale_hold`` (mid-hold).
        - Else convert a leftover open dated ``skip_trace_owner`` (including a
          matured hold) into the handoff, else create a fresh placeholder.
        - Complete other open ``skip_trace_owner`` rows except future holds.

        Returns ``(handoff_or_hold_task, hubspot_handoff_clear_ids, hubspot_completion_ids)``.
        """
        today = date.today()
        future_hold = self._find_open_future_recent_sale_hold(lead_id, today=today)

        # Mid-hold always wins: keep the dated hold, retire competing handoffs,
        # never create a second undated placeholder.
        if future_hold is not None:
            completion_ids = self._retire_extra_open_skip_trace_owners(
                lead_id,
                keep_id=future_hold.id,
                actor=actor,
                today=today,
            )
            if commit:
                db.session.commit()
            return future_hold, set(), completion_ids

        skip_trace_task = self._find_undated_skip_trace_handoff(lead_id)

        if skip_trace_task is None:
            candidates = (
                LeadTask.query
                .filter_by(
                    lead_id=lead_id,
                    task_type="skip_trace_owner",
                    status="open",
                )
                .order_by(
                    LeadTask.due_date.asc().nullslast(),
                    LeadTask.id.asc(),
                )
                .all()
            )
            for task in candidates:
                if self._is_future_recent_sale_hold(task, today=today):
                    continue
                skip_trace_task = task
                break

        handoff_clear_ids: set[str] = set()
        if skip_trace_task is not None and not self._is_undated_skip_trace_handoff(
            skip_trace_task,
        ):
            self._convert_to_awaiting_handoff(skip_trace_task, handoff_clear_ids)
        elif skip_trace_task is None:
            skip_trace_task = self._tasks.create(
                lead_id,
                {
                    "task_type": "skip_trace_owner",
                    "title": "Awaiting skip trace",
                    "due_date": None,
                },
                actor=actor,
                recompute_action=False,
                commit=False,
            )
            skip_trace_task.workflow_key = "awaiting_skip_trace_handoff"
            db.session.add(skip_trace_task)

        completion_ids = self._retire_extra_open_skip_trace_owners(
            lead_id,
            keep_id=skip_trace_task.id,
            actor=actor,
            today=today,
        )

        if commit:
            db.session.commit()
        return skip_trace_task, handoff_clear_ids, completion_ids

    def _retire_extra_open_skip_trace_owners(
        self,
        lead_id: int,
        *,
        keep_id: int,
        actor: str,
        today: date | None = None,
    ) -> set[str]:
        """Complete other open skip_trace_owner tasks so only *keep_id* remains.

        Future-dated ``recent_sale_hold`` tasks are preserved.
        """
        today = today or date.today()
        now = datetime.now(timezone.utc)
        pending_hubspot_ids: set[str] = set()
        extras = (
            LeadTask.query
            .filter(
                LeadTask.lead_id == lead_id,
                LeadTask.task_type == "skip_trace_owner",
                LeadTask.status == "open",
                LeadTask.id != keep_id,
            )
            .all()
        )
        for task in extras:
            if self._is_future_recent_sale_hold(task, today=today):
                continue
            completed_via_hubspot = False
            if task.hubspot_task_id:
                from app.services.hubspot_task_completion_service import (
                    mark_hubspot_task_completed_local,
                )

                local_completion = mark_hubspot_task_completed_local(
                    lead_id,
                    task.id,
                    actor=actor,
                    reason="dedupe_skip_trace_handoff",
                )
                if local_completion is not None:
                    completed_via_hubspot = True
                    if local_completion.hubspot_task_id:
                        pending_hubspot_ids.add(str(local_completion.hubspot_task_id))
            if not completed_via_hubspot:
                self._complete_task_and_log(
                    task,
                    now,
                    actor,
                    reason="dedupe_skip_trace_handoff",
                )
                if task.hubspot_task_id:
                    pending_hubspot_ids.add(str(task.hubspot_task_id))
        return pending_hubspot_ids

    @staticmethod
    def _convert_to_awaiting_handoff(
        task: LeadTask,
        hubspot_handoff_clear_ids: set[str] | None = None,
    ) -> None:
        """Normalize a skip-trace task into the undated pipeline placeholder."""
        task.title = "Awaiting skip trace"
        task.due_date = None
        task.workflow_key = "awaiting_skip_trace_handoff"
        db.session.add(task)
        from app.services.hubspot_task_completion_service import (
            mirror_crm_task_from_lead_task,
        )
        mirror_crm_task_from_lead_task(task, hubspot_handoff_clear_ids)
        if hubspot_handoff_clear_ids is not None and task.hubspot_task_id:
            hubspot_handoff_clear_ids.add(str(task.hubspot_task_id))

    @staticmethod
    def _is_recent_sale_verify_title(title: str | None) -> bool:
        normalized = (title or "").strip().lower()
        return normalized.startswith("recent-sale hold ended")

    @staticmethod
    def _is_future_recent_sale_hold(
        task: LeadTask,
        *,
        today: date | None = None,
    ) -> bool:
        today = today or date.today()
        return (
            task.workflow_key == "recent_sale_hold"
            and task.due_date is not None
            and task.due_date > today
        )

    @classmethod
    def _find_open_future_recent_sale_hold(
        cls,
        lead_id: int,
        *,
        today: date | None = None,
    ) -> Optional[LeadTask]:
        today = today or date.today()
        tasks = (
            LeadTask.query
            .filter_by(
                lead_id=lead_id,
                task_type="skip_trace_owner",
                status="open",
                workflow_key="recent_sale_hold",
            )
            .order_by(LeadTask.due_date.asc(), LeadTask.id.asc())
            .all()
        )
        for task in tasks:
            if cls._is_future_recent_sale_hold(task, today=today):
                return task
        return None

    @staticmethod
    def _find_undated_skip_trace_handoff(lead_id: int) -> Optional[LeadTask]:
        """Return the open undated skip-trace placeholder when one exists."""
        tasks = (
            LeadTask.query
            .filter_by(
                lead_id=lead_id,
                task_type="skip_trace_owner",
                status="open",
            )
            .all()
        )
        for task in tasks:
            if SkipTraceEnqueue._is_undated_skip_trace_handoff(task):
                return task
        return None

    @staticmethod
    def _is_undated_skip_trace_handoff(task: LeadTask) -> bool:
        """True for the undated pipeline placeholder — not current due work."""
        if task.task_type != "skip_trace_owner":
            return False
        if task.due_date is not None:
            return False
        if task.workflow_key == "awaiting_skip_trace_handoff":
            return True
        return (task.title or "").strip().lower() == "awaiting skip trace"

    @staticmethod
    def _complete_task_and_log(
        task: LeadTask,
        completed_at: datetime,
        actor: str,
        *,
        reason: str = 'moved_to_skip_trace',
    ) -> None:
        """Complete native/mirrored work and preserve task side effects."""
        task.status = 'completed'
        task.completed_at = completed_at
        complete_native_task_mirror(task, completed_at)
        db.session.add(LeadTimelineEntry(
            lead_id=task.lead_id,
            event_type='task_completed',
            occurred_at=completed_at,
            source='manual',
            actor=actor,
            summary=f'Task completed: {task.title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'title': task.title,
                'reason': reason,
            },
        ))

    @staticmethod
    def _serialize_lead_enqueue(lead_id: int) -> None:
        bind = db.session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"skip_trace_enqueue:{lead_id}"},
        )
