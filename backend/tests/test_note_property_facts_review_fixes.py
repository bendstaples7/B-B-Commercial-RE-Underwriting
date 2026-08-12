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


def test_note_fact_scoring_refresh_callers_commit_after_success():
    backend_dir = Path(__file__).resolve().parent.parent
    callers = [
        (
            backend_dir / "app/services/hubspot_activity_converter_service.py",
            "refresh_lead_scoring after note facts failed",
            "db.session.commit()",
        ),
        (
            backend_dir / "app/controllers/command_center_controller.py",
            "refresh_lead_scoring after note facts heal failed",
            "_db.session.commit()",
        ),
    ]

    for path, warning_text, commit_call in callers:
        source = path.read_text(encoding="utf-8")
        window_start = source.index(warning_text) - 300
        window = source[window_start: source.index(warning_text) + len(warning_text)]

        refresh_at = window.index("refresh_lead_scoring(lead.id)")
        commit_at = window.index(commit_call)
        except_at = window.index("except Exception as score_exc")

        assert refresh_at < commit_at < except_at
