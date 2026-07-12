"""Tests for free Illinois SOS bulk parser and provider."""
from __future__ import annotations

from datetime import datetime

import pytest

from app import db
from app.models.il_sos_llc import IlSosLlcAgent, IlSosLlcEntity, IlSosLlcManager
from app.services.entity_lookup import EntityLookupProviderNotConfiguredError
from app.services.entity_lookup.ilsos_bulk import IllinoisSosBulkProvider
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


def test_factory_defaults_to_ilsos_bulk(monkeypatch):
    monkeypatch.delenv("ENTITY_LOOKUP_PROVIDER", raising=False)
    provider = get_entity_lookup_provider()
    assert provider.name == "ilsos_bulk"


class TestIllinoisSosBulkProvider:
    def test_empty_db_not_configured(self, app):
        with app.app_context():
            provider = IllinoisSosBulkProvider()
            assert provider.is_configured() is False
            with pytest.raises(EntityLookupProviderNotConfiguredError):
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
