"""Tests for free Illinois SOS bulk parser and provider."""
from __future__ import annotations

from datetime import datetime

import pytest

from app import db
from app.models.il_sos_llc import IlSosLlcAgent, IlSosLlcEntity, IlSosLlcManager
from app.services.entity_lookup import EntityLookupProviderNotConfiguredError
from app.services.entity_lookup.ilsos_bulk import IllinoisSosBulkProvider
from app.services.entity_lookup.opencorporates import IllinoisOpenCorporatesProvider
from app.services.entity_lookup.ilsos_parser import (
    MANAGER_SCHEMA,
    NAME_SCHEMA,
    normalize_llc_name,
    parse_fixed_width_line,
    parse_records,
)
from app.services.entity_lookup.factory import get_entity_lookup_provider


def test_normalize_llc_name_variants():
    assert normalize_llc_name("Sunrise Properties, LLC") == normalize_llc_name(
        "SUNRISE PROPERTIES LLC"
    )
    assert "LLC" in normalize_llc_name("Foo L.L.C.")


def test_parse_name_and_manager_lines():
    # file_number(8) + name(120)
    name_line = "01234567" + "SUNRISE PROPERTIES LLC".ljust(120)
    name_rec = parse_fixed_width_line(name_line, NAME_SCHEMA)
    assert name_rec["file_number"] == "01234567"
    assert name_rec["name"] == "SUNRISE PROPERTIES LLC"

    # manager schema total width 163
    mgr_line = (
        "01234567"
        + "JOHN MANAGER".ljust(60)
        + "123 MAIN ST".ljust(45)
        + "CHICAGO".ljust(30)
        + "IL"
        + "606010000"
        + "20240101"
        + "M"
    )
    mgr_rec = parse_fixed_width_line(mgr_line, MANAGER_SCHEMA)
    assert mgr_rec["mm_name"] == "JOHN MANAGER"
    assert mgr_rec["mm_city"] == "CHICAGO"
    assert mgr_rec["mm_type_code"] == "M"


def test_parse_records_skips_header_trailer():
    body = "\n".join([
        "RUN DATE = 20240101 FILE: LLCALLNAM",
        "01234567" + "ACME LLC".ljust(120),
        "END OF FILE RECORD COUNT=0000001",
    ])
    recs = parse_records(body, NAME_SCHEMA)
    assert len(recs) == 1
    assert recs[0]["name"] == "ACME LLC"


def test_parse_records_skips_malformed_file_numbers():
    body = "\n".join([
        "NOTANUM!" + "THIS IS NOT DATA".ljust(120),
        "01234567" + "ACME LLC".ljust(120),
    ])
    recs = parse_records(body, NAME_SCHEMA)
    assert len(recs) == 1
    assert recs[0]["file_number"] == "01234567"


def test_factory_defaults_to_ilsos_bulk(monkeypatch):
    monkeypatch.delenv("ENTITY_LOOKUP_PROVIDER", raising=False)
    provider = get_entity_lookup_provider()
    assert provider.name == "ilsos_bulk"


class TestIllinoisSosBulkProvider:
    def test_empty_db_not_configured(self, app):
        with app.app_context():
            provider = IllinoisSosBulkProvider()
            assert provider.is_configured() is False
            with pytest.raises(EntityLookupProviderNotConfiguredError, match="Illinois LLC list is not loaded yet"):
                provider.lookup_llc("ANY LLC")

    def test_lookup_returns_managers_and_agent(self, app):
        with app.app_context():
            now = datetime.utcnow()
            db.session.add(IlSosLlcEntity(
                file_number="11223344",
                name="SUNRISE PROPERTIES LLC",
                normalized_name=normalize_llc_name("SUNRISE PROPERTIES LLC"),
                status_code="00",
                management_type="M",
                juris_organized="IL",
                imported_at=now,
            ))
            db.session.add(IlSosLlcManager(
                file_number="11223344",
                mm_name="Jane Owner",
                mm_street="1 Oak Ave",
                mm_city="Chicago",
                mm_juris="IL",
                mm_zip="60601",
                mm_type_code="M",
                is_company=False,
            ))
            db.session.add(IlSosLlcAgent(
                file_number="11223344",
                agent_name="CSC AGENT LLC",
                agent_street="2 Agent St",
                agent_city="Springfield",
                agent_zip="62701",
            ))
            db.session.commit()

            result = IllinoisSosBulkProvider().lookup_llc("Sunrise Properties, LLC")
            assert result.found is True
            assert result.file_number == "11223344"
            assert result.registered_agent_name == "CSC AGENT LLC"
            assert any(
                p.party_type == "manager" and p.full_name == "Jane Owner" and not p.is_company
                for p in result.parties
            )
            assert any(p.party_type == "registered_agent" for p in result.parties)

    def test_no_match(self, app):
        with app.app_context():
            db.session.add(IlSosLlcEntity(
                file_number="99999999",
                name="OTHER LLC",
                normalized_name=normalize_llc_name("OTHER LLC"),
                imported_at=datetime.utcnow(),
            ))
            db.session.commit()
            result = IllinoisSosBulkProvider().lookup_llc("MISSING ENTITY LLC")
            assert result.found is False
            assert "No matching" in (result.error or "")

    def test_ambiguous_normalized_name_refuses_guess(self, app):
        with app.app_context():
            now = datetime.utcnow()
            for fn, status in (("11111111", "00"), ("22222222", "00")):
                db.session.add(IlSosLlcEntity(
                    file_number=fn,
                    name="TWIN NAME LLC",
                    normalized_name=normalize_llc_name("TWIN NAME LLC"),
                    status_code=status,
                    imported_at=now,
                ))
            db.session.commit()
            result = IllinoisSosBulkProvider().lookup_llc("Twin Name, LLC")
            assert result.found is False
            assert "Multiple Illinois LLC filings" in (result.error or "")

    def test_ambiguous_prefers_single_active(self, app):
        with app.app_context():
            now = datetime.utcnow()
            db.session.add(IlSosLlcEntity(
                file_number="33333333",
                name="ACTIVE PREFERRED LLC",
                normalized_name=normalize_llc_name("ACTIVE PREFERRED LLC"),
                status_code="01",
                imported_at=now,
            ))
            db.session.add(IlSosLlcEntity(
                file_number="44444444",
                name="ACTIVE PREFERRED LLC",
                normalized_name=normalize_llc_name("ACTIVE PREFERRED LLC"),
                status_code="00",
                imported_at=now,
            ))
            db.session.add(IlSosLlcManager(
                file_number="44444444",
                mm_name="Active Manager",
                mm_type_code="M",
                is_company=False,
            ))
            db.session.commit()
            result = IllinoisSosBulkProvider().lookup_llc("Active Preferred LLC")
            assert result.found is True
            assert result.file_number == "44444444"

    def test_lookup_adds_llc_suffix_for_bare_name(self, app):
        with app.app_context():
            now = datetime.utcnow()
            db.session.add(IlSosLlcEntity(
                file_number="55555555",
                name="BARE NAME LLC",
                normalized_name=normalize_llc_name("BARE NAME LLC"),
                status_code="00",
                imported_at=now,
            ))
            db.session.commit()
            result = IllinoisSosBulkProvider().lookup_llc("Bare Name")
            assert result.found is True
            assert result.file_number == "55555555"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self._responses.pop(0))


def test_opencorporates_requires_exact_search_match():
    session = _FakeSession([
        {
            "results": {
                "companies": [
                    {
                        "company": {
                            "name": "DIFFERENT LLC",
                            "jurisdiction_code": "us_il",
                            "company_number": "999",
                        },
                    },
                ],
            },
        },
    ])
    provider = IllinoisOpenCorporatesProvider(api_token="token", session=session)
    result = provider.lookup_llc("Requested LLC")
    assert result.found is False
    assert len(session.calls) == 1


def test_opencorporates_inactive_status_is_not_active():
    session = _FakeSession([
        {
            "results": {
                "companies": [
                    {
                        "company": {
                            "name": "REQUESTED LLC",
                            "jurisdiction_code": "us_il",
                            "company_number": "123",
                        },
                    },
                ],
            },
        },
        {
            "results": {
                "company": {
                    "name": "REQUESTED LLC",
                    "jurisdiction_code": "us_il",
                    "company_number": "123",
                    "current_status": "inactive",
                    "officers": [],
                },
            },
        },
    ])
    provider = IllinoisOpenCorporatesProvider(api_token="token", session=session)
    result = provider.lookup_llc("Requested LLC")
    assert result.found is True
    assert result.status == "inactive"


class TestIlsosBulkImportIfStale:
    def test_skips_when_fresh_and_tables_have_rows(self, app, tmp_path):
        from datetime import timedelta

        from app.models.il_sos_llc import IlSosImportRun
        from app.services.entity_lookup.ilsos_import_service import (
            import_ilsos_bulk_if_stale,
        )

        with app.app_context():
            now = datetime.utcnow()
            db.session.add(IlSosLlcEntity(
                file_number="99887766",
                name="FRESH LLC",
                normalized_name=normalize_llc_name("FRESH LLC"),
                imported_at=now,
            ))
            db.session.add(IlSosImportRun(
                source="test",
                status="success",
                started_at=now - timedelta(days=1),
                finished_at=now - timedelta(hours=2),
                row_counts={"entities_loaded": 1},
            ))
            db.session.commit()

            called = {"n": 0}

            def _boom(*_a, **_k):
                called["n"] += 1
                raise AssertionError("should skip download")

            from app.services.entity_lookup import ilsos_import_service as svc
            orig = svc.IlSosBulkImportService.import_all
            svc.IlSosBulkImportService.import_all = _boom  # type: ignore[method-assign]
            try:
                result = import_ilsos_bulk_if_stale(tmp_path)
            finally:
                svc.IlSosBulkImportService.import_all = orig  # type: ignore[method-assign]

            assert result["skipped"] is True
            assert result["reason"] == "fresh"
            assert called["n"] == 0

    def test_runs_when_tables_empty(self, app, tmp_path):
        from app.services.entity_lookup.ilsos_import_service import (
            import_ilsos_bulk_if_stale,
        )

        with app.app_context():
            captured = {}

            def _fake_import(self, cache_dir, **kwargs):
                captured["cache_dir"] = cache_dir
                return {"dry_run": False, "row_counts": {"entities_loaded": 3}}

            from app.services.entity_lookup import ilsos_import_service as svc
            orig = svc.IlSosBulkImportService.import_all
            svc.IlSosBulkImportService.import_all = _fake_import  # type: ignore[method-assign]
            try:
                result = import_ilsos_bulk_if_stale(tmp_path)
            finally:
                svc.IlSosBulkImportService.import_all = orig  # type: ignore[method-assign]

            assert result["skipped"] is False
            assert result["row_counts"]["entities_loaded"] == 3
            assert captured["cache_dir"] == tmp_path


def test_slim_master_keeps_only_join_fields():
    from app.services.entity_lookup.ilsos_import_service import _slim_master_by_file_number

    slim = _slim_master_by_file_number([
        {
            "file_number": "11223344",
            "status_code": "00",
            "management_type": "M",
            "juris_organized": "IL",
            "purpose_code": "DROPME",
        },
        {"file_number": "", "status_code": "00"},
    ])
    assert slim == {
        "11223344": {
            "status_code": "00",
            "management_type": "M",
            "juris_organized": "IL",
        },
    }


def test_latest_agent_keeps_newest_change_date():
    from app.services.entity_lookup.ilsos_import_service import _latest_agent_by_file_number

    latest = _latest_agent_by_file_number([
        {
            "file_number": "11223344",
            "agent_name": "OLD AGENT",
            "agent_change_date": "20240101",
        },
        {
            "file_number": "11223344",
            "agent_name": "NEW AGENT",
            "agent_change_date": "20240601",
        },
        {
            "file_number": "55667788",
            "agent_name": "LATER INPUT AGENT",
        },
        {
            "file_number": "55667788",
            "agent_name": "LAST INPUT AGENT",
        },
    ])

    assert latest["11223344"]["agent_name"] == "NEW AGENT"
    assert latest["55667788"]["agent_name"] == "LAST INPUT AGENT"


def test_ilsos_weekly_beat_is_registered():
    from celery_worker import celery

    job = celery.conf.beat_schedule.get("ilsos-weekly-bulk-refresh")
    assert job is not None
    assert job["task"] == "ilsos.refresh_bulk"


def test_ilsos_refresh_task_soft_fails(monkeypatch):
    from celery_worker import ilsos_refresh_bulk_task

    class _App:
        def app_context(self):
            from contextlib import nullcontext
            return nullcontext()

    monkeypatch.setattr(
        "app.create_app",
        lambda: _App(),
    )

    def _raise(*_a, **_k):
        raise RuntimeError("download failed")

    monkeypatch.setattr(
        "app.services.entity_lookup.ilsos_import_service.import_ilsos_bulk_if_stale",
        _raise,
    )
    result = ilsos_refresh_bulk_task()
    assert result["ok"] is False
    assert "download failed" in result["error"]

