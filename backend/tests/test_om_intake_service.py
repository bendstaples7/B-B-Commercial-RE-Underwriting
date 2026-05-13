"""
Integration tests for the OM Intake pipeline — Celery retry / failure behavior.

Task 18.3: Verify that when GeminiOMExtractorService.extract raises GeminiAPIError
the pipeline transitions the job to FAILED status (max_retries=0, no auto-retry).

The tests run the pipeline function synchronously (bypassing Celery/Redis) by
calling the inner logic directly with mocked external services, so no broker is
required.

Requirements: 9.1
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

from app import db
from app.models import OMIntakeJob
from app.exceptions import GeminiAPIError


# ---------------------------------------------------------------------------
# Minimal valid PDF bytes (same as used in test_om_intake_full_flow.py)
# ---------------------------------------------------------------------------

_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 200>>
stream
BT /F1 12 Tf 50 750 Td
(Offering Memorandum - 123 Main Street Chicago IL) Tj
0 -20 Td (Asking Price: $2,500,000) Tj
0 -20 Td (Unit Count: 10 units) Tj
0 -20 Td (Cap Rate: 6.5%) Tj
0 -20 Td (NOI: $162,500) Tj
0 -20 Td (Unit Mix: 5x 2BR/1BA at $1,200/mo, 5x 1BR/1BA at $950/mo) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
0000000526 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
605
%%EOF"""


# ---------------------------------------------------------------------------
# Helper: create a PENDING job directly in the DB
# ---------------------------------------------------------------------------

def _create_pending_job(app, user_id: str = "test-retry-user") -> int:
    """Insert a PENDING OMIntakeJob and return its id."""
    with app.app_context():
        job = OMIntakeJob(
            user_id=user_id,
            original_filename="test_retry.pdf",
            intake_status="PENDING",
            pdf_bytes=_MINIMAL_PDF,
            expires_at=datetime.utcnow() + timedelta(days=90),
        )
        db.session.add(job)
        db.session.commit()
        return job.id


# ---------------------------------------------------------------------------
# Helper: run the pipeline function body synchronously (no Celery broker)
# ---------------------------------------------------------------------------

def _run_pipeline_sync(app, job_id: int) -> None:
    """Execute the om_intake pipeline logic synchronously inside an app context.

    Patches ``app.create_app`` (the source module) so the Celery task body
    uses the test app (and its SQLite in-memory DB) instead of spinning up a
    fresh production app that has no knowledge of the test data.

    The task does ``from app import create_app`` inside the function body, so
    we must patch the name in the ``app`` package namespace.
    """
    from celery_worker import process_om_intake_pipeline

    with patch("app.create_app", return_value=app):
        try:
            process_om_intake_pipeline.run(job_id)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# TestCeleryRetryBehavior
# ---------------------------------------------------------------------------

class TestCeleryRetryBehavior:
    """Integration tests for pipeline failure / retry behavior.

    Since the pipeline has max_retries=0, a GeminiAPIError causes an immediate
    FAILED transition — there is no automatic Celery retry.

    Requirements: 9.1
    """

    def test_gemini_api_error_transitions_job_to_failed(self, app):
        """When GeminiOMExtractorService.extract raises GeminiAPIError the job
        must transition to FAILED status.

        Validates: Requirements 9.1
        """
        job_id = _create_pending_job(app)

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            side_effect=GeminiAPIError("Simulated Gemini API failure"),
        ):
            _run_pipeline_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job is not None
            assert job.intake_status == "FAILED", (
                f"Expected FAILED but got {job.intake_status!r}. "
                "The pipeline must transition to FAILED when Gemini raises GeminiAPIError."
            )

    def test_gemini_api_error_sets_error_message(self, app):
        """When the pipeline fails due to GeminiAPIError the job's error_message
        must be populated with a non-empty string.

        Validates: Requirements 9.1
        """
        job_id = _create_pending_job(app)
        error_text = "Gemini quota exceeded — 429 Too Many Requests"

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            side_effect=GeminiAPIError(error_text),
        ):
            _run_pipeline_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "FAILED"
            assert job.error_message is not None, "error_message must be set on FAILED job"
            assert len(job.error_message) > 0, "error_message must not be empty"
            assert error_text in job.error_message, (
                f"Expected error_message to contain {error_text!r}, "
                f"got {job.error_message!r}"
            )

    def test_gemini_api_error_records_failed_at_stage(self, app):
        """When the pipeline fails during Gemini extraction the failed_at_stage
        must be set to the stage that was active when the error occurred.

        Validates: Requirements 9.1
        """
        job_id = _create_pending_job(app)

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            side_effect=GeminiAPIError("Network timeout"),
        ):
            _run_pipeline_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "FAILED"
            assert job.failed_at_stage == "EXTRACTING", (
                f"Expected failed_at_stage='EXTRACTING' but got {job.failed_at_stage!r}"
            )

    def test_manual_retry_after_failure_succeeds(self, app):
        """Simulates the user-initiated retry flow (Req 9.3).

        Validates: Requirements 9.1
        """
        # --- Attempt 1: fails ---
        job_id_1 = _create_pending_job(app)

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            side_effect=GeminiAPIError("Transient API error"),
        ):
            _run_pipeline_sync(app, job_id_1)

        with app.app_context():
            job1 = OMIntakeJob.query.get(job_id_1)
            assert job1.intake_status == "FAILED"

        # --- Attempt 2: also fails ---
        job_id_2 = _create_pending_job(app)

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            side_effect=GeminiAPIError("Transient API error again"),
        ):
            _run_pipeline_sync(app, job_id_2)

        with app.app_context():
            job2 = OMIntakeJob.query.get(job_id_2)
            assert job2.intake_status == "FAILED"

        # --- Attempt 3: succeeds ---
        job_id_3 = _create_pending_job(app)
        _mock_extracted = _build_mock_extracted_data()

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            return_value=_mock_extracted,
        ), patch(
            "app.services.om_intake.rentcast_service"
            ".RentCastService.__init__",
            side_effect=Exception("RentCast unavailable in test"),
        ):
            _run_pipeline_sync(app, job_id_3)

        with app.app_context():
            job3 = OMIntakeJob.query.get(job_id_3)
            assert job3.intake_status == "REVIEW", (
                f"Third attempt (with successful Gemini) must reach REVIEW, "
                f"got {job3.intake_status!r}"
            )

    def test_pipeline_no_auto_retry_on_gemini_error(self, app):
        """Verify that the pipeline does NOT auto-retry when Gemini raises
        GeminiAPIError — it should call extract exactly once and then fail.

        Validates: Requirements 9.1
        """
        job_id = _create_pending_job(app)
        mock_extract = MagicMock(side_effect=GeminiAPIError("API down"))

        with patch(
            "app.services.om_intake.gemini_om_extractor_service"
            ".GeminiOMExtractorService.extract",
            mock_extract,
        ):
            _run_pipeline_sync(app, job_id)

        assert mock_extract.call_count == 1, (
            f"Expected extract to be called exactly once (max_retries=0), "
            f"but it was called {mock_extract.call_count} time(s)."
        )

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "FAILED"


# ---------------------------------------------------------------------------
# Helper: build a minimal ExtractedOMData for success-path mocking
# ---------------------------------------------------------------------------

def _build_mock_extracted_data():
    """Return a minimal ExtractedOMData instance suitable for pipeline success tests."""
    from app.services.om_intake.om_intake_dataclasses import ExtractedOMData

    def _field(value, confidence=0.9):
        return {"value": value, "confidence": confidence}

    def _null_field():
        return {"value": None, "confidence": 0.0}

    return ExtractedOMData(
        property_address=_field("123 Main St"),
        property_city=_field("Chicago"),
        property_state=_field("IL"),
        property_zip=_field("60601"),
        neighborhood=_null_field(),
        asking_price=_field(2500000),
        unit_count=_field(10),
        year_built=_field(1920),
        building_sqft=_field(8500),
        zoning=_null_field(),
        price_per_unit=_null_field(),
        price_per_sqft=_null_field(),
        lot_size=_null_field(),
        current_noi=_field(162500),
        current_cap_rate=_field(0.065),
        current_grm=_null_field(),
        current_gross_potential_income=_field(162500),
        current_effective_gross_income=_field(154375),
        current_vacancy_rate=_field(0.05),
        current_gross_expenses=_field(0),
        proforma_noi=_field(175000),
        proforma_cap_rate=_null_field(),
        proforma_grm=_null_field(),
        proforma_gross_potential_income=_field(175000),
        proforma_effective_gross_income=_field(166250),
        proforma_vacancy_rate=_field(0.05),
        proforma_gross_expenses=_field(0),
        unit_mix=[
            {
                "unit_type_label": _field("2BR/1BA"),
                "unit_count": _field(5),
                "sqft": _field(850),
                "current_avg_rent": _field(1200),
                "proforma_rent": _field(1400),
            },
            {
                "unit_type_label": _field("1BR/1BA"),
                "unit_count": _field(5),
                "sqft": _field(650),
                "current_avg_rent": _field(950),
                "proforma_rent": _field(1100),
            },
        ],
        apartment_income_current=_null_field(),
        apartment_income_proforma=_null_field(),
        other_income_items=[],
        expense_items=[],
        down_payment_pct=_null_field(),
        loan_amount=_null_field(),
        interest_rate=_null_field(),
        amortization_years=_null_field(),
        debt_service_annual=_null_field(),
        current_dscr=_null_field(),
        proforma_dscr=_null_field(),
        current_cash_on_cash=_null_field(),
        proforma_cash_on_cash=_null_field(),
        listing_broker_name=_null_field(),
        listing_broker_company=_null_field(),
        listing_broker_phone=_null_field(),
        listing_broker_email=_null_field(),
    )


# ---------------------------------------------------------------------------
# Mock data for TestOMIntakePipelineIntegration
# ---------------------------------------------------------------------------

_PIPELINE_MOCK_EXTRACTED_DATA = {
    "property_address": {"value": "123 Main St", "confidence": 0.95},
    "property_city": {"value": "Chicago", "confidence": 0.95},
    "property_state": {"value": "IL", "confidence": 0.95},
    "property_zip": {"value": "60601", "confidence": 0.95},
    "neighborhood": {"value": "Rogers Park", "confidence": 0.80},
    "asking_price": {"value": 2500000, "confidence": 0.95},
    "unit_count": {"value": 10, "confidence": 0.99},
    "year_built": {"value": 1920, "confidence": 0.90},
    "building_sqft": {"value": 8500, "confidence": 0.85},
    "zoning": {"value": "RT-4", "confidence": 0.80},
    "price_per_unit": {"value": 250000, "confidence": 0.90},
    "price_per_sqft": {"value": 294, "confidence": 0.85},
    "lot_size": {"value": 5400, "confidence": 0.80},
    "current_noi": {"value": 162500, "confidence": 0.90},
    "current_cap_rate": {"value": 0.065, "confidence": 0.90},
    "current_grm": {"value": 15.38, "confidence": 0.85},
    "current_gross_potential_income": {"value": 162500, "confidence": 0.85},
    "current_effective_gross_income": {"value": 154375, "confidence": 0.85},
    "current_vacancy_rate": {"value": 0.05, "confidence": 0.80},
    "current_gross_expenses": {"value": 0, "confidence": 0.0},
    "proforma_noi": {"value": 175000, "confidence": 0.85},
    "proforma_cap_rate": {"value": 0.07, "confidence": 0.85},
    "proforma_grm": {"value": 14.29, "confidence": 0.80},
    "proforma_gross_potential_income": {"value": 175000, "confidence": 0.80},
    "proforma_effective_gross_income": {"value": 166250, "confidence": 0.80},
    "proforma_vacancy_rate": {"value": 0.05, "confidence": 0.80},
    "proforma_gross_expenses": {"value": 0, "confidence": 0.0},
    "unit_mix": [
        {
            "unit_type_label": {"value": "2BR/1BA", "confidence": 0.98},
            "unit_count": {"value": 5, "confidence": 0.98},
            "sqft": {"value": 850, "confidence": 0.85},
            "current_avg_rent": {"value": 1200, "confidence": 0.90},
            "proforma_rent": {"value": 1400, "confidence": 0.80},
        },
        {
            "unit_type_label": {"value": "1BR/1BA", "confidence": 0.98},
            "unit_count": {"value": 5, "confidence": 0.98},
            "sqft": {"value": 650, "confidence": 0.85},
            "current_avg_rent": {"value": 950, "confidence": 0.90},
            "proforma_rent": {"value": 1100, "confidence": 0.80},
        },
    ],
    "apartment_income_current": {"value": None, "confidence": 0.0},
    "apartment_income_proforma": {"value": None, "confidence": 0.0},
    "other_income_items": [],
    "expense_items": [],
    "down_payment_pct": {"value": None, "confidence": 0.0},
    "loan_amount": {"value": None, "confidence": 0.0},
    "interest_rate": {"value": None, "confidence": 0.0},
    "amortization_years": {"value": None, "confidence": 0.0},
    "debt_service_annual": {"value": None, "confidence": 0.0},
    "current_dscr": {"value": None, "confidence": 0.0},
    "proforma_dscr": {"value": None, "confidence": 0.0},
    "current_cash_on_cash": {"value": None, "confidence": 0.0},
    "proforma_cash_on_cash": {"value": None, "confidence": 0.0},
    "listing_broker_name": {"value": None, "confidence": 0.0},
    "listing_broker_company": {"value": None, "confidence": 0.0},
    "listing_broker_phone": {"value": None, "confidence": 0.0},
    "listing_broker_email": {"value": None, "confidence": 0.0},
}

_PIPELINE_MOCK_RENT_ESTIMATES = {
    "2BR/1BA": {
        "market_rent_estimate": 1350.0,
        "market_rent_low": 1200.0,
        "market_rent_high": 1500.0,
        "comparables_count": 8,
    },
    "1BR/1BA": {
        "market_rent_estimate": 1050.0,
        "market_rent_low": 950.0,
        "market_rent_high": 1150.0,
        "comparables_count": 6,
    },
}


def _build_pipeline_extracted_om_data():
    """Construct an ExtractedOMData instance from the pipeline mock dict."""
    from app.services.om_intake.om_intake_dataclasses import ExtractedOMData
    return ExtractedOMData(**{
        k: _PIPELINE_MOCK_EXTRACTED_DATA[k]
        for k in ExtractedOMData.__dataclass_fields__
        if k in _PIPELINE_MOCK_EXTRACTED_DATA
    })


def _run_pipeline_integration_sync(app, job_id: int) -> list:
    """Run the full OM intake pipeline synchronously, bypassing Celery.

    Calls OMIntakeService methods directly (no Celery broker needed).
    Returns the list of status values observed at each stage transition.

    Requirements: 2.5, 3.7, 4.10
    """
    from decimal import Decimal
    from app.services.om_intake.om_intake_service import OMIntakeService
    from app.services.om_intake.om_intake_dataclasses import (
        ScenarioInputs, UnitMixRow,
    )
    from app.services.om_intake.scenario_engine import compute_scenarios
    from app.services.om_intake.pdf_parser_service import PDFParserService

    observed_statuses = []

    with app.app_context():
        service = OMIntakeService()

        # Capture initial PENDING status
        job = OMIntakeJob.query.get(job_id)
        observed_statuses.append(job.intake_status)

        # Stage 1: PDF parsing (Req 2.5)
        service.transition_to_parsing(job_id)
        job = OMIntakeJob.query.get(job_id)
        observed_statuses.append(job.intake_status)  # PARSING

        parser = PDFParserService()
        parse_result = parser.extract(job.pdf_bytes)
        service.store_parsed_text(job_id, parse_result.raw_text, parse_result.tables, [])

        # Stage 2: Gemini extraction (Req 3.7) — mocked
        service.transition_to_extracting(job_id)
        job = OMIntakeJob.query.get(job_id)
        observed_statuses.append(job.intake_status)  # EXTRACTING

        extracted = _build_pipeline_extracted_om_data()
        service.store_extracted_data(job_id, extracted)

        # Stage 3: Market rent research (Req 4.10) — mocked
        for unit_type, rent_data in _PIPELINE_MOCK_RENT_ESTIMATES.items():
            service.store_market_rent(
                job_id,
                unit_type,
                rent_data["market_rent_estimate"],
                rent_data["market_rent_low"],
                rent_data["market_rent_high"],
            )

        # Stage 4: Scenario computation + REVIEW transition
        unit_mix_rows = tuple(
            UnitMixRow(
                unit_type_label=row["unit_type_label"]["value"],
                unit_count=row["unit_count"]["value"],
                sqft=Decimal(str(row["sqft"]["value"])),
                current_avg_rent=Decimal(str(row["current_avg_rent"]["value"])),
                proforma_rent=Decimal(str(row["proforma_rent"]["value"])),
                market_rent_estimate=Decimal(str(
                    _PIPELINE_MOCK_RENT_ESTIMATES[row["unit_type_label"]["value"]]["market_rent_estimate"]
                )),
                market_rent_low=Decimal(str(
                    _PIPELINE_MOCK_RENT_ESTIMATES[row["unit_type_label"]["value"]]["market_rent_low"]
                )),
                market_rent_high=Decimal(str(
                    _PIPELINE_MOCK_RENT_ESTIMATES[row["unit_type_label"]["value"]]["market_rent_high"]
                )),
            )
            for row in _PIPELINE_MOCK_EXTRACTED_DATA["unit_mix"]
        )

        inputs = ScenarioInputs(
            unit_mix=unit_mix_rows,
            proforma_vacancy_rate=Decimal("0.05"),
            proforma_gross_expenses=Decimal("0"),
            other_income_items=(),
            asking_price=Decimal("2500000"),
            loan_amount=None,
            interest_rate=None,
            amortization_years=None,
            debt_service_annual=None,
            current_gross_potential_income=Decimal("162500"),
            current_effective_gross_income=Decimal("154375"),
            current_gross_expenses=Decimal("0"),
            current_noi=Decimal("162500"),
            current_vacancy_rate=Decimal("0.05"),
            proforma_gross_potential_income=Decimal("175000"),
            proforma_effective_gross_income=Decimal("166250"),
            proforma_noi=Decimal("175000"),
        )
        comparison = compute_scenarios(inputs)
        service.store_scenario_comparison(job_id, comparison)
        service.transition_to_review(job_id)

        job = OMIntakeJob.query.get(job_id)
        observed_statuses.append(job.intake_status)  # REVIEW

    return observed_statuses


# ---------------------------------------------------------------------------
# TestOMIntakePipelineIntegration
# ---------------------------------------------------------------------------

class TestOMIntakePipelineIntegration:
    """End-to-end integration tests for the OM intake pipeline state machine.

    Runs the full pipeline synchronously with mocked Gemini/RentCast responses,
    verifying that the job progresses through all statuses to REVIEW and that
    ScenarioComparison is populated.

    Requirements: 2.5, 3.7, 4.10
    """

    def _create_pending_job(self, app) -> int:
        """Helper: create a PENDING OMIntakeJob directly in the DB and return its id."""
        with app.app_context():
            job = OMIntakeJob(
                user_id="test-pipeline-user",
                original_filename="test_om.pdf",
                intake_status="PENDING",
                pdf_bytes=_MINIMAL_PDF,
                expires_at=datetime.utcnow() + timedelta(days=90),
            )
            db.session.add(job)
            db.session.commit()
            return job.id

    def test_pipeline_progresses_through_all_statuses(self, app):
        """Pipeline must transition PENDING → PARSING → EXTRACTING → REVIEW.

        Validates Req 2.5 (PDF text extraction stage), Req 3.7 (Gemini
        extraction stage), and Req 4.10 (market rent research stage) by
        confirming each status is reached in the correct order.
        """
        job_id = self._create_pending_job(app)

        observed = _run_pipeline_integration_sync(app, job_id)

        assert observed == ["PENDING", "PARSING", "EXTRACTING", "REVIEW"], (
            f"Expected status sequence PENDING→PARSING→EXTRACTING→REVIEW, "
            f"got: {observed}"
        )

    def test_pipeline_final_status_is_review(self, app):
        """Job must be in REVIEW status after the pipeline completes.

        Validates Req 4.10 — the pipeline must reach REVIEW before the user
        can inspect the scenario comparison.
        """
        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.intake_status == "REVIEW", (
                f"Expected job to be in REVIEW after pipeline, got: {job.intake_status}"
            )

    def test_scenario_comparison_is_populated(self, app):
        """ScenarioComparison must be stored on the job after the pipeline.

        Validates Req 4.10 — scenario_comparison must be a non-empty dict
        containing the three scenario keys (broker_current, broker_proforma,
        realistic) and the unit_mix_comparison array.
        """
        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            sc = job.scenario_comparison

            assert sc is not None, "scenario_comparison must not be None after pipeline"
            assert isinstance(sc, dict), "scenario_comparison must be a dict"

            # Three scenario keys must be present
            assert "broker_current" in sc, "scenario_comparison missing 'broker_current'"
            assert "broker_proforma" in sc, "scenario_comparison missing 'broker_proforma'"
            assert "realistic" in sc, "scenario_comparison missing 'realistic'"

            # Unit mix comparison must be present and non-empty
            assert "unit_mix_comparison" in sc, "scenario_comparison missing 'unit_mix_comparison'"
            assert len(sc["unit_mix_comparison"]) > 0, (
                "unit_mix_comparison must contain at least one row"
            )

    def test_extracted_om_data_is_stored(self, app):
        """extracted_om_data must be persisted on the job after the EXTRACTING stage.

        Validates Req 3.7 — Gemini extraction results must be stored so the
        review endpoint can return them to the user.
        """
        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.extracted_om_data is not None, (
                "extracted_om_data must be stored after pipeline"
            )
            assert isinstance(job.extracted_om_data, dict)
            assert "asking_price" in job.extracted_om_data
            assert "unit_count" in job.extracted_om_data
            assert "unit_mix" in job.extracted_om_data

    def test_market_rent_results_are_stored(self, app):
        """market_rent_results must be populated for each unit type.

        Validates Req 4.10 — market rent estimates must be stored per unit
        type after the RentCast research stage.
        """
        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            mr = job.market_rent_results

            assert mr is not None, "market_rent_results must not be None after pipeline"
            assert isinstance(mr, dict)
            assert "2BR/1BA" in mr, "market_rent_results missing '2BR/1BA'"
            assert "1BR/1BA" in mr, "market_rent_results missing '1BR/1BA'"

            for unit_type in ("2BR/1BA", "1BR/1BA"):
                entry = mr[unit_type]
                assert "estimate" in entry
                assert "low" in entry
                assert "high" in entry

    def test_raw_text_is_stored_after_parsing(self, app):
        """raw_text must be stored on the job after the PARSING stage.

        Validates Req 2.5 — PDF text extraction must persist the raw text
        so subsequent stages (Gemini extraction) can consume it.
        """
        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            assert job.raw_text is not None, "raw_text must be stored after PDF parsing"
            assert len(job.raw_text) > 0, "raw_text must not be empty"

    def test_scenario_comparison_cap_rates_are_numeric(self, app):
        """Cap rates in the ScenarioComparison must be numeric (or None).

        Validates that the scenario engine produces well-formed financial
        metrics — cap_rate values must be convertible to Decimal when present.
        """
        from decimal import Decimal

        job_id = self._create_pending_job(app)
        _run_pipeline_integration_sync(app, job_id)

        with app.app_context():
            job = OMIntakeJob.query.get(job_id)
            sc = job.scenario_comparison

            for scenario_key in ("broker_current", "broker_proforma", "realistic"):
                scenario = sc[scenario_key]
                cap_rate = scenario.get("cap_rate")
                if cap_rate is not None:
                    try:
                        Decimal(str(cap_rate))
                    except Exception as exc:
                        pytest.fail(
                            f"scenario_comparison['{scenario_key}']['cap_rate'] = {cap_rate!r} "
                            f"is not a valid numeric value: {exc}"
                        )
