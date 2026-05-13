"""Celery worker configuration.

All task decorators and logic live here, where the ``celery`` app instance
is guaranteed to exist.

Design principles:
  - One task per pipeline (om_intake.process_pipeline) instead of three
    chained tasks — simpler, fewer failure modes, no send_task chaining.
  - time_limit=120 on the pipeline task — Celery hard-kills it after 2
    minutes, freeing the worker regardless of what external APIs do.
  - Startup assertion verifies all expected tasks are registered at boot.
"""
import os

from dotenv import load_dotenv
load_dotenv()

from celery import Celery
from celery.signals import worker_ready

celery = Celery(
    'real_estate_analysis',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# ---------------------------------------------------------------------------
# Existing tasks
# ---------------------------------------------------------------------------

@celery.task(name='lead_scoring.bulk_rescore')
def bulk_rescore_task(user_id: str, lead_ids: list[int] | None = None) -> int:
    from app import create_app
    from app.services.lead_scoring_engine import LeadScoringEngine
    app = create_app()
    with app.app_context():
        engine = LeadScoringEngine()
        return engine.bulk_rescore(user_id, lead_ids)


@celery.task(name='import.process')
def import_task(job_id: int, lead_category: str = 'residential') -> dict:
    from app import create_app
    from app.services.google_sheets_importer import GoogleSheetsImporter
    app = create_app()
    with app.app_context():
        importer_service = GoogleSheetsImporter()
        result = importer_service.process_import(job_id, lead_category=lead_category)
        return {
            'job_id': result.job_id,
            'status': result.status,
            'total_rows': result.total_rows,
            'rows_imported': result.rows_imported,
            'rows_skipped': result.rows_skipped,
        }


@celery.task(name='enrichment.bulk_enrich')
def bulk_enrich_task(lead_ids: list[int], source_name: str) -> int:
    from app import create_app
    from app.services.data_source_connector import DataSourceConnector
    app = create_app()
    with app.app_context():
        connector = DataSourceConnector()
        records = connector.bulk_enrich(lead_ids, source_name)
        return len(records)


@celery.task(name='multifamily.recompute_all_deals')
def multifamily_recompute_all_task() -> int:
    from app.tasks.multifamily_recompute import recompute_all_deals
    return recompute_all_deals()


# ---------------------------------------------------------------------------
# OM Intake — single pipeline task
#
# Runs all three stages (PDF parse → Gemini extract → market rents) in one
# task. time_limit=120 hard-kills the task after 2 minutes so a hung
# external API call can never block the worker permanently.
# ---------------------------------------------------------------------------

def _parse_unit_type(label: str) -> tuple[int | None, float | None]:
    """Parse beds and baths from a unit type label like '2BR/1BA' or 'Studio'.

    Returns (beds, baths) as integers/floats, or (None, None) if unparseable.
    """
    import re
    label_upper = label.upper()
    beds_match = re.search(r'(\d+)\s*BR', label_upper)
    baths_match = re.search(r'(\d+(?:\.\d+)?)\s*BA', label_upper)
    beds = int(beds_match.group(1)) if beds_match else None
    baths = float(baths_match.group(1)) if baths_match else None
    # Studio = 0 beds
    if 'STUDIO' in label_upper:
        beds = 0
    return beds, baths

@celery.task(
    name='om_intake.process_pipeline',
    bind=True,
    max_retries=0,          # no auto-retry — failures transition job to FAILED
    time_limit=120,         # hard kill after 2 minutes (OS-level SIGKILL)
    soft_time_limit=100,    # raises SoftTimeLimitExceeded at 100s for clean shutdown
)
def process_om_intake_pipeline(self, job_id: int) -> None:
    """Run the full OM intake pipeline for a single job.

    Stages:
      1. PDF text/table extraction
      2. Gemini field extraction
      3. Market rent research + scenario computation

    On any unhandled exception the job is transitioned to FAILED.
    The time_limit=120 ensures the worker is never blocked indefinitely.
    """
    import logging
    from decimal import Decimal, InvalidOperation
    from typing import Any

    logger = logging.getLogger(__name__)

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

    from app import create_app
    app = create_app()

    with app.app_context():
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

            job = OMIntakeJob.query.get(job_id)
            if job is None:
                logger.error("process_om_intake_pipeline: job_id=%d not found", job_id)
                return

            parser = PDFParserService()
            parse_result = parser.extract(job.pdf_bytes)

            service.store_parsed_text(
                job_id,
                parse_result.raw_text,
                parse_result.tables,
                [parse_result.table_extraction_warning] if parse_result.table_extraction_warning else [],
            )
            service.transition_to_extracting(job_id)
            logger.info("process_om_intake_pipeline: job_id=%d PDF parsed, text_length=%d",
                        job_id, len(parse_result.raw_text))

            # ----------------------------------------------------------
            # Stage 2: Gemini field extraction
            # ----------------------------------------------------------
            from app.services.om_intake.gemini_om_extractor_service import GeminiOMExtractorService

            # Reload job to get raw_text and tables_json
            job = OMIntakeJob.query.get(job_id)
            extractor = GeminiOMExtractorService()
            extracted_data = extractor.extract(job.raw_text, job.tables_json or [])
            service.store_extracted_data(job_id, extracted_data)
            logger.info("process_om_intake_pipeline: job_id=%d Gemini extraction complete, unit_mix_rows=%d",
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

            # Build full address for RentCast
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
                logger.warning("process_om_intake_pipeline: RentCastService unavailable: %s", exc)
                rent_service = None

            for unit_type_label, row_data in seen_unit_types.items():
                sqft_field = row_data.get("sqft", {})
                sqft_raw = sqft_field.get("value") if isinstance(sqft_field, dict) else sqft_field
                sqft_int = int(float(sqft_raw)) if sqft_raw is not None else None

                # Parse beds/baths from unit_type_label (e.g. "2BR/1BA" → beds=2, baths=1)
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
                    logger.info("process_om_intake_pipeline: RentCast '%s' estimate=%s", unit_type_label, estimate)
                except Exception as exc:
                    logger.warning("process_om_intake_pipeline: RentCast failed for '%s': %s", unit_type_label, exc)
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
            logger.info("process_om_intake_pipeline: job_id=%d complete → REVIEW", job_id)

        except Exception as exc:
            logger.error("process_om_intake_pipeline: job_id=%d failed: %s", job_id, exc, exc_info=True)
            try:
                service.transition_to_failed(job_id, str(exc))
            except Exception:
                logger.exception("process_om_intake_pipeline: could not transition job_id=%d to FAILED", job_id)
            raise


# ---------------------------------------------------------------------------
# AI Comp Fetch — async Celery tasks (Option 2)
#
# These tasks run Gemini in the background so the HTTP request returns
# immediately with a job_id. The frontend polls /fetch-ai/status/:job_id
# until status == 'done' or 'failed'.
#
# Results are stored in the Celery result backend (Redis) with a 1-hour TTL.
# time_limit=180 hard-kills the task if Gemini hangs indefinitely.
# ---------------------------------------------------------------------------

@celery.task(
    name='multifamily.fetch_rent_comps_ai',
    bind=True,
    max_retries=0,
    time_limit=180,
    soft_time_limit=160,
)
def fetch_rent_comps_ai_task(self, deal_id: int, user_id: str) -> dict:
    """Fetch rent comps via Gemini and insert them into the DB.

    Returns a dict with keys: added, skipped, message.
    Raises on failure so Celery marks the task FAILURE.
    """
    import logging
    logger = logging.getLogger(__name__)

    from app import create_app
    app = create_app()

    with app.app_context():
        from app import db
        from app.models.deal import Deal
        from app.models.unit import Unit
        from app.services.multifamily.ai_comp_service import fetch_rent_comps
        from app.services.multifamily.market_rent_service import MarketRentService

        deal = Deal.query.get(deal_id)
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        units = Unit.query.filter_by(deal_id=deal_id).all()
        unit_type_map: dict[str, dict] = {}
        for u in units:
            key = u.unit_type
            if key not in unit_type_map:
                unit_type_map[key] = {'unit_type': key, 'count': 0, 'sqft': u.sqft}
            unit_type_map[key]['count'] += 1
        unit_mix = list(unit_type_map.values())

        address_parts = [p for p in [
            deal.property_address, deal.property_city,
            deal.property_state, deal.property_zip,
        ] if p]
        full_address = ', '.join(address_parts)

        comps = fetch_rent_comps(full_address, unit_mix)

        service = MarketRentService()
        added = 0
        errors = []
        for comp in comps:
            try:
                service.add_rent_comp(deal_id, comp)
                added += 1
            except Exception as exc:
                errors.append(str(exc))
        db.session.commit()

        logger.info("fetch_rent_comps_ai_task: deal_id=%d added=%d skipped=%d", deal_id, added, len(errors))
        return {
            'added': added,
            'skipped': len(errors),
            'message': f'Added {added} rent comp(s) from AI research.',
        }


@celery.task(
    name='multifamily.fetch_sale_comps_ai',
    bind=True,
    max_retries=0,
    time_limit=180,
    soft_time_limit=160,
)
def fetch_sale_comps_ai_task(self, deal_id: int, user_id: str) -> dict:
    """Fetch sale comps via Gemini and insert them into the DB.

    Returns a dict with keys: added, skipped, message.
    Raises on failure so Celery marks the task FAILURE.
    """
    import logging
    logger = logging.getLogger(__name__)

    from app import create_app
    app = create_app()

    with app.app_context():
        from app import db
        from app.models.deal import Deal
        from app.models.unit import Unit
        from app.services.multifamily.ai_comp_service import fetch_sale_comps
        from app.services.multifamily.sale_comp_service import SaleCompService

        deal = Deal.query.get(deal_id)
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        units = Unit.query.filter_by(deal_id=deal_id).all()
        unit_type_map: dict[str, dict] = {}
        for u in units:
            key = u.unit_type
            if key not in unit_type_map:
                unit_type_map[key] = {'unit_type': key, 'count': 0, 'sqft': u.sqft}
            unit_type_map[key]['count'] += 1
        unit_mix = list(unit_type_map.values())

        address_parts = [p for p in [
            deal.property_address, deal.property_city,
            deal.property_state, deal.property_zip,
        ] if p]
        full_address = ', '.join(address_parts)

        comps = fetch_sale_comps(full_address, deal.unit_count, unit_mix)

        service = SaleCompService()
        added = 0
        errors = []
        for comp in comps:
            try:
                service.add_sale_comp(deal_id, comp)
                added += 1
            except Exception as exc:
                errors.append(str(exc))
        db.session.commit()

        logger.info("fetch_sale_comps_ai_task: deal_id=%d added=%d skipped=%d", deal_id, added, len(errors))
        return {
            'added': added,
            'skipped': len(errors),
            'message': f'Added {added} sale comp(s) from AI research.',
        }


# ---------------------------------------------------------------------------
# Startup assertion
# ---------------------------------------------------------------------------

REQUIRED_TASKS = {
    'lead_scoring.bulk_rescore',
    'import.process',
    'enrichment.bulk_enrich',
    'multifamily.recompute_all_deals',
    'om_intake.process_pipeline',
    'multifamily.fetch_rent_comps_ai',
    'multifamily.fetch_sale_comps_ai',
}


@worker_ready.connect
def assert_tasks_registered(sender, **kwargs):
    registered = set(sender.app.tasks.keys())
    missing = REQUIRED_TASKS - registered
    assert not missing, (
        f"Worker started with missing tasks: {missing}. "
        f"Check celery_worker.py."
    )
