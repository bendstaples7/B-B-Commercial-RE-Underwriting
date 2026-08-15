"""Regression coverage for note-property review fixes."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_note_property_migration_pages_lead_ids(monkeypatch):
    from alembic_migrations.versions import note_pf_20260812_note_property_facts as migration

    pages = [
        [(1,), (2,)],
        [(5,)],
        [],
    ]

    class Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def fetchall(self):  # pragma: no cover - should fail before coverage matters
            raise AssertionError("migration backfill must not fetch all lead IDs")

    class FakeSession:
        def __init__(self):
            self.execute_params = []
            self.added = []
            self.commits = 0

        def execute(self, _statement, params):
            self.execute_params.append(params)
            return Result(pages.pop(0))

        def get(self, _model, lead_id):
            return SimpleNamespace(id=lead_id)

        def add(self, lead):
            self.added.append(lead)

        def commit(self):
            self.commits += 1

    fake_session = FakeSession()

    monkeypatch.setattr(migration, "_BACKFILL_CHUNK", 2)
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(execute=lambda _sql: None, get_bind=lambda: object()),
    )
    monkeypatch.setattr(migration, "Session", lambda bind: fake_session)

    from app.services.helpers import note_property_facts

    def fake_apply_note_facts(lead):
        return ["units"] if lead.id != 2 else []

    monkeypatch.setattr(
        note_property_facts,
        "apply_note_facts_from_timeline",
        fake_apply_note_facts,
    )

    migration.upgrade()

    assert fake_session.execute_params == [
        {"last_lead_id": 0, "limit": 2},
        {"last_lead_id": 2, "limit": 2},
        {"last_lead_id": 5, "limit": 2},
    ]
    assert [lead.id for lead in fake_session.added] == [1, 5]
    assert fake_session.commits == 2


def test_note_fact_score_refresh_includes_property_type_updates():
    backend_dir = Path(__file__).resolve().parent.parent
    callers = [
        (
            backend_dir / "app/services/hubspot_activity_converter_service.py",
            "refresh_lead_scoring(score_lead_id)",
        ),
        (
            backend_dir / "app/controllers/command_center_controller.py",
            "refresh_lead_scoring(lead.id)",
        ),
    ]

    for path, refresh_call in callers:
        source = path.read_text(encoding="utf-8")
        refresh_at = source.index(refresh_call)
        window_start = max(0, refresh_at - 900)
        window = source[window_start: refresh_at + 220]
        assert "property_type" in window
        assert "except Exception as score_exc" in window
        commit_marker = (
            "db.session.commit()"
            if path.name == "hubspot_activity_converter_service.py"
            else "_db.session.commit()"
        )
        commit_at = source.rfind(commit_marker, 0, refresh_at)
        assert commit_at != -1
        assert commit_at < refresh_at


def test_command_center_rebuilds_action_snapshot_after_note_fact_heal():
    backend_dir = Path(__file__).resolve().parent.parent
    source = (backend_dir / "app/controllers/command_center_controller.py").read_text(
        encoding="utf-8",
    )

    heal_at = source.index("apply_note_facts_from_timeline(lead)")
    recompute_at = source.index("_build_recommended_action_snapshot(lead)", heal_at)
    tasks_refresh_at = source.index("_lead_task_service.list_open(lead_id)", heal_at)
    timeline_refresh_at = source.index(
        "_lead_timeline_service.get_page(",
        heal_at,
    )
    payload_at = source.index("'recommended_action': {", recompute_at)

    assert heal_at < recompute_at < payload_at
    assert heal_at < tasks_refresh_at < payload_at
    assert heal_at < timeline_refresh_at < payload_at
