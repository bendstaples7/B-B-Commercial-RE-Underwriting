"""
Unit tests for OMIntakeService._run_consistency_checks (task 5.2).

Tests cover:
- Unit count sum check (Req 10.1)
- NOI consistency check (Req 10.2)
- Cap rate consistency check (Req 10.3)
- GRM consistency check (Req 10.4)
- Missing field flags: asking_price_missing_error (Req 10.6)
- Missing field flags: unit_count_missing_error (Req 10.7)
- Insufficient data warnings when operands are null/zero (Req 10.8)
- store_extracted_data integration (Req 3.2)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.om_intake_job import OMIntakeJob
from app.services.om_intake.om_intake_service import OMIntakeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(value, confidence=0.9):
    """Build a field dict in ExtractedOMData format."""
    return {"value": value, "confidence": confidence}


def _unit_mix_row(unit_type="1BR/1BA", unit_count=4, sqft=700,
                  current_avg_rent=1000, proforma_rent=1100):
    return {
        "unit_type_label": _field(unit_type),
        "unit_count": _field(unit_count),
        "sqft": _field(sqft),
        "current_avg_rent": _field(current_avg_rent),
        "proforma_rent": _field(proforma_rent),
    }


def _base_data_dict(
    asking_price=2_000_000,
    unit_count=8,
    unit_mix=None,
    current_noi=100_000,
    current_effective_gross_income=150_000,
    current_gross_expenses=50_000,
    current_cap_rate=0.05,          # 100_000 / 2_000_000
    current_grm=10.0,               # 2_000_000 / 200_000
    current_gross_potential_income=200_000,
):
    """Return a fully consistent data_dict for use in tests."""
    if unit_mix is None:
        unit_mix = [
            _unit_mix_row("1BR/1BA", unit_count=4),
            _unit_mix_row("2BR/1BA", unit_count=4),
        ]
    return {
        "asking_price": _field(asking_price),
        "unit_count": _field(unit_count),
        "unit_mix": unit_mix,
        "current_noi": _field(current_noi),
        "current_effective_gross_income": _field(current_effective_gross_income),
        "current_gross_expenses": _field(current_gross_expenses),
        "current_cap_rate": _field(current_cap_rate),
        "current_grm": _field(current_grm),
        "current_gross_potential_income": _field(current_gross_potential_income),
    }


def _make_mock_job():
    """Return a simple object that accepts attribute assignment for flag tests."""
    class _FakeJob:
        asking_price_missing_error = None
        unit_count_missing_error = None
    return _FakeJob()


# ---------------------------------------------------------------------------
# Tests for _run_consistency_checks (pure logic, no DB needed)
# ---------------------------------------------------------------------------

class TestRunConsistencyChecks:
    """Tests for OMIntakeService._run_consistency_checks."""

    # ------------------------------------------------------------------
    # Req 10.6 — asking_price_missing_error flag
    # ------------------------------------------------------------------

    def test_asking_price_present_clears_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(asking_price=1_000_000)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.asking_price_missing_error is False

    def test_asking_price_null_sets_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(asking_price=None)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.asking_price_missing_error is True

    def test_asking_price_zero_sets_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(asking_price=0)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.asking_price_missing_error is True

    # ------------------------------------------------------------------
    # Req 10.7 — unit_count_missing_error flag
    # ------------------------------------------------------------------

    def test_unit_count_present_clears_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(unit_count=8)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.unit_count_missing_error is False

    def test_unit_count_null_sets_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(unit_count=None)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.unit_count_missing_error is True

    def test_unit_count_zero_sets_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(unit_count=0)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.unit_count_missing_error is True

    def test_unit_count_negative_sets_flag(self):
        job = _make_mock_job()
        data = _base_data_dict(unit_count=-1)
        OMIntakeService._run_consistency_checks(job, data)
        assert job.unit_count_missing_error is True

    # ------------------------------------------------------------------
    # Req 10.1 — unit_count sum check
    # ------------------------------------------------------------------

    def test_unit_count_sum_matches_no_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(
            unit_count=8,
            unit_mix=[
                _unit_mix_row("1BR", unit_count=4),
                _unit_mix_row("2BR", unit_count=4),
            ],
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "unit_count_mismatch_warning" not in types

    def test_unit_count_sum_mismatch_adds_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(
            unit_count=10,  # stated 10 but mix sums to 8
            unit_mix=[
                _unit_mix_row("1BR", unit_count=4),
                _unit_mix_row("2BR", unit_count=4),
            ],
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        mismatch = [w for w in warnings if w["type"] == "unit_count_mismatch_warning"]
        assert len(mismatch) == 1
        w = mismatch[0]
        assert w["field"] == "unit_count"
        assert w["computed"] == 8
        assert w["stated"] == 10
        assert w["delta"] == -2

    def test_unit_count_sum_mismatch_positive_delta(self):
        job = _make_mock_job()
        data = _base_data_dict(
            unit_count=6,
            unit_mix=[
                _unit_mix_row("1BR", unit_count=4),
                _unit_mix_row("2BR", unit_count=4),
            ],
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        mismatch = [w for w in warnings if w["type"] == "unit_count_mismatch_warning"]
        assert mismatch[0]["delta"] == 2

    def test_unit_count_sum_skipped_when_stated_null(self):
        """No mismatch warning when top-level unit_count is null."""
        job = _make_mock_job()
        data = _base_data_dict(
            unit_count=None,
            unit_mix=[_unit_mix_row("1BR", unit_count=4)],
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "unit_count_mismatch_warning" not in types

    # ------------------------------------------------------------------
    # Req 10.2 — NOI consistency check
    # ------------------------------------------------------------------

    def test_noi_consistent_no_warning(self):
        """EGI - expenses == stated NOI → no warning."""
        job = _make_mock_job()
        # 150_000 - 50_000 = 100_000 (exact match)
        data = _base_data_dict(
            current_noi=100_000,
            current_effective_gross_income=150_000,
            current_gross_expenses=50_000,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "noi_consistency_warning" not in types

    def test_noi_within_tolerance_no_warning(self):
        """Difference within 2% tolerance → no warning."""
        job = _make_mock_job()
        # computed = 150_000 - 50_000 = 100_000; stated = 101_000
        # |100_000 - 101_000| / 101_000 ≈ 0.0099 < 0.02
        data = _base_data_dict(
            current_noi=101_000,
            current_effective_gross_income=150_000,
            current_gross_expenses=50_000,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "noi_consistency_warning" not in types

    def test_noi_outside_tolerance_adds_warning(self):
        """Difference > 2% → noi_consistency_warning."""
        job = _make_mock_job()
        # computed = 150_000 - 50_000 = 100_000; stated = 80_000
        # |100_000 - 80_000| / 80_000 = 0.25 > 0.02
        data = _base_data_dict(
            current_noi=80_000,
            current_effective_gross_income=150_000,
            current_gross_expenses=50_000,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        noi_warns = [w for w in warnings if w["type"] == "noi_consistency_warning"]
        assert len(noi_warns) == 1
        w = noi_warns[0]
        assert w["field"] == "current_noi"
        assert w["stated"] == 80_000.0
        assert abs(w["computed"] - 100_000.0) < 0.01

    def test_noi_null_operand_adds_insufficient_data_warning(self):
        """Null NOI → insufficient_data_warning for noi_consistency."""
        job = _make_mock_job()
        data = _base_data_dict(current_noi=None)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "noi_consistency"]
        assert len(insuf) == 1
        assert insuf[0]["reason"] == "missing operand"

    def test_noi_zero_stated_adds_insufficient_data_warning(self):
        """Zero stated NOI → insufficient_data_warning (avoid division by zero)."""
        job = _make_mock_job()
        data = _base_data_dict(current_noi=0)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "noi_consistency"]
        assert len(insuf) == 1

    # ------------------------------------------------------------------
    # Req 10.3 — Cap rate consistency check
    # ------------------------------------------------------------------

    def test_cap_rate_consistent_no_warning(self):
        """computed cap rate == stated → no warning."""
        job = _make_mock_job()
        # 100_000 / 2_000_000 = 0.05
        data = _base_data_dict(
            asking_price=2_000_000,
            current_noi=100_000,
            current_cap_rate=0.05,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "cap_rate_consistency_warning" not in types

    def test_cap_rate_within_tolerance_no_warning(self):
        """Difference ≤ 0.005 → no warning."""
        job = _make_mock_job()
        # computed = 100_000 / 2_000_000 = 0.05; stated = 0.054 → diff = 0.004 ≤ 0.005
        data = _base_data_dict(
            asking_price=2_000_000,
            current_noi=100_000,
            current_cap_rate=0.054,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "cap_rate_consistency_warning" not in types

    def test_cap_rate_outside_tolerance_adds_warning(self):
        """Difference > 0.005 → cap_rate_consistency_warning."""
        job = _make_mock_job()
        # computed = 100_000 / 2_000_000 = 0.05; stated = 0.08 → diff = 0.03 > 0.005
        data = _base_data_dict(
            asking_price=2_000_000,
            current_noi=100_000,
            current_cap_rate=0.08,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        cap_warns = [w for w in warnings if w["type"] == "cap_rate_consistency_warning"]
        assert len(cap_warns) == 1
        w = cap_warns[0]
        assert w["field"] == "current_cap_rate"
        assert w["stated"] == 0.08

    def test_cap_rate_null_asking_price_adds_insufficient_data_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(asking_price=None)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "cap_rate_consistency"]
        assert len(insuf) == 1

    def test_cap_rate_null_cap_rate_adds_insufficient_data_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(current_cap_rate=None)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "cap_rate_consistency"]
        assert len(insuf) == 1

    # ------------------------------------------------------------------
    # Req 10.4 — GRM consistency check
    # ------------------------------------------------------------------

    def test_grm_consistent_no_warning(self):
        """computed GRM == stated → no warning."""
        job = _make_mock_job()
        # 2_000_000 / 200_000 = 10.0
        data = _base_data_dict(
            asking_price=2_000_000,
            current_gross_potential_income=200_000,
            current_grm=10.0,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "grm_consistency_warning" not in types

    def test_grm_within_tolerance_no_warning(self):
        """Difference ≤ 2% → no warning."""
        job = _make_mock_job()
        # computed = 2_000_000 / 200_000 = 10.0; stated = 10.19 → diff/stated ≈ 0.019 ≤ 0.02
        data = _base_data_dict(
            asking_price=2_000_000,
            current_gross_potential_income=200_000,
            current_grm=10.19,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        types = [w["type"] for w in warnings]
        assert "grm_consistency_warning" not in types

    def test_grm_outside_tolerance_adds_warning(self):
        """Difference > 2% → grm_consistency_warning."""
        job = _make_mock_job()
        # computed = 2_000_000 / 200_000 = 10.0; stated = 12.0 → diff/stated = 0.167 > 0.02
        data = _base_data_dict(
            asking_price=2_000_000,
            current_gross_potential_income=200_000,
            current_grm=12.0,
        )
        warnings = OMIntakeService._run_consistency_checks(job, data)
        grm_warns = [w for w in warnings if w["type"] == "grm_consistency_warning"]
        assert len(grm_warns) == 1
        w = grm_warns[0]
        assert w["field"] == "current_grm"
        assert w["stated"] == 12.0

    def test_grm_null_gpi_adds_insufficient_data_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(current_gross_potential_income=None)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "grm_consistency"]
        assert len(insuf) == 1

    def test_grm_zero_gpi_adds_insufficient_data_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(current_gross_potential_income=0)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "grm_consistency"]
        assert len(insuf) == 1

    def test_grm_null_grm_adds_insufficient_data_warning(self):
        job = _make_mock_job()
        data = _base_data_dict(current_grm=None)
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"
                 and w["field"] == "grm_consistency"]
        assert len(insuf) == 1

    # ------------------------------------------------------------------
    # Req 10.8 — all operands null → three insufficient_data_warnings
    # ------------------------------------------------------------------

    def test_all_null_produces_three_insufficient_data_warnings(self):
        """When all financial fields are null, each check emits an insufficient_data_warning."""
        job = _make_mock_job()
        data = {
            "asking_price": _field(None),
            "unit_count": _field(None),
            "unit_mix": [],
            "current_noi": _field(None),
            "current_effective_gross_income": _field(None),
            "current_gross_expenses": _field(None),
            "current_cap_rate": _field(None),
            "current_grm": _field(None),
            "current_gross_potential_income": _field(None),
        }
        warnings = OMIntakeService._run_consistency_checks(job, data)
        insuf = [w for w in warnings if w["type"] == "insufficient_data_warning"]
        fields = {w["field"] for w in insuf}
        assert "noi_consistency" in fields
        assert "cap_rate_consistency" in fields
        assert "grm_consistency" in fields

    # ------------------------------------------------------------------
    # Fully consistent data → no warnings
    # ------------------------------------------------------------------

    def test_fully_consistent_data_no_warnings(self):
        """A perfectly consistent data dict should produce zero warnings."""
        job = _make_mock_job()
        data = _base_data_dict()
        warnings = OMIntakeService._run_consistency_checks(job, data)
        # Only insufficient_data_warnings are acceptable (none expected here)
        non_insuf = [w for w in warnings if w["type"] != "insufficient_data_warning"]
        assert non_insuf == []


# ---------------------------------------------------------------------------
# Integration test: store_extracted_data persists warnings and flags
# ---------------------------------------------------------------------------

def _make_extracted_om_data(**field_value_overrides):
    """Build an ExtractedOMData instance using the field-dict format.

    Each key in *field_value_overrides* maps to the ``value`` of that field.
    All other fields default to ``{"value": None, "confidence": 0.0}``.
    """
    from app.services.om_intake.om_intake_dataclasses import ExtractedOMData

    kwargs = {}
    for f in ExtractedOMData.__dataclass_fields__:
        if f in field_value_overrides:
            v = field_value_overrides[f]
            if f in ("unit_mix", "other_income_items", "expense_items"):
                # These are lists, not field dicts
                kwargs[f] = v if v is not None else []
            else:
                kwargs[f] = {"value": v, "confidence": 0.9 if v is not None else 0.0}
        # else: use the dataclass default_factory
    return ExtractedOMData(**kwargs)


class TestStoreExtractedDataIntegration:
    """Integration tests for store_extracted_data using an in-memory SQLite DB."""

    @pytest.fixture(autouse=True)
    def setup(self, app):
        """Use the shared app fixture (SQLite in-memory)."""
        self.app = app
        self.service = OMIntakeService()

    def _create_job(self):
        """Insert a minimal OMIntakeJob and return its id."""
        job = OMIntakeJob(
            user_id="test-user",
            original_filename="test.pdf",
            intake_status="EXTRACTING",
            expires_at=datetime.utcnow() + timedelta(days=90),
        )
        db.session.add(job)
        db.session.commit()
        return job.id

    def test_store_extracted_data_persists_consistency_warnings(self):
        """store_extracted_data should persist consistency_warnings on the job."""
        job_id = self._create_job()

        # unit_mix is empty → sum = 0, but stated unit_count = 10 → mismatch warning
        data = _make_extracted_om_data(
            asking_price=2_000_000,
            unit_count=10,
            current_noi=100_000,
            current_cap_rate=0.05,
            current_grm=10.0,
            current_gross_potential_income=200_000,
            current_effective_gross_income=150_000,
            current_gross_expenses=50_000,
            unit_mix=[],
        )

        self.service.store_extracted_data(job_id, data)

        job = OMIntakeJob.query.get(job_id)
        assert job.consistency_warnings is not None
        assert isinstance(job.consistency_warnings, list)

    def test_store_extracted_data_sets_asking_price_missing_error(self):
        """asking_price=None → asking_price_missing_error=True on the job."""
        job_id = self._create_job()

        data = _make_extracted_om_data(
            asking_price=None,
            unit_count=8,
        )

        self.service.store_extracted_data(job_id, data)

        job = OMIntakeJob.query.get(job_id)
        assert job.asking_price_missing_error is True

    def test_store_extracted_data_sets_unit_count_missing_error(self):
        """unit_count=None → unit_count_missing_error=True on the job."""
        job_id = self._create_job()

        data = _make_extracted_om_data(
            asking_price=1_000_000,
            unit_count=None,
        )

        self.service.store_extracted_data(job_id, data)

        job = OMIntakeJob.query.get(job_id)
        assert job.unit_count_missing_error is True

    def test_store_extracted_data_clears_flags_when_valid(self):
        """Valid asking_price and unit_count → both flags False."""
        job_id = self._create_job()

        data = _make_extracted_om_data(
            asking_price=2_000_000,
            unit_count=8,
        )

        self.service.store_extracted_data(job_id, data)

        job = OMIntakeJob.query.get(job_id)
        assert job.asking_price_missing_error is False
        assert job.unit_count_missing_error is False
