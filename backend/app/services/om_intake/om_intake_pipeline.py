"""
OM Intake pipeline execution logic — side-effect-free module.

This module contains the pipeline body that runs the three stages of OM intake
processing (PDF parsing, Gemini extraction, market rent + scenario computation).
It has no Celery or worker bootstrap imports, so it can be safely imported from
both the Celery worker and the web-request sync fallback path without triggering
worker side effects.

Called by:
  - celery_worker.process_om_intake_pipeline  (pushes its own app context first)
  - OMIntakeService.create_job sync fallback   (reuses the existing request context)
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_unit_type(label: str) -> tuple[int | None, float | None]:
    """Parse beds and baths from a unit type label like '2BR/1BA' or 'Studio'.

    Returns (beds, baths) as integers/floats, or (None, None) if unparseable.
    """
    label_upper = label.upper()
    beds_match = re.search(r'(\d+)\s*BR', label_upper)
    baths_match = re.search(r'(\d+(?:\.\d+)?)\s*BA', label_upper)
    beds = int(beds_match.group(1)) if beds_match else None
    baths = float(baths_match.group(1)) if baths_match else None
    if 'STUDIO' in label_upper:
        beds = 0
    return beds, baths


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _get_field_value(field_dict: Any) -> Any:
    if isinstance(field_dict, dict):
        return field_dict.get("value")
    return None


def _get_decimal_field(data_dict: dict, field_name: str) -> Decimal | None:
    return _to_decimal(_get_field_value(data_dict.get(field_name)))


def _get_int_field(data_dict: dict, field_name: str) -> int | None:
    raw = _get_field_value(data_dict.get(field_name))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pipeline body
# ---------------------------------------------------------------------------


def run_om_intake_pipeline_body(job_id: int, pdf_b64: str | None = None) -> None:
    """Execute the OM intake pipeline stages within the caller's active app context.

    The caller is responsible for ensuring an active Flask app context is already
    pushed before calling this function.  No new app context is created here.

    Stages:
      1. PDF text/table extraction
      2. Gemini field extraction
      3. Market rent research + scenario computation

    On any unhandled exception the job is transitioned to FAILED and the
    exception is re-raised so the caller (Celery task or sync fallback) can
    handle it appropriately.

    Args:
        job_id: The OMIntakeJob primary key.
        pdf_b64: Base64-encoded PDF bytes, or None to fall back to the DB column
                 (legacy path for jobs created before the no-store change).
    """
    import base64

    from app import db
    from app.models import OMIntakeJob
    from app.services.om_intake.om_intake_service import OMIntakeService

    service = OMIntakeService()

    try:
        # ----------------------------------------------------------
        # Stage 1: PDF parsing
        # ----------------------------------------------------------
        from app.services.om_intake.pdf_parser_service import PDFParserService

        service.transition_to_parsing(job_id)

        if pdf_b64:
            pdf_bytes = base64.b64decode(pdf_b64)
        else:
            job = OMIntakeJob.query.get(job_id)
            if job is None:
                logger.error("run_om_intake_pipeline_body: job_id=%d not found", job_id)
                raise ValueError(f"OMIntakeJob {job_id} not found — cannot process pipeline")
            pdf_bytes = job.pdf_bytes
            if not pdf_bytes:
                service.transition_to_failed(job_id, "No PDF data available for processing.")
                return

        parser = PDFParserService()
        parse_result = parser.extract(pdf_bytes)
        del pdf_bytes

        service.store_parsed_text(
            job_id,
            parse_result.raw_text,
            parse_result.tables,
            [parse_result.table_extraction_warning] if parse_result.table_extraction_warning else [],
        )
        service.transition_to_extracting(job_id)
        logger.info("run_om_intake_pipeline_body: job_id=%d PDF parsed, text_length=%d",
                    job_id, len(parse_result.raw_text))

        # ----------------------------------------------------------
        # Stage 2: Gemini field extraction
        # ----------------------------------------------------------
        from app.services.om_intake.gemini_om_extractor_service import GeminiOMExtractorService

        job = OMIntakeJob.query.get(job_id)
        extractor = GeminiOMExtractorService()
        extracted_data = extractor.extract(job.raw_text, job.tables_json or [])
        service.store_extracted_data(job_id, extracted_data)
        logger.info("run_om_intake_pipeline_body: job_id=%d Gemini extraction complete, unit_mix_rows=%d",
                    job_id, len(extracted_data.unit_mix))

        # ----------------------------------------------------------
        # Stage 3: Market rent research + scenario computation
        # ----------------------------------------------------------
        from app.services.om_intake.rentcast_service import RentCastService
        from app.services.om_intake.om_intake_dataclasses import OtherIncomeItem, ScenarioInputs, UnitMixRow
        from app.services.om_intake.scenario_engine import compute_scenarios

        job = OMIntakeJob.query.get(job_id)
        extracted = job.extracted_om_data or {}

        property_address_raw = _get_field_value(extracted.get("property_address"))
        property_city = _get_field_value(extracted.get("property_city"))
        property_state = _get_field_value(extracted.get("property_state"))
        property_zip = _get_field_value(extracted.get("property_zip"))
        unit_mix_raw = extracted.get("unit_mix") or []

        address_parts = [p for p in [property_address_raw, property_city, property_state, property_zip] if p]
        full_address = ", ".join(address_parts) if address_parts else None

        seen_unit_types: dict[str, dict] = {}
        for row in unit_mix_raw:
            if not isinstance(row, dict):
                continue
            label_field = row.get("unit_type_label", {})
            label = _get_field_value(label_field) if isinstance(label_field, dict) else label_field
            if label and label not in seen_unit_types:
                seen_unit_types[label] = row

        market_rent_results: dict[str, dict] = {}
        market_research_warnings: list[dict] = []

        try:
            rent_service = RentCastService()
        except Exception as exc:
            logger.warning("run_om_intake_pipeline_body: RentCastService unavailable: %s", exc)
            rent_service = None

        for unit_type_label, row_data in seen_unit_types.items():
            sqft_field = row_data.get("sqft", {})
            sqft_raw = sqft_field.get("value") if isinstance(sqft_field, dict) else sqft_field
            sqft_int = int(float(sqft_raw)) if sqft_raw is not None else None

            beds, baths = _parse_unit_type(unit_type_label)

            if rent_service is None or full_address is None:
                market_research_warnings.append({"unit_type": unit_type_label, "warning": "RentCast unavailable or no address"})
                market_rent_results[unit_type_label] = {"estimate": None, "low": None, "high": None}
                service.store_market_rent(job_id, unit_type_label, None, None, None)
                continue

            try:
                result = rent_service.get_rent_estimate(
                    address=full_address,
                    property_type="Multi-Family",
                    bedrooms=beds,
                    bathrooms=baths,
                    square_footage=sqft_int,
                    unit_type_label=unit_type_label,
                )
                estimate = result.get("market_rent_estimate")
                low = result.get("market_rent_low")
                high = result.get("market_rent_high")
                market_rent_results[unit_type_label] = {"estimate": estimate, "low": low, "high": high}
                service.store_market_rent(job_id, unit_type_label, estimate, low, high)
                logger.info("run_om_intake_pipeline_body: RentCast '%s' estimate=%s", unit_type_label, estimate)
            except Exception as exc:
                logger.warning("run_om_intake_pipeline_body: RentCast failed for '%s': %s", unit_type_label, exc)
                market_research_warnings.append({"unit_type": unit_type_label, "warning": str(exc)})
                market_rent_results[unit_type_label] = {"estimate": None, "low": None, "high": None}
                service.store_market_rent(job_id, unit_type_label, None, None, None)

        if market_research_warnings:
            _job = OMIntakeJob.query.get(job_id)
            if _job is not None:
                _job.market_research_warnings = market_research_warnings
                db.session.commit()

        # Build unit mix rows
        unit_mix_rows = []
        for row in unit_mix_raw:
            if not isinstance(row, dict):
                continue
            label_field = row.get("unit_type_label", {})
            label = label_field.get("value") if isinstance(label_field, dict) else label_field
            if not label:
                continue
            uc_field = row.get("unit_count", {})
            uc_raw = uc_field.get("value") if isinstance(uc_field, dict) else uc_field
            try:
                unit_count = int(uc_raw) if uc_raw is not None else 0
            except (TypeError, ValueError):
                unit_count = 0
            sqft_field = row.get("sqft", {})
            sqft_raw2 = sqft_field.get("value") if isinstance(sqft_field, dict) else sqft_field
            sqft = _to_decimal(sqft_raw2) or Decimal("0")
            car_field = row.get("current_avg_rent", {})
            car_raw = car_field.get("value") if isinstance(car_field, dict) else car_field
            pr_field = row.get("proforma_rent", {})
            pr_raw = pr_field.get("value") if isinstance(pr_field, dict) else pr_field
            mr = market_rent_results.get(label, {})
            unit_mix_rows.append(UnitMixRow(
                unit_type_label=label,
                unit_count=unit_count,
                sqft=sqft,
                current_avg_rent=_to_decimal(car_raw),
                proforma_rent=_to_decimal(pr_raw),
                market_rent_estimate=_to_decimal(mr.get("estimate")),
                market_rent_low=_to_decimal(mr.get("low")),
                market_rent_high=_to_decimal(mr.get("high")),
            ))

        # Build other income items
        other_income_items = []
        for item in (extracted.get("other_income_items") or []):
            if not isinstance(item, dict):
                continue
            label_field = item.get("label", {})
            label = label_field.get("value") or "" if isinstance(label_field, dict) else str(label_field or "")
            amount_field = item.get("annual_amount", {})
            amount_raw = amount_field.get("value") if isinstance(amount_field, dict) else amount_field
            amount = _to_decimal(amount_raw)
            if amount is not None:
                other_income_items.append(OtherIncomeItem(label=label, annual_amount=amount))

        any_estimate_missing = any(r.market_rent_estimate is None for r in unit_mix_rows)
        _job2 = OMIntakeJob.query.get(job_id)
        if _job2 is not None:
            _job2.partial_realistic_scenario_warning = any_estimate_missing
            db.session.commit()

        proforma_vacancy_raw = _get_decimal_field(extracted, "proforma_vacancy_rate")
        proforma_vacancy_rate = proforma_vacancy_raw if proforma_vacancy_raw is not None else Decimal("0.05")

        inputs = ScenarioInputs(
            unit_mix=tuple(unit_mix_rows),
            proforma_vacancy_rate=proforma_vacancy_rate,
            proforma_gross_expenses=_get_decimal_field(extracted, "proforma_gross_expenses"),
            other_income_items=tuple(other_income_items),
            asking_price=_get_decimal_field(extracted, "asking_price"),
            loan_amount=_get_decimal_field(extracted, "loan_amount"),
            interest_rate=_get_decimal_field(extracted, "interest_rate"),
            amortization_years=_get_int_field(extracted, "amortization_years"),
            debt_service_annual=_get_decimal_field(extracted, "debt_service_annual"),
            current_gross_potential_income=_get_decimal_field(extracted, "current_gross_potential_income"),
            current_effective_gross_income=_get_decimal_field(extracted, "current_effective_gross_income"),
            current_gross_expenses=_get_decimal_field(extracted, "current_gross_expenses"),
            current_noi=_get_decimal_field(extracted, "current_noi"),
            current_vacancy_rate=_get_decimal_field(extracted, "current_vacancy_rate"),
            proforma_gross_potential_income=_get_decimal_field(extracted, "proforma_gross_potential_income"),
            proforma_effective_gross_income=_get_decimal_field(extracted, "proforma_effective_gross_income"),
            proforma_noi=_get_decimal_field(extracted, "proforma_noi"),
        )

        comparison = compute_scenarios(inputs)
        service.store_scenario_comparison(job_id, comparison)
        service.transition_to_review(job_id)
        logger.info("run_om_intake_pipeline_body: job_id=%d complete → REVIEW", job_id)

    except Exception as exc:
        logger.error("run_om_intake_pipeline_body: job_id=%d failed: %s", job_id, exc, exc_info=True)
        try:
            service.transition_to_failed(job_id, str(exc))
        except Exception:
            logger.exception("run_om_intake_pipeline_body: could not transition job_id=%d to FAILED", job_id)
        raise
