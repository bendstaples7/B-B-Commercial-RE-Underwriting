"""
OM Intake pipeline logic — pure functions called by Celery task wrappers.

This module contains NO Celery decorators. All @celery.task decorators
live in celery_worker.py where the ``celery`` app instance is guaranteed
to exist. This separation means this module can be imported safely in any
context (tests, Flask app, worker subprocesses) without needing a Celery
app instance.

The three entry points are:
  run_parse_om_pdf(job_id)         — called by parse_om_pdf_task
  run_extract_om_fields(job_id)    — called by extract_om_fields_task
  run_research_market_rents(job_id) — called by research_market_rents_task

Requirements: 2.5, 3.7, 4.1, 4.2, 4.9, 4.10, 9.1, 9.2, 9.4, 9.5
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    raw = _get_field_value(data_dict.get(field_name))
    return _to_decimal(raw)


def _get_int_field(data_dict: dict, field_name: str) -> int | None:
    raw = _get_field_value(data_dict.get(field_name))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stage 1: PDF parsing
# ---------------------------------------------------------------------------

def run_parse_om_pdf(job_id: int) -> None:
    """Parse the PDF bytes stored on an OMIntakeJob and enqueue field extraction."""
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.models import OMIntakeJob
        from app.services.om_intake.om_intake_service import OMIntakeService
        from app.services.om_intake.pdf_parser_service import PDFParserService

        service = OMIntakeService()
        try:
            service.transition_to_parsing(job_id)

            job = OMIntakeJob.query.get(job_id)
            if job is None:
                logger.error("run_parse_om_pdf: job_id=%d not found", job_id)
                return

            parser = PDFParserService()
            result = parser.extract(job.pdf_bytes)

            service.store_parsed_text(
                job_id,
                result.raw_text,
                result.tables,
                [result.table_extraction_warning] if result.table_extraction_warning else [],
            )
            service.transition_to_extracting(job_id)

            # Use the current Celery app (bound in the worker context) to enqueue
            from celery import current_app as _celery
            _celery.send_task('om_intake.extract_fields', args=[job_id])

            logger.info(
                "run_parse_om_pdf: job_id=%d parsed, text_length=%d, tables=%d",
                job_id, len(result.raw_text), len(result.tables),
            )

        except Exception as exc:
            logger.error("run_parse_om_pdf: job_id=%d failed: %s", job_id, exc, exc_info=True)
            try:
                service.transition_to_failed(job_id, str(exc))
            except Exception:
                logger.exception("run_parse_om_pdf: could not transition job_id=%d to FAILED", job_id)
            raise


# ---------------------------------------------------------------------------
# Stage 2: Gemini field extraction
# ---------------------------------------------------------------------------

def run_extract_om_fields(job_id: int) -> None:
    """Extract structured OM fields from raw text using Gemini."""
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    from app.exceptions import GeminiAPIError

    app = create_app()
    with app.app_context():
        from app.models import OMIntakeJob
        from app.services.om_intake.gemini_om_extractor_service import GeminiOMExtractorService
        from app.services.om_intake.om_intake_service import OMIntakeService

        service = OMIntakeService()
        try:
            job = OMIntakeJob.query.get(job_id)
            if job is None:
                logger.error("run_extract_om_fields: job_id=%d not found", job_id)
                return

            extractor = GeminiOMExtractorService()
            data = extractor.extract(job.raw_text, job.tables_json or [])
            service.store_extracted_data(job_id, data)

            from celery import current_app as _celery
            _celery.send_task('om_intake.research_market_rents', args=[job_id])

            logger.info(
                "run_extract_om_fields: job_id=%d complete, unit_mix_rows=%d",
                job_id, len(data.unit_mix),
            )

        except GeminiAPIError:
            raise  # Let Celery autoretry handle this
        except Exception as exc:
            logger.error("run_extract_om_fields: job_id=%d failed: %s", job_id, exc, exc_info=True)
            try:
                service.transition_to_failed(job_id, str(exc))
            except Exception:
                logger.exception("run_extract_om_fields: could not transition job_id=%d to FAILED", job_id)
            raise


# ---------------------------------------------------------------------------
# Stage 3: Market rent research + scenario computation
# ---------------------------------------------------------------------------

def run_research_market_rents(job_id: int) -> None:
    """Research market rents per unit type, compute scenarios, transition to REVIEW."""
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    from app.exceptions import GeminiAPIError

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import OMIntakeJob
        from app.services.om_intake.gemini_comparable_search_service import GeminiComparableSearchService
        from app.services.om_intake.om_intake_dataclasses import OtherIncomeItem, ScenarioInputs, UnitMixRow
        from app.services.om_intake.om_intake_service import OMIntakeService
        from app.services.om_intake.scenario_engine import compute_scenarios

        service = OMIntakeService()
        try:
            job = OMIntakeJob.query.get(job_id)
            if job is None:
                logger.error("run_research_market_rents: job_id=%d not found", job_id)
                return

            extracted = job.extracted_om_data or {}
            property_city = _get_field_value(extracted.get("property_city"))
            property_state = _get_field_value(extracted.get("property_state"))
            neighborhood = _get_field_value(extracted.get("neighborhood"))
            unit_mix_raw = extracted.get("unit_mix") or []

            # Collect distinct unit types
            seen_unit_types: dict[str, dict] = {}
            for row in unit_mix_raw:
                if not isinstance(row, dict):
                    continue
                label_field = row.get("unit_type_label", {})
                label = _get_field_value(label_field) if isinstance(label_field, dict) else label_field
                if label and label not in seen_unit_types:
                    seen_unit_types[label] = row

            # Research market rents
            market_rent_results: dict[str, dict] = {}
            market_research_warnings: list[dict] = []

            try:
                comparable_service = GeminiComparableSearchService()
            except Exception as exc:
                logger.warning("run_research_market_rents: GeminiComparableSearchService unavailable: %s", exc)
                comparable_service = None

            for unit_type_label, row_data in seen_unit_types.items():
                sqft_raw = _get_field_value(
                    row_data.get("sqft", {}) if isinstance(row_data.get("sqft"), dict)
                    else {"value": row_data.get("sqft")}
                )
                sqft_float = float(sqft_raw) if sqft_raw is not None else None

                if comparable_service is None:
                    market_research_warnings.append({"unit_type": unit_type_label, "warning": "GeminiComparableSearchService unavailable"})
                    market_rent_results[unit_type_label] = {"estimate": None, "low": None, "high": None}
                    service.store_market_rent(job_id, unit_type_label, None, None, None)
                    continue

                try:
                    result = comparable_service.search_comparable_rents(
                        property_city=property_city,
                        property_state=property_state,
                        neighborhood=neighborhood,
                        unit_type_label=unit_type_label,
                        sqft=sqft_float,
                    )
                    estimate = result.get("market_rent_estimate")
                    low = result.get("market_rent_low")
                    high = result.get("market_rent_high")
                    market_rent_results[unit_type_label] = {"estimate": estimate, "low": low, "high": high}
                    service.store_market_rent(job_id, unit_type_label, estimate, low, high)
                    logger.info("run_research_market_rents: job_id=%d unit_type='%s' estimate=%s", job_id, unit_type_label, estimate)

                except GeminiAPIError:
                    raise
                except Exception as exc:
                    logger.warning("run_research_market_rents: job_id=%d unit_type='%s' failed: %s", job_id, unit_type_label, exc)
                    market_research_warnings.append({"unit_type": unit_type_label, "warning": str(exc)})
                    market_rent_results[unit_type_label] = {"estimate": None, "low": None, "high": None}
                    service.store_market_rent(job_id, unit_type_label, None, None, None)

            if market_research_warnings:
                _job = OMIntakeJob.query.get(job_id)
                if _job is not None:
                    _job.market_research_warnings = market_research_warnings
                    db.session.commit()

            # Build ScenarioInputs
            unit_mix_rows = _build_unit_mix_rows(unit_mix_raw, market_rent_results)
            other_income_items = _build_other_income_items(extracted)

            any_estimate_missing = any(row.market_rent_estimate is None for row in unit_mix_rows)
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
            logger.info("run_research_market_rents: job_id=%d complete, transitioned to REVIEW", job_id)

        except GeminiAPIError:
            raise
        except Exception as exc:
            logger.error("run_research_market_rents: job_id=%d failed: %s", job_id, exc, exc_info=True)
            try:
                service.transition_to_failed(job_id, str(exc))
            except Exception:
                logger.exception("run_research_market_rents: could not transition job_id=%d to FAILED", job_id)
            raise


# ---------------------------------------------------------------------------
# Helpers for building ScenarioInputs
# ---------------------------------------------------------------------------

def _build_unit_mix_rows(unit_mix_raw: list, market_rent_results: dict[str, dict]) -> list:
    from app.services.om_intake.om_intake_dataclasses import UnitMixRow
    rows = []
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
        sqft_raw = sqft_field.get("value") if isinstance(sqft_field, dict) else sqft_field
        sqft = _to_decimal(sqft_raw) or Decimal("0")
        car_field = row.get("current_avg_rent", {})
        car_raw = car_field.get("value") if isinstance(car_field, dict) else car_field
        current_avg_rent = _to_decimal(car_raw)
        pr_field = row.get("proforma_rent", {})
        pr_raw = pr_field.get("value") if isinstance(pr_field, dict) else pr_field
        proforma_rent = _to_decimal(pr_raw)
        mr = market_rent_results.get(label, {})
        rows.append(UnitMixRow(
            unit_type_label=label,
            unit_count=unit_count,
            sqft=sqft,
            current_avg_rent=current_avg_rent,
            proforma_rent=proforma_rent,
            market_rent_estimate=_to_decimal(mr.get("estimate")),
            market_rent_low=_to_decimal(mr.get("low")),
            market_rent_high=_to_decimal(mr.get("high")),
        ))
    return rows


def _build_other_income_items(extracted: dict) -> list:
    from app.services.om_intake.om_intake_dataclasses import OtherIncomeItem
    items = []
    for item in (extracted.get("other_income_items") or []):
        if not isinstance(item, dict):
            continue
        label_field = item.get("label", {})
        label = label_field.get("value") or "" if isinstance(label_field, dict) else str(label_field or "")
        amount_field = item.get("annual_amount", {})
        amount_raw = amount_field.get("value") if isinstance(amount_field, dict) else amount_field
        amount = _to_decimal(amount_raw)
        if amount is not None:
            items.append(OtherIncomeItem(label=label, annual_amount=amount))
    return items
