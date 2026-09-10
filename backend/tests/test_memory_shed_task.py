"""MemoryShedTask must short-circuit inside Task.__call__ (not task_prerun)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from celery.exceptions import Ignore, Reject


def _load_celery_worker_module():
    import celery_worker as cw

    return cw


def _bound_dummy(cw, *, name: str | None = None):
    task_name = name or next(iter(cw.MEMORY_SHED_TASK_NAMES))

    class Dummy(cw.MemoryShedTask):
        def run(self, *a, **k):
            return {"ran": True}

    Dummy.bind(cw.celery)
    Dummy.name = task_name
    return Dummy()


def test_memory_shed_task_is_default_base():
    cw = _load_celery_worker_module()
    assert hasattr(cw, "MemoryShedTask")
    assert cw.celery.Task is cw.MemoryShedTask or issubclass(
        cw.celery.Task, cw.MemoryShedTask
    )


def test_shed_raises_ignore_for_beat_header(monkeypatch):
    cw = _load_celery_worker_module()
    task = _bound_dummy(cw)
    task.push_request(headers={"bb_beat": "1"}, expires=None)
    monkeypatch.setattr(
        "app.services.helpers.host_memory.memory_shed_skip_payload",
        lambda: {"skipped": True, "detail": "low mem"},
    )
    monkeypatch.setattr(task, "update_state", lambda **k: None)

    with pytest.raises(Ignore):
        task._maybe_shed_under_memory_pressure()


def test_manual_shed_requeues_then_ignores(monkeypatch):
    cw = _load_celery_worker_module()
    task = _bound_dummy(cw)
    task.push_request(headers={}, expires=None)
    monkeypatch.setattr(
        "app.services.helpers.host_memory.memory_shed_skip_payload",
        lambda: {"skipped": True, "detail": "low mem"},
    )
    monkeypatch.setattr(task, "update_state", lambda **k: None)
    calls = []
    monkeypatch.setattr(
        task, "apply_async", lambda **k: calls.append(k) or SimpleNamespace(id="x")
    )

    with pytest.raises(Ignore):
        task._maybe_shed_under_memory_pressure()
    assert calls
    assert calls[0]["headers"]["bb_memory_shed_attempts"] == 1


def test_manual_shed_reject_when_requeue_fails(monkeypatch):
    cw = _load_celery_worker_module()
    task = _bound_dummy(cw)
    task.push_request(headers={}, expires=None)
    monkeypatch.setattr(
        "app.services.helpers.host_memory.memory_shed_skip_payload",
        lambda: {"skipped": True, "detail": "low mem"},
    )
    monkeypatch.setattr(task, "update_state", lambda **k: None)

    def boom(**k):
        raise RuntimeError("broker down")

    monkeypatch.setattr(task, "apply_async", boom)
    with pytest.raises(Reject):
        task._maybe_shed_under_memory_pressure()


def test_bb_beat_stamped_on_shed_beat_entries():
    cw = _load_celery_worker_module()
    stamped = False
    for entry in (cw.celery.conf.beat_schedule or {}).values():
        if entry.get("task") in cw.MEMORY_SHED_TASK_NAMES:
            headers = (entry.get("options") or {}).get("headers") or {}
            assert headers.get("bb_beat") == "1"
            stamped = True
    assert stamped, "expected at least one shed beat entry stamped with bb_beat"
