"""Unit tests for OMIntakeService.confirm_job (Tasks 8.1 and 8.2).

Tests cover:
- Successful confirmation creates Deal and transitions job to CONFIRMED
- Re-confirming a CONFIRMED job raises ConflictError with deal_id
- Confirming a non-REVIEW job raises ConflictError
- asking_price null/zero raises InvalidFileError (422)
- unit_count null/< 1 raises InvalidFileError (422)
- unit_mix row with unit_count <= 0 raises InvalidFileError
- User override values are applied to the Deal
- Unrecognized expense labels stored as unmatched_expense_items
- Expense label mapping to Deal OpEx fields
- other_income_monthly computed from other_income_items
- Post-confirmation integrity checks (Task 8.2)
- DB failure mid-transaction rolls back and leaves job in REVIEW
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from app import db
from app.exceptions import ConflictError, InvalidFileError, ResourceNotFoundError
from app.models import Deal, OMIntakeJob, OMFieldOverride, Unit, RentRollEntry, MarketRentAssumption
from app.services.om_intake.om_intake_service import OMIntakeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(app, user_id="user-1", status="REVIEW", extracted_om_data=None):
    """Create and persist a minimal OMIntakeJob for testing."""
    with app.app_context():
        job = OMIntakeJob(
            user_id=user_id,
            original_filename="test.pdf",
            intake_status=status,
            pdf_bytes=b"%PDF-1.4 test",
            extracted_om_data=extracted_om_data or {},
            expires_at=datetime.utcnow() + timedelta(days=90),
        )
        db.session.add(job)
        db.session.commit()
        return job.id


def _minimal_extracted_data():
    """Return a minimal valid extracted_om_data dict."""
    return {
        "asking_price": {"value": 1500000, "confidence": 0.95},
        "unit_count": {"value": 6, "confidence": 0.99},
        "property_address": {"value": "123 Main St", "confidence": 0.9},
        "property_city": {"value": "Chicago", "confidence": 0.9},
        "property_state": {"value": "IL", "confidence": 0.9},
        "property_zip": {"value": "60601", "confidence": 0.9},
        "unit_mix": [
            {
                "unit_type_label": {"value": "2BR/1BA", "confidence": 0.98},
                "unit_count": {"value": 6, "confidence": 0.98},
                "sqft": {"value": 850, "confidence": 0.85},
                "current_avg_rent": {"value": 1200, "confidence": 0.90},
                "proforma_rent": {"value": 1400, "confidence": 0.80},
                "market_rent_estimate": {"value": 1350, "confidence": 0.75},
            }
        ],
        "expense_items": [],
        "other_income_items": [],
    }


def _minimal_confirmed_data():
    """Return a minimal valid confirmed_data dict."""
    return {
        "asking_price": 1500000,
        "unit_count": 6,
        "unit_mix": [
            {
                "unit_type_label": "2BR/1BA",
                "unit_count": 6,
                "sqft": 850,
                "current_avg_rent": 1200,
                "proforma_rent": 1400,
                "market_rent_estimate": 1350,
            }
        ],
        "expense_items": [],
        "other_income_items": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConfirmJobStateValidation:
    """Tests for job state validation in confirm_job."""

    def test_confirm_review_job_succeeds(self, app):
        """Confirming a REVIEW job creates a Deal and transitions to CONFIRMED."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            assert deal is not None
            assert isinstance(deal, Deal)
            deal_id = deal.id

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "CONFIRMED"
            assert job.deal_id == deal_id

    def test_confirm_already_confirmed_raises_conflict(self, app):
        """Re-confirming a CONFIRMED job raises ConflictError with deal_id."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            deal_id = deal.id

        with pytest.raises(ConflictError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, _minimal_confirmed_data())

        assert exc_info.value.status_code == 409
        assert exc_info.value.payload.get("deal_id") == deal_id

    def test_confirm_non_review_status_raises_conflict(self, app):
        """Confirming a job not in REVIEW raises ConflictError."""
        job_id = _make_job(app, status="PARSING", extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with pytest.raises(ConflictError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, _minimal_confirmed_data())

        assert exc_info.value.status_code == 409
        assert "PARSING" in str(exc_info.value)

    def test_confirm_wrong_user_raises_not_found(self, app):
        """Confirming another user's job raises ResourceNotFoundError."""
        job_id = _make_job(app, user_id="user-1", extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with pytest.raises(ResourceNotFoundError):
            with app.app_context():
                service.confirm_job("user-2", job_id, _minimal_confirmed_data())


class TestConfirmJobFieldValidation:
    """Tests for required field validation in confirm_job."""

    def test_null_asking_price_raises_invalid_file_error(self, app):
        """asking_price=None raises InvalidFileError."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["asking_price"] = None

        with pytest.raises(InvalidFileError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, data)

        assert exc_info.value.status_code == 422
        assert "asking_price" in str(exc_info.value)

    def test_zero_asking_price_raises_invalid_file_error(self, app):
        """asking_price=0 raises InvalidFileError."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["asking_price"] = 0

        with pytest.raises(InvalidFileError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, data)

        assert exc_info.value.status_code == 422

    def test_null_unit_count_raises_invalid_file_error(self, app):
        """unit_count=None raises InvalidFileError."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["unit_count"] = None

        with pytest.raises(InvalidFileError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, data)

        assert exc_info.value.status_code == 422
        assert "unit_count" in str(exc_info.value)

    def test_zero_unit_count_raises_invalid_file_error(self, app):
        """unit_count=0 raises InvalidFileError."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["unit_count"] = 0

        with pytest.raises(InvalidFileError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, data)

        assert exc_info.value.status_code == 422

    def test_unit_mix_row_with_zero_unit_count_raises_error(self, app):
        """A unit_mix row with unit_count=0 raises InvalidFileError."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["unit_mix"] = [
            {
                "unit_type_label": "2BR/1BA",
                "unit_count": 0,  # invalid
                "sqft": 850,
                "current_avg_rent": 1200,
                "proforma_rent": 1400,
            }
        ]
        data["unit_count"] = 6  # keep valid to pass initial check

        with pytest.raises(InvalidFileError) as exc_info:
            with app.app_context():
                service.confirm_job("user-1", job_id, data)

        assert exc_info.value.status_code == 422
        assert "unit_count" in str(exc_info.value).lower()


class TestConfirmJobDealCreation:
    """Tests for Deal creation logic in confirm_job."""

    def test_deal_has_correct_purchase_price(self, app):
        """Deal.purchase_price matches asking_price from confirmed_data."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            assert deal.purchase_price == Decimal("1500000")

    def test_deal_has_correct_unit_count(self, app):
        """Deal.unit_count matches unit_count from confirmed_data."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            assert deal.unit_count == 6

    def test_deal_property_fields_mapped(self, app):
        """Deal property address fields are mapped from confirmed_data."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["property_address"] = "456 Oak Ave"
        data["property_city"] = "Springfield"
        data["property_state"] = "IL"
        data["property_zip"] = "62701"

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            assert deal.property_address == "456 Oak Ave"
            assert deal.property_city == "Springfield"
            assert deal.property_state == "IL"
            assert deal.property_zip == "62701"

    def test_units_created_for_each_unit_mix_row(self, app):
        """One Unit record is created per unit in each unit_mix row."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            units = Unit.query.filter_by(deal_id=deal.id).all()
            assert len(units) == 6

    def test_unit_identifiers_are_unique(self, app):
        """Unit identifiers follow the pattern '{unit_type_label}-{i+1}'."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            units = Unit.query.filter_by(deal_id=deal.id).order_by(Unit.unit_identifier).all()
            identifiers = [u.unit_identifier for u in units]
            assert "2BR/1BA-1" in identifiers
            assert "2BR/1BA-6" in identifiers
            assert len(set(identifiers)) == 6  # all unique

    def test_rent_roll_entries_created(self, app):
        """RentRollEntry records are created for each unit."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            units = Unit.query.filter_by(deal_id=deal.id).all()
            for unit in units:
                rre = RentRollEntry.query.filter_by(unit_id=unit.id).first()
                assert rre is not None
                assert rre.current_rent == Decimal("1200")

    def test_market_rent_assumptions_created(self, app):
        """MarketRentAssumption records are created per distinct unit type."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            mras = MarketRentAssumption.query.filter_by(deal_id=deal.id).all()
            assert len(mras) == 1
            assert mras[0].unit_type == "2BR/1BA"
            assert mras[0].post_reno_target_rent == Decimal("1400")
            assert mras[0].target_rent == Decimal("1350")

    def test_market_rent_assumption_null_when_absent(self, app):
        """MarketRentAssumption.target_rent is null when market_rent_estimate is absent."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["unit_mix"][0]["market_rent_estimate"] = None

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            mra = MarketRentAssumption.query.filter_by(deal_id=deal.id).first()
            assert mra.target_rent is None

    def test_other_income_monthly_computed(self, app):
        """other_income_monthly is sum of other_income_items annual_amount / 12."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["other_income_items"] = [
            {"label": "Laundry", "annual_amount": 1200},
            {"label": "Parking", "annual_amount": 2400},
        ]

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            # (1200 + 2400) / 12 = 300
            assert deal.other_income_monthly == Decimal("300")

    def test_user_override_applied_to_deal(self, app):
        """confirmed_data overrides extracted_om_data values in the Deal."""
        extracted = _minimal_extracted_data()
        extracted["asking_price"] = {"value": 1000000, "confidence": 0.9}
        job_id = _make_job(app, extracted_om_data=extracted)
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["asking_price"] = 1500000  # override

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            assert deal.purchase_price == Decimal("1500000")

    def test_override_records_stored(self, app):
        """OMFieldOverride records are created for overridden fields."""
        extracted = _minimal_extracted_data()
        extracted["asking_price"] = {"value": 1000000, "confidence": 0.9}
        job_id = _make_job(app, extracted_om_data=extracted)
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["asking_price"] = 1500000  # override

        with app.app_context():
            service.confirm_job("user-1", job_id, data)
            override = OMFieldOverride.query.filter_by(
                om_intake_job_id=job_id, field_name="asking_price"
            ).first()
            assert override is not None
            assert override.original_value == 1000000
            assert override.overridden_value == 1500000


class TestConfirmJobExpenseMapping:
    """Tests for expense label mapping to Deal OpEx fields."""

    def _confirm_with_expenses(self, app, expense_items):
        """Helper: create job and confirm with given expense_items. Returns deal_id."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["expense_items"] = expense_items
        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            return deal.id

    def test_property_taxes_mapped(self, app):
        """'Real Estate Tax' maps to property_taxes_annual."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Real Estate Tax", "current_annual_amount": 12000}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.property_taxes_annual == Decimal("12000")

    def test_insurance_mapped(self, app):
        """'Insurance' maps to insurance_annual."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Insurance", "current_annual_amount": 6000}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.insurance_annual == Decimal("6000")

    def test_utilities_summed(self, app):
        """Gas + Electric map to utilities_annual (summed)."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Gas", "current_annual_amount": 3000},
            {"label": "Electric", "current_annual_amount": 2400},
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.utilities_annual == Decimal("5400")

    def test_repairs_mapped(self, app):
        """'Maintenance' maps to repairs_and_maintenance_annual."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Maintenance", "current_annual_amount": 4800}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.repairs_and_maintenance_annual == Decimal("4800")

    def test_admin_marketing_mapped(self, app):
        """'Admin' maps to admin_and_marketing_annual."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Admin", "current_annual_amount": 2400}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.admin_and_marketing_annual == Decimal("2400")

    def test_payroll_mapped(self, app):
        """'Payroll' maps to payroll_annual."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Payroll", "current_annual_amount": 18000}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.payroll_annual == Decimal("18000")

    def test_unrecognized_expense_stored_in_warnings(self, app):
        """Unrecognized expense labels are stored in consistency_warnings."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = _minimal_confirmed_data()
        data["expense_items"] = [
            {"label": "Pest Control", "current_annual_amount": 1200}
        ]

        with app.app_context():
            service.confirm_job("user-1", job_id, data)
            job = OMIntakeJob.query.get(job_id)
            warnings = job.consistency_warnings or []
            unmatched = next(
                (w for w in warnings if w.get("type") == "unmatched_expense_items"),
                None,
            )
            assert unmatched is not None
            assert any(
                item.get("label") == "Pest Control"
                for item in unmatched.get("items", [])
            )

    def test_management_rate_as_percentage(self, app):
        """Management fee < 1.0 is stored as management_fee_rate."""
        deal_id = self._confirm_with_expenses(app, [
            {"label": "Management", "current_annual_amount": 0.08}
        ])
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal.management_fee_rate == Decimal("0.08")


class TestConfirmJobMultipleUnitTypes:
    """Tests for multiple unit types in unit_mix."""

    def test_multiple_unit_types_create_correct_units(self, app):
        """Multiple unit_mix rows create the correct total number of units."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()
        data = {
            "asking_price": 2500000,
            "unit_count": 10,
            "unit_mix": [
                {
                    "unit_type_label": "1BR/1BA",
                    "unit_count": 4,
                    "sqft": 650,
                    "current_avg_rent": 1000,
                    "proforma_rent": 1200,
                    "market_rent_estimate": 1100,
                },
                {
                    "unit_type_label": "2BR/1BA",
                    "unit_count": 6,
                    "sqft": 850,
                    "current_avg_rent": 1200,
                    "proforma_rent": 1400,
                    "market_rent_estimate": 1300,
                },
            ],
            "expense_items": [],
            "other_income_items": [],
        }

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            units = Unit.query.filter_by(deal_id=deal.id).all()
            assert len(units) == 10

            mras = MarketRentAssumption.query.filter_by(deal_id=deal.id).all()
            assert len(mras) == 2
            unit_types = {m.unit_type for m in mras}
            assert unit_types == {"1BR/1BA", "2BR/1BA"}


class TestConfirmJobIntegrityChecks:
    """Tests for post-confirmation integrity checks (Task 8.2)."""

    def test_purchase_price_integrity_check_passes(self, app):
        """Integrity check passes when purchase_price matches asking_price."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            assert abs(deal.purchase_price - Decimal("1500000")) <= Decimal("0.01")

    def test_unit_count_integrity_check_passes(self, app):
        """Integrity check passes when unit records created == unit_count."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            units = Unit.query.filter_by(deal_id=deal.id).all()
            assert len(units) == 6

    def test_rent_roll_sum_integrity_check_passes(self, app):
        """Integrity check passes when rent roll sum matches unit mix sum."""
        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, _minimal_confirmed_data())
            units = Unit.query.filter_by(deal_id=deal.id).all()
            rent_sum = sum(
                RentRollEntry.query.filter_by(unit_id=u.id).first().current_rent
                for u in units
            )
            # 6 units * $1200 = $7200
            assert rent_sum == Decimal("7200")

    def test_job_remains_in_review_on_db_failure(self, app):
        """If an exception occurs mid-transaction, job stays in REVIEW."""
        from unittest.mock import patch

        job_id = _make_job(app, extracted_om_data=_minimal_extracted_data())
        service = OMIntakeService()

        # Patch db.session.flush to raise after the Deal is added
        original_flush = db.session.flush
        call_count = [0]

        def failing_flush():
            call_count[0] += 1
            if call_count[0] >= 2:
                raise RuntimeError("Simulated DB failure")
            original_flush()

        with pytest.raises(RuntimeError, match="Simulated DB failure"):
            with app.app_context():
                with patch.object(db.session, "flush", side_effect=failing_flush):
                    service.confirm_job("user-1", job_id, _minimal_confirmed_data())

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "REVIEW"
            # No Deal should have been created
            assert job.deal_id is None


class TestConfirmJobExtractedDataFallback:
    """Tests that confirm_job falls back to extracted_om_data when confirmed_data is partial."""

    def test_uses_extracted_data_when_field_not_in_confirmed(self, app):
        """Fields not in confirmed_data are read from extracted_om_data."""
        extracted = _minimal_extracted_data()
        extracted["property_address"] = {"value": "789 Elm St", "confidence": 0.9}
        job_id = _make_job(app, extracted_om_data=extracted)
        service = OMIntakeService()

        # confirmed_data does NOT include property_address
        data = _minimal_confirmed_data()
        # Remove property_address from confirmed_data if present
        data.pop("property_address", None)

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            assert deal.property_address == "789 Elm St"

    def test_uses_extracted_unit_mix_when_not_in_confirmed(self, app):
        """unit_mix from extracted_om_data is used when not in confirmed_data."""
        extracted = _minimal_extracted_data()
        job_id = _make_job(app, extracted_om_data=extracted)
        service = OMIntakeService()

        # confirmed_data without unit_mix
        data = {
            "asking_price": 1500000,
            "unit_count": 6,
            "expense_items": [],
            "other_income_items": [],
        }

        with app.app_context():
            deal = service.confirm_job("user-1", job_id, data)
            units = Unit.query.filter_by(deal_id=deal.id).all()
            assert len(units) == 6
