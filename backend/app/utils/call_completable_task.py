"""Match open tasks that may be completed when logging a call."""
from __future__ import annotations

import re
from typing import Any

CALL_TITLE_RE = re.compile(r'\b(call|phone|voicemail)\b', re.IGNORECASE)
FOLLOW_UP_TITLE_RE = re.compile(r'\bfollow[\s-]?up\b', re.IGNORECASE)
MAIL_OR_EMAIL_TITLE_RE = re.compile(r'\b(email|e-mail|mail|letter)\b', re.IGNORECASE)

NON_CALL_TASK_TYPES = frozenset({
    'research_missing_pin',
    'match_hubspot_deal',
    'run_property_analysis',
    'add_to_mail_batch',
    'skip_trace_owner',
})


def is_mail_or_email_outreach_task(task_type: str | None, title: str | None) -> bool:
    ttype = (task_type or 'custom').strip()
    text = title or ''
    if ttype == 'add_to_mail_batch':
        return True
    return bool(MAIL_OR_EMAIL_TITLE_RE.search(text))


def is_call_completable_task(task_type: str | None, title: str | None) -> bool:
    """Return True if logging a call may complete this task."""
    ttype = (task_type or 'custom').strip()
    text = title or ''

    if ttype == 'call_owner_today':
        return True

    if ttype in NON_CALL_TASK_TYPES:
        return False

    if is_mail_or_email_outreach_task(task_type, title):
        return False

    return bool(CALL_TITLE_RE.search(text) or FOLLOW_UP_TITLE_RE.search(text))


def _task_fields(task: Any) -> tuple[str | None, str | None, str | None, str | None]:
    if isinstance(task, dict):
        return (
            task.get('status'),
            task.get('task_type'),
            task.get('title'),
            task.get('source'),
        )
    return (
        getattr(task, 'status', None),
        getattr(task, 'task_type', None),
        getattr(task, 'title', None),
        getattr(task, 'source', None),
    )


def find_call_completable_task(tasks: list[Any]) -> Any | None:
    """Return the best open task to complete when logging a call (native or HubSpot)."""
    open_tasks: list[Any] = []
    for task in tasks:
        status, task_type, title, _source = _task_fields(task)
        if status not in (None, 'open', 'overdue'):
            continue
        open_tasks.append(task)
        if is_call_completable_task(task_type, title):
            return task

    # One open task that isn't mail/email outreach — treat as the call task.
    if len(open_tasks) == 1:
        _, task_type, title, _ = _task_fields(open_tasks[0])
        if not is_mail_or_email_outreach_task(task_type, title):
            return open_tasks[0]

    return None
