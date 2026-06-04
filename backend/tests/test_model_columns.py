"""Unit tests for model column presence — Task 2.3.

Asserts that Property and ImportJob instances accept and persist
source_type, tax_distress_data, and manual_priority (Property) and
source_type (ImportJob) correctly.

Requirements: 10.1, 10.2, 10.3, 9.1
"""
import pytest
from app import db
from app.models.lead import Property
from app.models.import_job import ImportJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_property(**kwargs):
    """Return a Property instance with just enough data to be unique."""
    defaults = dict(
        property_street=kwargs.pop("property_street", "100 Test St"),
        lead_category="residential",
    )
    defaults.update(kwargs)
    return Property(**defaults)


def _minimal_import_job(**kwargs):
    """Return an ImportJob instance with required fields."""
    defaults = dict(
        user_id="test-user-id",
        spreadsheet_id="sheet-abc",
        sheet_name="Sheet1",
        status="pending",
    )
    defaults.update(kwargs)
    return ImportJob(**defaults)


# ---------------------------------------------------------------------------
# Property — in-memory attribute tests (no DB flush)
# ---------------------------------------------------------------------------

class TestPropertyColumnPresence:
    """Property model accepts and exposes the three new columns."""

    def test_source_type_attribute_accepted(self, app):
        with app.app_context():
            prop = _minimal_property(source_type="foreclosure")
            assert prop.source_type == "foreclosure"

    def test_tax_distress_data_attribute_accepted(self, app):
        with app.app_context():
            payload = {"signal_type": "tax_delinquency"}
            prop = _minimal_property(tax_distress_data=payload)
            assert prop.tax_distress_data == payload

    def test_manual_priority_attribute_accepted(self, app):
        with app.app_context():
            prop = _minimal_property(manual_priority=3)
            assert prop.manual_priority == 3

    def test_all_three_columns_together(self, app):
        with app.app_context():
            payload = {"signal_type": "tax_delinquency"}
            prop = _minimal_property(
                source_type="foreclosure",
                tax_distress_data=payload,
                manual_priority=3,
            )
            assert prop.source_type == "foreclosure"
            assert prop.tax_distress_data == payload
            assert prop.manual_priority == 3

    def test_new_columns_default_to_none(self, app):
        with app.app_context():
            prop = _minimal_property()
            assert prop.source_type is None
            assert prop.tax_distress_data is None
            assert prop.manual_priority is None


# ---------------------------------------------------------------------------
# Property — DB round-trip tests
# ---------------------------------------------------------------------------

class TestPropertyColumnRoundTrip:
    """Property new columns persist to and load from the test DB correctly."""

    def test_source_type_round_trips(self, app):
        with app.app_context():
            prop = _minimal_property(
                property_street="200 Roundtrip Ave",
                source_type="foreclosure",
            )
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.source_type == "foreclosure"

    def test_tax_distress_data_round_trips(self, app):
        with app.app_context():
            payload = {
                "signal_type": "tax_delinquency",
                "delinquent_amount": 4250.00,
                "tax_year": 2022,
            }
            prop = _minimal_property(
                property_street="300 Tax Ave",
                tax_distress_data=payload,
            )
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.tax_distress_data == payload

    def test_manual_priority_round_trips(self, app):
        with app.app_context():
            prop = _minimal_property(
                property_street="400 Priority Blvd",
                manual_priority=3,
            )
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.manual_priority == 3

    def test_all_three_columns_round_trip_together(self, app):
        with app.app_context():
            payload = {
                "signal_type": "tax_delinquency",
                "delinquent_amount": 1500.50,
                "tax_year": 2021,
            }
            prop = _minimal_property(
                property_street="500 Full Data Ln",
                source_type="foreclosure",
                tax_distress_data=payload,
                manual_priority=3,
            )
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.source_type == "foreclosure"
            assert loaded.tax_distress_data == payload
            assert loaded.manual_priority == 3

    def test_null_values_round_trip(self, app):
        with app.app_context():
            prop = _minimal_property(property_street="600 Null St")
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.source_type is None
            assert loaded.tax_distress_data is None
            assert loaded.manual_priority is None

    def test_tax_distress_data_null_signal_type(self, app):
        """JSON field handles minimal payload with only signal_type."""
        with app.app_context():
            payload = {"signal_type": "tax_sale"}
            prop = _minimal_property(
                property_street="700 Tax Sale Rd",
                tax_distress_data=payload,
            )
            db.session.add(prop)
            db.session.commit()
            lead_id = prop.id

            db.session.expire_all()
            loaded = db.session.get(Property, lead_id)
            assert loaded.tax_distress_data["signal_type"] == "tax_sale"


# ---------------------------------------------------------------------------
# ImportJob — in-memory attribute tests
# ---------------------------------------------------------------------------

class TestImportJobColumnPresence:
    """ImportJob model accepts and exposes the source_type column."""

    def test_source_type_attribute_accepted(self, app):
        with app.app_context():
            job = _minimal_import_job(source_type="foreclosure")
            assert job.source_type == "foreclosure"

    def test_source_type_defaults_to_none(self, app):
        with app.app_context():
            job = _minimal_import_job()
            assert job.source_type is None

    def test_all_valid_source_types_accepted(self, app):
        valid_types = [
            "foreclosure",
            "long_owned",
            "absentee_owner",
            "tax_distress",
            "manual_distress",
        ]
        with app.app_context():
            for source_type in valid_types:
                job = _minimal_import_job(source_type=source_type)
                assert job.source_type == source_type


# ---------------------------------------------------------------------------
# ImportJob — DB round-trip tests
# ---------------------------------------------------------------------------

class TestImportJobColumnRoundTrip:
    """ImportJob source_type column persists to and loads from the test DB."""

    def test_source_type_round_trips(self, app):
        with app.app_context():
            job = _minimal_import_job(source_type="foreclosure")
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            db.session.expire_all()
            loaded = db.session.get(ImportJob, job_id)
            assert loaded.source_type == "foreclosure"

    def test_source_type_null_round_trips(self, app):
        with app.app_context():
            job = _minimal_import_job()
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            db.session.expire_all()
            loaded = db.session.get(ImportJob, job_id)
            assert loaded.source_type is None

    def test_source_type_all_values_round_trip(self, app):
        valid_types = [
            "foreclosure",
            "long_owned",
            "absentee_owner",
            "tax_distress",
            "manual_distress",
        ]
        with app.app_context():
            for i, source_type in enumerate(valid_types):
                job = _minimal_import_job(
                    spreadsheet_id=f"sheet-{i}",
                    source_type=source_type,
                )
                db.session.add(job)
            db.session.commit()

            # Re-query and verify each stored value
            jobs = db.session.query(ImportJob).filter(
                ImportJob.spreadsheet_id.like("sheet-%")
            ).all()
            stored_types = {j.source_type for j in jobs}
            assert stored_types == set(valid_types)
