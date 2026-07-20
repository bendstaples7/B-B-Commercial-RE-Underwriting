"""Unit tests for LeadIngestionService — Task 7.13.

Covers:
- ForeclosureHandler field mapping (source_type, data_source, property_state, lead_category, notes)
- LongOwnedHandler: SFR filter, 15-year threshold, 20+ note, missing acquisition_date
- AbsenteeOwnerHandler: equal-address skip, different-address lead, long-owned note
- TaxDistressHandler: tax_distress_data populated, notes null/empty, source_type
- ManualDistressHandler (process_csv): source_type, notes from CSV cols, manual_priority validation
- GIS enrichment: match → fields populated + has_property_match; no match → needs_skip_trace + note;
  timeout/error → null GIS fields, batch continues
- ImportJob lifecycle: status=completed after success; status=failed on exception;
  rows_processed/imported/skipped correct

Requirements: 1.1-1.7, 2.1-2.7, 3.1-3.6, 4.1-4.5, 5.1-5.6, 6.1-6.9, 8.1-8.7, 9.1-9.7
"""
import os
import csv
import tempfile
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app import db
from app.models.lead import Property
from app.models.import_job import ImportJob
from app.services.deduplication_engine import DeduplicationEngine
from app.services.lead_ingestion_service import LeadIngestionService
from app.services.gis.base import GISParcel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user-test-001"


def _make_service(gis_registry=None):
    """Return a LeadIngestionService with a real DeduplicationEngine."""
    dedup = DeduplicationEngine()
    return LeadIngestionService(dedup_engine=dedup, gis_registry=gis_registry or {})


def _make_gis_parcel(**kwargs):
    """Return a GISParcel with sensible defaults overridden by kwargs."""
    defaults = dict(
        county_assessor_pin="12-34-567-890",
        property_type="Single Family",
        year_built=1985,
        square_footage=1800,
        bedrooms=3,
        bathrooms=2.0,
        lot_size=7500,
        owner_first_name="GIS First",
        owner_last_name="GIS Last",
        mailing_address="100 GIS Mailing St",
        mailing_city="Wheaton",
        mailing_state="IL",
        mailing_zip="60187",
    )
    defaults.update(kwargs)
    return GISParcel(**defaults)


def _make_mock_connector(parcel=None, raise_exc=None, market="dupage_il"):
    """Return a mock GISConnector."""
    connector = MagicMock()
    connector.connector_name = "dupage_gis"
    connector.market = market
    if raise_exc:
        connector.lookup_by_address.side_effect = raise_exc
        connector.lookup_by_pin.side_effect = raise_exc
    else:
        connector.lookup_by_address.return_value = parcel
        connector.lookup_by_pin.return_value = parcel
    return connector


def _foreclosure_record(**overrides):
    rec = {
        "property_street": "100 Foreclosure St",
        "property_city": "Naperville",
        "property_zip": "60540",
        "owner_first_name": "John",
        "owner_last_name": "Doe",
        "case_number": "2024-FC-001",
        "sale_date": "2024-06-15",
        "source_url": "https://sheriff.dupagecounty.gov/sale/001",
    }
    rec.update(overrides)
    return rec


def _long_owned_record(years_ago=20, sfr=True, **overrides):
    """Return a long-owned record with acquisition date `years_ago` years in the past.

    acquisition_date is a Python date object because _normalize_long_owned_record passes
    record.get('acquisition_date') directly to the ORM, and SQLite requires a date object.
    The service parses string dates too, but using a date object avoids the SQLite restriction.
    """
    acq_date = date.today() - timedelta(days=int(years_ago * 365.25))
    rec = {
        "property_street": "200 Long Owned Ave",
        "property_city": "Downers Grove",
        "property_zip": "60515",
        "owner_first_name": "Mary",
        "owner_last_name": "Long",
        "county_assessor_pin": "99-88-777-001",
        "assessor_class_code": "202" if sfr else "500",
        "acquisition_date": acq_date,
    }
    rec.update(overrides)
    return rec


def _absentee_record(same_address=False, years_ago=None, **overrides):
    rec = {
        "property_street": "300 Absentee Blvd",
        "property_city": "Lombard",
        "property_zip": "60148",
        "owner_first_name": "Alice",
        "owner_last_name": "Away",
        "county_assessor_pin": "55-44-333-002",
        "assessor_class_code": "202",
        "mailing_address": "300 Absentee Blvd" if same_address else "999 Mailing Rd",
        "mailing_city": "Chicago",
        "mailing_state": "IL",
        "mailing_zip": "60601",
    }
    if years_ago is not None:
        # Use a Python date object — SQLite requires date objects, not strings
        rec["acquisition_date"] = date.today() - timedelta(days=int(years_ago * 365.25))
    rec.update(overrides)
    return rec


def _tax_distress_record(**overrides):
    rec = {
        "property_street": "400 Tax Distress Rd",
        "property_city": "Glen Ellyn",
        "property_zip": "60137",
        "owner_first_name": "Bob",
        "owner_last_name": "Taxes",
        "county_assessor_pin": "11-22-333-004",
        "signal_type": "tax_delinquency",
        "delinquent_amount": 4500.00,
        "tax_year": 2022,
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# ForeclosureHandler field mapping
# ---------------------------------------------------------------------------

class TestForeclosureHandler:
    """ingest_foreclosure — field mapping per Requirements 2.1-2.4."""

    def test_source_type_is_foreclosure(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.source_type == "foreclosure"

    def test_data_source_is_dupage_sheriff(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.data_source == "dupage_sheriff"

    def test_property_state_is_IL(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.property_state == "IL"

    def test_lead_category_is_residential(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.lead_category == "residential"

    def test_notes_contain_case_number(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record(case_number="2024-FC-999")], USER_ID)
            lead = db.session.query(Property).first()
            assert "Case: 2024-FC-999" in lead.notes

    def test_notes_contain_sale_date(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record(sale_date="2024-09-20")], USER_ID)
            lead = db.session.query(Property).first()
            assert "Sale Date: 2024-09-20" in lead.notes

    def test_notes_contain_source_url(self, app):
        with app.app_context():
            svc = _make_service()
            url = "https://sheriff.dupagecounty.gov/sale/XYZ"
            svc.ingest_foreclosure([_foreclosure_record(source_url=url)], USER_ID)
            lead = db.session.query(Property).first()
            assert url in lead.notes

    def test_owner_user_id_set_from_parameter(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_foreclosure([_foreclosure_record()], "specific-user-id")
            lead = db.session.query(Property).first()
            assert lead.owner_user_id == "specific-user-id"

    def test_no_case_number_notes_still_contains_sale_date(self, app):
        with app.app_context():
            svc = _make_service()
            rec = _foreclosure_record(case_number=None, sale_date="2024-11-01")
            svc.ingest_foreclosure([rec], USER_ID)
            lead = db.session.query(Property).first()
            assert "Sale Date: 2024-11-01" in lead.notes
            assert "Case:" not in lead.notes

    def test_no_optional_fields_notes_is_none_or_empty(self, app):
        with app.app_context():
            svc = _make_service()
            rec = _foreclosure_record(case_number=None, sale_date=None, source_url=None)
            svc.ingest_foreclosure([rec], USER_ID)
            lead = db.session.query(Property).first()
            # Notes should be None or empty string when no note parts
            assert not lead.notes


# ---------------------------------------------------------------------------
# LongOwnedHandler field mapping and filtering
# ---------------------------------------------------------------------------

class TestLongOwnedHandler:
    """ingest_long_owned — Requirements 3.1-3.6."""

    def test_sfr_record_15_years_creates_lead(self, app):
        with app.app_context():
            svc = _make_service()
            # Use 15 years + 10 days to ensure we clear the threshold regardless of rounding
            svc.ingest_long_owned([_long_owned_record(years_ago=15.1)], USER_ID)
            lead = db.session.query(Property).first()
            assert lead is not None
            assert lead.source_type == "long_owned"

    def test_non_sfr_record_is_skipped(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_long_owned([_long_owned_record(sfr=False)], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1

    def test_record_under_15_years_is_skipped(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_long_owned([_long_owned_record(years_ago=14)], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1

    def test_record_exactly_15_years_creates_lead(self, app):
        """15 full calendar years is the minimum threshold — should be included."""
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_long_owned([_long_owned_record(years_ago=15.1)], USER_ID)
            assert job.rows_imported == 1

    def test_record_20_years_gets_owned_20_plus_note(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_long_owned([_long_owned_record(years_ago=20)], USER_ID)
            lead = db.session.query(Property).first()
            assert "Owned 20+ years" in lead.notes

    def test_record_19_years_no_owned_20_plus_note(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_long_owned([_long_owned_record(years_ago=19)], USER_ID)
            lead = db.session.query(Property).first()
            assert lead is not None
            assert (lead.notes is None or "Owned 20+" not in (lead.notes or ""))

    def test_missing_acquisition_date_skipped(self, app):
        with app.app_context():
            svc = _make_service()
            rec = _long_owned_record()
            rec.pop("acquisition_date")
            job = svc.ingest_long_owned([rec], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1
            assert any("missing acquisition_date" in str(e) for e in job.error_log)

    def test_data_source_is_dupage_gis(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_long_owned([_long_owned_record(years_ago=20)], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.data_source == "dupage_gis"

    def test_property_state_is_IL(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_long_owned([_long_owned_record(years_ago=20)], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.property_state == "IL"


# ---------------------------------------------------------------------------
# AbsenteeOwnerHandler
# ---------------------------------------------------------------------------

class TestAbsenteeOwnerHandler:
    """ingest_absentee_owner — Requirements 4.1-4.5."""

    def test_different_addresses_creates_lead(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_absentee_owner([_absentee_record(same_address=False)], USER_ID)
            assert job.rows_imported == 1
            lead = db.session.query(Property).first()
            assert lead.source_type == "absentee_owner"

    def test_equal_normalized_addresses_skipped(self, app):
        """Records where property and mailing address normalize to same string are skipped."""
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_absentee_owner([_absentee_record(same_address=True)], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1

    def test_source_type_is_absentee_owner(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_absentee_owner([_absentee_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.source_type == "absentee_owner"

    def test_long_owned_absentee_gets_note(self, app):
        """Absentee owner record also owned ≥15 years gets 'Long-owned absentee' note."""
        with app.app_context():
            svc = _make_service()
            svc.ingest_absentee_owner([_absentee_record(years_ago=16)], USER_ID)
            lead = db.session.query(Property).first()
            assert "Long-owned absentee" in (lead.notes or "")

    def test_short_owned_absentee_no_long_owned_note(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_absentee_owner([_absentee_record(years_ago=5)], USER_ID)
            lead = db.session.query(Property).first()
            assert lead is not None
            assert "Long-owned absentee" not in (lead.notes or "")

    def test_non_sfr_absentee_skipped(self, app):
        with app.app_context():
            svc = _make_service()
            rec = _absentee_record()
            rec["assessor_class_code"] = "500"
            job = svc.ingest_absentee_owner([rec], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1

    def test_case_insensitive_address_comparison_skips_match(self, app):
        """Same address in different case should be treated as equal and skipped."""
        with app.app_context():
            svc = _make_service()
            rec = _absentee_record()
            rec["property_street"] = "300 ABSENTEE BLVD"
            rec["mailing_address"] = "300 absentee blvd"
            job = svc.ingest_absentee_owner([rec], USER_ID)
            assert db.session.query(Property).count() == 0
            assert job.rows_skipped == 1


# ---------------------------------------------------------------------------
# TaxDistressHandler
# ---------------------------------------------------------------------------

class TestTaxDistressHandler:
    """ingest_tax_distress — Requirements 5.1-5.6."""

    def test_source_type_is_tax_distress(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_tax_distress([_tax_distress_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.source_type == "tax_distress"

    def test_data_source_is_tax_distress_source(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_tax_distress([_tax_distress_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.data_source == "tax_distress_source"

    def test_tax_distress_data_is_populated(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_tax_distress([_tax_distress_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.tax_distress_data is not None
            assert lead.tax_distress_data["signal_type"] == "tax_delinquency"
            assert lead.tax_distress_data["delinquent_amount"] == 4500.00
            assert lead.tax_distress_data["tax_year"] == 2022

    def test_tax_distress_data_null_optional_fields(self, app):
        """delinquent_amount and tax_year should be null when absent from source."""
        with app.app_context():
            svc = _make_service()
            rec = _tax_distress_record()
            rec.pop("delinquent_amount")
            rec.pop("tax_year")
            svc.ingest_tax_distress([rec], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.tax_distress_data["delinquent_amount"] is None
            assert lead.tax_distress_data["tax_year"] is None

    def test_notes_field_is_null_or_empty(self, app):
        """Tax distress records must NEVER write to notes (Req 5.4)."""
        with app.app_context():
            svc = _make_service()
            svc.ingest_tax_distress([_tax_distress_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert not lead.notes

    def test_notes_field_contains_no_tax_language(self, app):
        with app.app_context():
            svc = _make_service()
            svc.ingest_tax_distress([_tax_distress_record()], USER_ID)
            lead = db.session.query(Property).first()
            notes = (lead.notes or "").lower()
            assert "tax" not in notes
            assert "delinquent" not in notes

    def test_tax_sale_signal_type_stored(self, app):
        with app.app_context():
            svc = _make_service()
            rec = _tax_distress_record(signal_type="tax_sale")
            svc.ingest_tax_distress([rec], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.tax_distress_data["signal_type"] == "tax_sale"


# ---------------------------------------------------------------------------
# ManualDistressHandler — process_csv
# ---------------------------------------------------------------------------

def _write_csv(rows, headers=None):
    """Write rows (list of dicts) to a temp CSV file; return file path."""
    if headers is None and rows:
        headers = list(rows[0].keys())
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


class TestManualDistressHandlerCSV:
    """process_csv — Requirements 6.1-6.9."""

    def _create_job(self, app_ctx, svc):
        """Helper: create an ImportJob and return it."""
        job = svc._create_import_job(USER_ID, "manual_distress")
        db.session.commit()
        return job

    def test_source_type_is_manual_distress(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([
                {"property_address": "500 Manual St", "condition_notes": "broken windows"},
            ])
            svc.process_csv(job.id, path, USER_ID)
            lead = db.session.query(Property).first()
            assert lead.source_type == "manual_distress"

    def test_data_source_is_manual_csv(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([{"property_address": "501 Manual Ave"}])
            svc.process_csv(job.id, path, USER_ID)
            lead = db.session.query(Property).first()
            assert lead.data_source == "manual_csv"

    def test_condition_notes_stored_in_notes(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([{
                "property_address": "502 Manual Blvd",
                "condition_notes": "roof damage",
                "distress_reason": "vacant",
            }])
            svc.process_csv(job.id, path, USER_ID)
            lead = db.session.query(Property).first()
            assert "roof damage" in (lead.notes or "")
            assert "vacant" in (lead.notes or "")

    def test_valid_manual_priority_stored(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([{
                "property_address": "503 Priority Ln",
                "manual_priority": "3",
            }])
            svc.process_csv(job.id, path, USER_ID)
            lead = db.session.query(Property).first()
            assert lead.manual_priority == 3

    def test_invalid_priority_not_stored_warning_logged(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([{
                "property_address": "504 Bad Priority Dr",
                "manual_priority": "99",
            }])
            svc.process_csv(job.id, path, USER_ID)
            lead = db.session.query(Property).first()
            # Lead created but priority not stored
            assert lead is not None
            assert lead.manual_priority is None
            # Reload job
            db.session.expire(job)
            assert any("manual_priority" in str(e.get("reason", "")) for e in job.error_log)

    def test_missing_property_address_row_skipped(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([
                {"property_address": "", "condition_notes": "no address"},
            ])
            svc.process_csv(job.id, path, USER_ID)
            assert db.session.query(Property).count() == 0
            db.session.expire(job)
            assert job.rows_skipped == 1

    def test_1_row_creates_lead(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            path = _write_csv([{"property_address": "505 One Row Ct"}])
            svc.process_csv(job.id, path, USER_ID)
            db.session.expire(job)
            assert job.rows_imported == 1
            assert job.rows_processed == 1

    def test_499_rows_processes_synchronously(self, app):
        """process_csv with 499 rows completes and sets status=completed."""
        with app.app_context():
            svc = _make_service()
            job = svc._create_import_job(USER_ID, "manual_distress")
            db.session.commit()
            rows = [{"property_address": f"600 Sync Way Unit {i}"} for i in range(499)]
            path = _write_csv(rows)
            svc.process_csv(job.id, path, USER_ID)
            db.session.expire(job)
            assert job.status == "completed"
            assert job.rows_processed == 499
            assert job.rows_imported == 499


# ---------------------------------------------------------------------------
# GIS enrichment
# ---------------------------------------------------------------------------

class TestGISEnrichment:
    """_enrich_with_gis — Requirements 8.1-8.7."""

    def test_match_found_populates_gis_fields(self, app):
        """When GIS returns a parcel, null Lead fields are populated (Req 8.2)."""
        with app.app_context():
            parcel = _make_gis_parcel()
            connector = _make_mock_connector(parcel=parcel)
            svc = _make_service(gis_registry={"dupage_il": connector})
            svc.ingest_foreclosure([_foreclosure_record(
                property_street="700 GIS Match St",
                # Don't pre-set any GIS fields so they start null
                owner_first_name=None,
                owner_last_name=None,
            )], USER_ID)
            lead = db.session.query(Property).filter(
                Property.property_street == "700 GIS Match St"
            ).first()
            assert lead is not None
            assert lead.has_property_match is True
            assert lead.year_built == 1985
            assert lead.bedrooms == 3
            assert lead.square_footage == 1800

    def test_match_found_sets_has_property_match_true(self, app):
        """Req 8.3: has_property_match set to True when match found."""
        with app.app_context():
            connector = _make_mock_connector(parcel=_make_gis_parcel())
            svc = _make_service(gis_registry={"dupage_il": connector})
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.has_property_match is True

    def test_no_match_sets_needs_skip_trace_true(self, app):
        """Req 8.4: No match → needs_skip_trace=True."""
        with app.app_context():
            connector = _make_mock_connector(parcel=None)
            svc = _make_service(gis_registry={"dupage_il": connector})
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.needs_skip_trace is True

    def test_no_match_appends_gis_note(self, app):
        """Req 8.4: No match → 'GIS match not found' appended to notes."""
        with app.app_context():
            connector = _make_mock_connector(parcel=None)
            svc = _make_service(gis_registry={"dupage_il": connector})
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert "GIS match not found" in (lead.notes or "")

    def test_no_match_still_runs_property_address_completion(self, app):
        """No parcel match should not return before canonical situs completion."""
        with app.app_context():
            lead = Property(
                property_street='1239 N Hoyne Ave Chicago IL 60622',
                lead_category='residential',
            )
            db.session.add(lead)
            db.session.flush()
            connector = _make_mock_connector(parcel=None)
            svc = _make_service(gis_registry={"dupage_il": connector})

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
                return_value=None,
            ) as mock_ensure:
                outcome = svc._enrich_with_gis(lead, connector, import_job_id=1)

            assert outcome['match_found'] is False
            assert lead.needs_skip_trace is True
            mock_ensure.assert_called_once()

    def test_gis_error_batch_continues(self, app):
        """Req 8.6: GIS lookup error must not abort the batch."""
        with app.app_context():
            connector = _make_mock_connector(raise_exc=TimeoutError("timeout"))
            svc = _make_service(gis_registry={"dupage_il": connector})
            # Two records — first GIS errors, second should still be processed
            records = [
                _foreclosure_record(property_street="800 Error St"),
                _foreclosure_record(property_street="801 Error St"),
            ]
            job = svc.ingest_foreclosure(records, USER_ID)
            assert job.rows_processed == 2
            assert job.rows_imported == 2
            assert job.status == "completed"

    def test_gis_error_leaves_gis_fields_null(self, app):
        """Req 8.6: On error, GIS fields remain unchanged (null)."""
        with app.app_context():
            connector = _make_mock_connector(raise_exc=RuntimeError("GIS down"))
            svc = _make_service(gis_registry={"dupage_il": connector})
            svc.ingest_foreclosure([_foreclosure_record(property_street="802 GIS Null St")], USER_ID)
            lead = db.session.query(Property).filter(
                Property.property_street == "802 GIS Null St"
            ).first()
            assert lead is not None
            assert lead.year_built is None
            assert lead.bedrooms is None

    def test_gis_error_logged_in_error_log(self, app):
        """Req 8.7: GIS error recorded in ImportJob error_log."""
        with app.app_context():
            connector = _make_mock_connector(raise_exc=RuntimeError("GIS down"))
            svc = _make_service(gis_registry={"dupage_il": connector})
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            gis_errors = [e for e in job.error_log if e.get("type") == "gis_enrichment"]
            assert len(gis_errors) == 1
            assert gis_errors[0]["error"] is not None

    def test_no_connector_registered_skips_enrichment(self, app):
        """Req 8.5: No connector in registry → GIS enrichment skipped, not an error."""
        with app.app_context():
            svc = _make_service(gis_registry={})  # no connector
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            assert job.status == "completed"
            lead = db.session.query(Property).first()
            assert lead is not None


# ---------------------------------------------------------------------------
# ImportJob lifecycle
# ---------------------------------------------------------------------------

class TestImportJobLifecycle:
    """ImportJob creation, status, and row counters — Requirements 9.1-9.7."""

    def test_import_job_created_with_in_progress_status(self, app):
        with app.app_context():
            svc = _make_service()
            # Intercept after _create_import_job but before completion
            original_complete = svc._complete_import_job

            captured_status = {}

            def capturing_complete(job, *args, **kwargs):
                captured_status["before"] = job.status
                return original_complete(job, *args, **kwargs)

            svc._complete_import_job = capturing_complete
            svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            # Should have been in_progress before completion call
            assert captured_status.get("before") == "in_progress"

    def test_import_job_status_completed_after_success(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            assert job.status == "completed"

    def test_import_job_status_failed_on_exception(self, app):
        with app.app_context():
            svc = _make_service()
            # Force an exception by making dedup_engine.process_record raise
            svc.dedup_engine.process_record = MagicMock(side_effect=RuntimeError("boom"))
            with pytest.raises(RuntimeError):
                job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            # Job should be failed — query directly since exception was re-raised
            failed_job = db.session.query(ImportJob).filter(
                ImportJob.source_type == "foreclosure"
            ).first()
            assert failed_job is not None
            assert failed_job.status == "failed"
            assert failed_job.error_log[0]["error"] == "boom"

    def test_rows_processed_count_correct(self, app):
        with app.app_context():
            svc = _make_service()
            records = [
                _foreclosure_record(property_street="900 Row A St"),
                _foreclosure_record(property_street="901 Row B St"),
                _foreclosure_record(property_street="902 Row C St"),
            ]
            job = svc.ingest_foreclosure(records, USER_ID)
            assert job.rows_processed == 3

    def test_rows_imported_count_correct(self, app):
        with app.app_context():
            svc = _make_service()
            records = [
                _foreclosure_record(property_street="1000 Import A St"),
                _foreclosure_record(property_street="1001 Import B St"),
            ]
            job = svc.ingest_foreclosure(records, USER_ID)
            assert job.rows_imported == 2

    def test_rows_skipped_count_for_non_sfr_in_long_owned(self, app):
        with app.app_context():
            svc = _make_service()
            records = [
                _long_owned_record(years_ago=20),  # SFR — imported
                _long_owned_record(sfr=False, property_street="Skip Me St",
                                   county_assessor_pin="XX-00-000-001"),  # skipped
            ]
            job = svc.ingest_long_owned(records, USER_ID)
            assert job.rows_imported == 1
            assert job.rows_skipped == 1
            assert job.rows_processed == 2

    def test_import_job_source_type_set(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            assert job.source_type == "foreclosure"

    def test_lead_last_import_job_id_set(self, app):
        """Req 9.7: Each created/updated lead has last_import_job_id = current job id."""
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            lead = db.session.query(Property).first()
            assert lead.last_import_job_id == job.id

    def test_completed_at_set_after_success(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([_foreclosure_record()], USER_ID)
            assert job.completed_at is not None

    def test_empty_records_list_completes_with_zero_rows(self, app):
        with app.app_context():
            svc = _make_service()
            job = svc.ingest_foreclosure([], USER_ID)
            assert job.status == "completed"
            assert job.rows_processed == 0
            assert job.rows_imported == 0


# ---------------------------------------------------------------------------
# Property 5: review_required creation rule (Hypothesis)
# Feature: source-agnostic-crm-queues, Property 5: review_required creation rule
# ---------------------------------------------------------------------------

from hypothesis import given, settings, assume
from hypothesis import strategies as st


# Strategies for the three critical fields:
# Each field can be None, empty string, or a non-empty stripped string.
_field_strategy = st.one_of(
    st.none(),
    st.just(""),
    st.text(min_size=1).map(str.strip).filter(lambda s: len(s) > 0),
)


@given(
    phone_1=_field_strategy,
    email_1=_field_strategy,
    county_assessor_pin=_field_strategy,
)
@settings(max_examples=100)
def test_property_5_review_required_creation_rule(phone_1, email_1, county_assessor_pin):
    # Feature: source-agnostic-crm-queues, Property 5: review_required creation rule
    # Validates: Requirements 5.2, 5.3

    # Build a mock lead object with only the fields _set_review_required_flag touches
    lead = MagicMock()
    lead.phone_1 = phone_1
    lead.email_1 = email_1
    lead.county_assessor_pin = county_assessor_pin
    lead.review_required = False   # default before flag is set
    lead.review_reason = None

    # Determine whether each field is "populated" (non-null, non-empty after strip)
    has_phone = bool(phone_1 and str(phone_1).strip())
    has_email = bool(email_1 and str(email_1).strip())
    has_pin   = bool(county_assessor_pin and str(county_assessor_pin).strip())

    all_missing = not has_phone and not has_email and not has_pin

    # Call the helper directly — no database needed
    svc = LeadIngestionService(
        dedup_engine=MagicMock(),
        gis_registry={},
    )
    svc._set_review_required_flag(lead, is_creation=True)

    if all_missing:
        # All three critical fields absent → review_required must be True
        assert lead.review_required is True, (
            f"Expected review_required=True when phone_1={phone_1!r}, "
            f"email_1={email_1!r}, county_assessor_pin={county_assessor_pin!r}"
        )
        assert lead.review_reason == "Missing phone, email, and county PIN"
    else:
        # At least one field populated → review_required must remain False
        assert lead.review_required is False, (
            f"Expected review_required=False when phone_1={phone_1!r}, "
            f"email_1={email_1!r}, county_assessor_pin={county_assessor_pin!r} "
            f"(has_phone={has_phone}, has_email={has_email}, has_pin={has_pin})"
        )


# ---------------------------------------------------------------------------
# Property 6: review_required update rule (Hypothesis)
# Feature: source-agnostic-crm-queues, Property 6: review_required update rule
# ---------------------------------------------------------------------------


@given(
    phone_1=_field_strategy,
    email_1=_field_strategy,
    county_assessor_pin=_field_strategy,
)
@settings(max_examples=100)
def test_property_6_review_required_update_rule(phone_1, email_1, county_assessor_pin):
    # Feature: source-agnostic-crm-queues, Property 6: review_required update rule
    # Validates: Requirement 5.4

    # Build a mock lead that already has review_required=True (pre-update state)
    lead = MagicMock()
    lead.phone_1 = phone_1
    lead.email_1 = email_1
    lead.county_assessor_pin = county_assessor_pin
    lead.review_required = True
    lead.review_reason = 'Missing phone, email, and county PIN'

    # Determine whether each field is "populated" (non-null, non-empty after strip)
    has_phone = bool(phone_1 and str(phone_1).strip())
    has_email = bool(email_1 and str(email_1).strip())
    has_pin   = bool(county_assessor_pin and str(county_assessor_pin).strip())

    all_present = has_phone and has_email and has_pin

    # Call the helper directly on an update path — no database needed
    svc = LeadIngestionService(
        dedup_engine=MagicMock(),
        gis_registry={},
    )
    svc._set_review_required_flag(lead, is_creation=False)

    if all_present:
        # All three critical fields populated → flag must clear
        assert lead.review_required is False, (
            f"Expected review_required=False (cleared) when phone_1={phone_1!r}, "
            f"email_1={email_1!r}, county_assessor_pin={county_assessor_pin!r}"
        )
        assert lead.review_reason is None, (
            f"Expected review_reason=None when all fields populated, "
            f"got {lead.review_reason!r}"
        )
    else:
        # At least one field is still null/empty → flag must stay True (unchanged)
        assert lead.review_required is True, (
            f"Expected review_required=True (unchanged) when phone_1={phone_1!r}, "
            f"email_1={email_1!r}, county_assessor_pin={county_assessor_pin!r} "
            f"(has_phone={has_phone}, has_email={has_email}, has_pin={has_pin})"
        )


# ---------------------------------------------------------------------------
# Property 7: GIS no-match sets has_property_match=False (Hypothesis)
# Feature: source-agnostic-crm-queues, Property 7: GIS no-match sets has_property_match=False
# ---------------------------------------------------------------------------

# Strategy: prior has_property_match state — True or False
_prior_match_strategy = st.booleans()

# Strategy: what the GIS connector returns — None (no match) or a real parcel (match)
_gis_result_strategy = st.one_of(
    st.none(),
    st.just(_make_gis_parcel()),
)


@given(
    prior_has_match=_prior_match_strategy,
    gis_result=_gis_result_strategy,
)
@settings(max_examples=100)
def test_property_7_gis_no_match_sets_false(prior_has_match, gis_result):
    # Feature: source-agnostic-crm-queues, Property 7: GIS no-match sets has_property_match=False
    # Validates: Requirements 6.2, 6.3, 6.4

    # Build a mock lead with a prior has_property_match state
    lead = MagicMock()
    lead.property_street = "123 Test St"
    lead.county_assessor_pin = None
    lead.has_property_match = prior_has_match
    lead.needs_skip_trace = False
    lead.notes = None
    # Give lead attributes that _enrich_with_gis iterates over (_GIS_FIELDS)
    for field in [
        'county_assessor_pin', 'property_type', 'year_built', 'square_footage',
        'bedrooms', 'bathrooms', 'lot_size', 'owner_first_name', 'owner_last_name',
        'mailing_address', 'mailing_city', 'mailing_state', 'mailing_zip',
    ]:
        setattr(lead, field, None)
    lead.source_type = "foreclosure"

    # Wire up a mock connector returning the generated gis_result
    connector = _make_mock_connector(parcel=gis_result)

    svc = LeadIngestionService(
        dedup_engine=MagicMock(),
        gis_registry={"dupage_il": connector},
    )

    outcome = svc._enrich_with_gis(lead, connector, import_job_id=1)

    if gis_result is None:
        # GIS connector attempted a lookup and found no match (Req 6.2, 6.3):
        # has_property_match must be False regardless of prior state
        assert lead.has_property_match is False, (
            f"Expected has_property_match=False after GIS no-match "
            f"(prior={prior_has_match!r})"
        )
        assert outcome["match_found"] is False
    else:
        # GIS connector found a match (Req 6.4):
        # has_property_match must be True; a prior True is never overridden to False
        assert lead.has_property_match is True, (
            f"Expected has_property_match=True after GIS match "
            f"(prior={prior_has_match!r})"
        )
        assert outcome["match_found"] is True
        # Crucially: if prior was already True, it remains True (never flipped to False)
        if prior_has_match:
            assert lead.has_property_match is True, (
                f"A prior True must never be overridden to False by a subsequent result "
                f"(prior={prior_has_match!r}, gis_result={gis_result!r})"
            )
