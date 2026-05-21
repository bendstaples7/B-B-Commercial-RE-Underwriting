"""
Full-flow integration test for the Commercial OM PDF Intake feature.

Tests the complete user journey with mocked external services (Gemini, RentCast):
  1. Upload PDF → job created (PENDING)
  2. Run pipeline synchronously (bypassing Celery) → job reaches REVIEW
  3. GET /review → returns ExtractedOMData and ScenarioComparison
  4. POST /confirm → Deal created, job transitions to CONFIRMED
  5. GET /deals/{id} → Deal exists with correct fields

This test runs in pytest without a live server, Celery, or Redis.
It catches endpoint-level failures (schema validation, missing fields, etc.)
that would only surface when a user actually clicks through the full flow.

Requirements: 1.1, 1.2, 5.1, 7.1, 7.9, 8.4, 11.1
"""
import io
import json
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app import db
from app.models import OMIntakeJob, Deal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = '/api/om-intake'
USER_HEADERS = {'X-User-Id': 'test-user-flow'}

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

# Fixture: what GeminiOMExtractorService.extract returns
_MOCK_EXTRACTED_DATA = {
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

# Fixture: what RentCastService.get_rent_estimate returns per unit type
_MOCK_RENT_ESTIMATES = {
    "2BR/1BA": {"market_rent_estimate": 1350.0, "market_rent_low": 1200.0, "market_rent_high": 1500.0, "comparables_count": 8},
    "1BR/1BA": {"market_rent_estimate": 1050.0, "market_rent_low": 950.0, "market_rent_high": 1150.0, "comparables_count": 6},
}


def _upload(client):
    data = io.BytesIO(_MINIMAL_PDF)
    return client.post(
        f'{BASE}/jobs',
        data={'file': (data, 'test_om.pdf', 'application/pdf')},
        content_type='multipart/form-data',
        headers=USER_HEADERS,
    )


def _get(client, path):
    return client.get(f'{BASE}{path}', headers=USER_HEADERS)


def _post(client, path, payload):
    return client.post(
        f'{BASE}{path}',
        data=json.dumps(payload),
        content_type='application/json',
        headers=USER_HEADERS,
    )


def _run_pipeline_sync(app, job_id):
    """Run the full OM intake pipeline synchronously, bypassing Celery.

    Mocks Gemini and RentCast so no external API calls are made.
    """
    from app.services.om_intake.om_intake_service import OMIntakeService
    from app.services.om_intake.om_intake_dataclasses import ExtractedOMData
    from app.services.om_intake.scenario_engine import compute_scenarios
    from app.services.om_intake.pdf_parser_service import PDFParserService

    with app.app_context():
        service = OMIntakeService()

        # Stage 1: PDF parsing (real — uses the actual PDF parser)
        service.transition_to_parsing(job_id)
        job = OMIntakeJob.query.get(job_id)
        parser = PDFParserService()
        parse_result = parser.extract(job.pdf_bytes)
        service.store_parsed_text(job_id, parse_result.raw_text, parse_result.tables, [])
        service.transition_to_extracting(job_id)

        # Stage 2: Gemini extraction (mocked)
        import dataclasses
        from app.services.om_intake.om_intake_dataclasses import (
            UnitMixRow, OtherIncomeItem, ScenarioInputs
        )

        # Build ExtractedOMData from the mock dict
        from app.services.om_intake.om_intake_dataclasses import ExtractedOMData
        extracted = ExtractedOMData(**{
            k: _MOCK_EXTRACTED_DATA[k]
            for k in ExtractedOMData.__dataclass_fields__
            if k in _MOCK_EXTRACTED_DATA
        })
        service.store_extracted_data(job_id, extracted)

        # Stage 3: Market rents (mocked RentCast)
        for unit_type, rent_data in _MOCK_RENT_ESTIMATES.items():
            service.store_market_rent(
                job_id, unit_type,
                rent_data["market_rent_estimate"],
                rent_data["market_rent_low"],
                rent_data["market_rent_high"],
            )

        # Compute scenarios
        unit_mix_rows = tuple(
            UnitMixRow(
                unit_type_label=row["unit_type_label"]["value"],
                unit_count=row["unit_count"]["value"],
                sqft=Decimal(str(row["sqft"]["value"])),
                current_avg_rent=Decimal(str(row["current_avg_rent"]["value"])),
                proforma_rent=Decimal(str(row["proforma_rent"]["value"])),
                market_rent_estimate=Decimal(str(_MOCK_RENT_ESTIMATES.get(
                    row["unit_type_label"]["value"], {}
                ).get("market_rent_estimate", 0))),
                market_rent_low=Decimal(str(_MOCK_RENT_ESTIMATES.get(
                    row["unit_type_label"]["value"], {}
                ).get("market_rent_low", 0))),
                market_rent_high=Decimal(str(_MOCK_RENT_ESTIMATES.get(
                    row["unit_type_label"]["value"], {}
                ).get("market_rent_high", 0))),
            )
            for row in _MOCK_EXTRACTED_DATA["unit_mix"]
        )

        inputs = ScenarioInputs(
            unit_mix=unit_mix_rows,
            proforma_vacancy_rate=Decimal("0.05"),
            proforma_gross_expenses=Decimal("0"),
            other_income_items=(),
            asking_price=Decimal("2500000"),
            loan_amount=None, interest_rate=None, amortization_years=None,
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOMIntakeFullFlow:
    """Full happy-path flow: upload → pipeline → review → confirm → Deal."""

    def test_full_flow_creates_deal(self, app, client):
        """The complete user journey from PDF upload to Deal creation."""

        # Step 1: Upload PDF
        resp = _upload(client)
        assert resp.status_code == 201, f"Upload failed: {resp.get_json()}"
        body = resp.get_json()
        assert "intake_job_id" in body
        job_id = body["intake_job_id"]

        # Step 2: Run pipeline synchronously with mocked external services
        _run_pipeline_sync(app, job_id)

        # Step 3: GET /review — must return 200 with extracted data
        resp = _get(client, f"/jobs/{job_id}/review")
        assert resp.status_code == 200, f"GET /review failed: {resp.get_json()}"
        review = resp.get_json()
        assert review["intake_status"] == "REVIEW"
        assert review["extracted_om_data"] is not None, "extracted_om_data is missing"
        assert review["scenario_comparison"] is not None, "scenario_comparison is missing"

        # Step 4: POST /confirm — must return 200 with deal_id
        confirmed_data = {
            "asking_price": 2500000,
            "unit_count": 10,
            "unit_mix": [
                {"unit_type_label": "2BR/1BA", "unit_count": 5, "sqft": 850,
                 "current_avg_rent": 1200, "proforma_rent": 1400},
                {"unit_type_label": "1BR/1BA", "unit_count": 5, "sqft": 650,
                 "current_avg_rent": 950, "proforma_rent": 1100},
            ],
            "expense_items": [],
            "other_income_items": [],
        }
        resp = _post(client, f"/jobs/{job_id}/confirm", confirmed_data)
        assert resp.status_code == 200, (
            f"POST /confirm failed with {resp.status_code}: {resp.get_json()}\n"
            f"This is the critical check — if this fails, users cannot complete the flow."
        )
        confirm_body = resp.get_json()
        assert "deal_id" in confirm_body, "confirm response missing deal_id"
        deal_id = confirm_body["deal_id"]
        assert confirm_body["status"] == "CONFIRMED"

        # Step 5: Verify Deal exists in the database
        with app.app_context():
            deal = Deal.query.get(deal_id)
            assert deal is not None, f"Deal {deal_id} not found in database"
            assert deal.purchase_price == Decimal("2500000")
            assert deal.unit_count == 10
            assert deal.property_address == "123 Main St"

        # Step 6: Verify job is CONFIRMED
        resp = _get(client, f"/jobs/{job_id}")
        assert resp.status_code == 200
        job_status = resp.get_json()
        assert job_status["intake_status"] == "CONFIRMED"
        assert job_status["deal_id"] == deal_id

    def test_confirm_rejects_unknown_fields(self, app, client):
        """Confirm endpoint must not fail when user_id is injected by Axios interceptor."""
        # Create a job in REVIEW status directly
        with app.app_context():
            job = OMIntakeJob(
                user_id="test-user-flow",
                original_filename="test.pdf",
                intake_status="REVIEW",
                pdf_bytes=_MINIMAL_PDF,
                extracted_om_data=_MOCK_EXTRACTED_DATA,
                expires_at=datetime.utcnow() + timedelta(days=90),
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        # Simulate Axios interceptor injecting user_id into the body
        payload_with_user_id = {
            "asking_price": 2500000,
            "unit_count": 10,
            "unit_mix": [
                {"unit_type_label": "2BR/1BA", "unit_count": 5, "sqft": 850,
                 "current_avg_rent": 1200, "proforma_rent": 1400},
                {"unit_type_label": "1BR/1BA", "unit_count": 5, "sqft": 650,
                 "current_avg_rent": 950, "proforma_rent": 1100},
            ],
            "expense_items": [],
            "other_income_items": [],
            "user_id": "test-user-flow",  # injected by Axios interceptor
        }

        resp = _post(client, f"/jobs/{job_id}/confirm", payload_with_user_id)
        assert resp.status_code == 200, (
            f"Confirm failed with user_id in body: {resp.status_code} {resp.get_json()}\n"
            "The OMIntakeConfirmRequestSchema must use unknown=EXCLUDE."
        )
