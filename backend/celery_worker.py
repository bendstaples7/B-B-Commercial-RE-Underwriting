"""Celery worker configuration."""
from celery import Celery
from celery.schedules import crontab
from datetime import date, datetime
import os
import sys

# Ensure the backend directory is on sys.path regardless of where the worker
# is launched from. This prevents "No module named 'app'" errors when Celery
# is started from the project root instead of the backend/ directory.
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
os.chdir(_backend_dir)

# Option 1: Load .env so DATABASE_URL and all other vars are available
# regardless of how the worker is launched.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_backend_dir, '.env'))

# Option 3: Assert critical env vars are present before registering tasks.
# Fails loudly at startup rather than silently mid-task.
_required_env_vars = ['DATABASE_URL', 'REDIS_URL']
_missing = [v for v in _required_env_vars if not os.getenv(v)]
if _missing:
    raise SystemExit(
        f"\n\n*** CELERY STARTUP ERROR: Missing required environment variables: {_missing}\n"
        f"    Ensure backend/.env is present and contains these variables.\n"
    )

# Startup smoke test — validate that 'app' is importable before registering
# any tasks. If this fails, the worker exits immediately with a clear error
# instead of silently failing mid-task.
try:
    import app  # noqa: F401
except ImportError as e:
    raise SystemExit(
        f"\n\n*** CELERY STARTUP ERROR: Cannot import 'app' module.\n"
        f"    Run the worker from the backend/ directory: {e}\n"
    )


from dotenv import load_dotenv
load_dotenv()

from celery import Celery
from celery.signals import worker_ready, worker_init

celery = Celery(
    'real_estate_analysis',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
)

# ---------------------------------------------------------------------------
# Push a Flask app context when the Celery worker starts.
# This allows task functions to use Flask-SQLAlchemy models and services
# without calling create_app() themselves — which is critical for the
# threads pool on Windows where multiple create_app() calls in the same
# process cause DB connection pool exhaustion.
# ---------------------------------------------------------------------------
_flask_app = None
_flask_ctx = None

@worker_init.connect
def init_worker(**kwargs):
    global _flask_app, _flask_ctx
    from app import create_app
    _flask_app = create_app()
    _flask_ctx = _flask_app.app_context()
    _flask_ctx.push()
    import logging
    logging.getLogger(__name__).info("Flask app context pushed for Celery worker.")

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Option 2: Celery Beat schedule — run signal extraction nightly at 2am UTC
    # and rescore leads immediately after. This catches any interactions that
    # slipped through the inline extraction (Option 3) due to errors.
    beat_schedule={
        'hubspot-nightly-signal-extraction': {
            'task': 'hubspot.extract_signals',
            'schedule': 86400,  # every 24 hours (seconds)
            'options': {'expires': 3600},
        },
        'hubspot-nightly-rescore': {
            'task': 'hubspot.rescore_leads',
            'schedule': 86400,
            'options': {'expires': 3600},
        },
        'tasks-nightly-mark-overdue': {
            'task': 'tasks.mark_overdue',
            'schedule': 3600,  # every hour — keeps overdue status current
            'options': {'expires': 1800},
        },
        'hubspot-webhook-log-cleanup': {
            'task': 'hubspot_webhook.purge_logs',
            'schedule': crontab(hour=3, minute=0),  # daily at 3 AM UTC
        },
        # Scheduled engagement sync — imports new HubSpot notes/calls/tasks hourly.
        # Engagements cannot be delivered via webhook (HubSpot legacy app limitation),
        # so this scheduled job is the mechanism for near-real-time engagement updates.
        # Interval is configurable via HUBSPOT_ENGAGEMENT_SYNC_INTERVAL_MINUTES (default: 60).
        'hubspot-scheduled-engagement-sync': {
            'task': 'hubspot.scheduled_engagement_sync',
            'schedule': int(os.environ.get('HUBSPOT_ENGAGEMENT_SYNC_INTERVAL_MINUTES', 60)) * 60,
            'options': {'expires': 3300},  # expire if not consumed within 55 min
        },
    },
)

# ---------------------------------------------------------------------------
# Socrata cache refresh schedule
# ---------------------------------------------------------------------------

def _parse_socrata_schedule() -> crontab:
    """Parse SOCRATA_SYNC_SCHEDULE env var into a crontab, or return the default.

    The env var must be a standard 5-field cron expression:
        <minute> <hour> <day-of-month> <month> <day-of-week>

    Raises
    ------
    InvalidCronExpressionException
        If the value is set but does not contain exactly 5 whitespace-separated
        fields.  Raised at module load time so the worker refuses to start.
    """
    raw = os.getenv('SOCRATA_SYNC_SCHEDULE', '').strip()
    if not raw:
        # Default: every Sunday at 02:00 UTC
        return crontab(hour=2, minute=0, day_of_week='sunday')

    fields = raw.split()
    if len(fields) != 5:
        from app.exceptions import InvalidCronExpressionException
        raise InvalidCronExpressionException(raw)

    minute, hour, day_of_month, month, day_of_week = fields
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month,
        day_of_week=day_of_week,
    )


_socrata_schedule = _parse_socrata_schedule()

celery.conf.beat_schedule['socrata-cache-refresh'] = {
    'task': 'socrata_cache.refresh',
    'schedule': _socrata_schedule,
    'args': (),
    'kwargs': {'dataset': 'all'},
}


def _serialize_property_facts(property_facts) -> dict:
    """Convert a ``PropertyFacts`` ORM object to a plain dict.

    Replicates the serialization logic from
    ``WorkflowController._serialize_property_facts`` as a standalone
    module-level helper so that ``run_comparable_search_task`` can call it
    without instantiating the controller.
    """
    return {
        'id': property_facts.id,
        'address': property_facts.address,
        'property_type': property_facts.property_type.name,
        'units': property_facts.units,
        'bedrooms': property_facts.bedrooms,
        'bathrooms': property_facts.bathrooms,
        'square_footage': property_facts.square_footage,
        'lot_size': property_facts.lot_size,
        'year_built': property_facts.year_built,
        'construction_type': property_facts.construction_type.name,
        'basement': property_facts.basement,
        'parking_spaces': property_facts.parking_spaces,
        'last_sale_price': property_facts.last_sale_price,
        'last_sale_date': property_facts.last_sale_date.isoformat() if property_facts.last_sale_date else None,
        'assessed_value': property_facts.assessed_value,
        'annual_taxes': property_facts.annual_taxes,
        'zoning': property_facts.zoning,
        'interior_condition': property_facts.interior_condition.name,
        'latitude': property_facts.latitude,
        'longitude': property_facts.longitude,
        'data_source': property_facts.data_source,
        'user_modified_fields': property_facts.user_modified_fields or [],
    }


def _resolve_enum(enum_class, value, default):
    """Resolve an enum value using value-string lookup, then name lookup, then default.

    Resolution order:
    1. ``EnumClass(value)``  — matches by value string (e.g. ``"single_family"``)
    2. ``EnumClass[value.upper()]`` — matches by name (e.g. ``"SINGLE_FAMILY"``)
    3. Return *default* if both lookups fail or *value* is not a string.
    """
    if not isinstance(value, str):
        return default
    try:
        return enum_class(value)
    except (ValueError, KeyError):
        pass
    try:
        return enum_class[value.upper()]
    except (ValueError, KeyError):
        pass
    return default


def _map_comparable_to_model(comp_dict: dict, session_id: str):
    """Map a Gemini JSON comparable object to a ``ComparableSale`` ORM instance.

    All 16 fields from the Gemini response are mapped to the corresponding
    ``ComparableSale`` columns.  Each field has a safe default applied on any
    parse or type-coercion failure so that a single bad field never prevents
    the record from being created.

    Parameters
    ----------
    comp_dict : dict
        A single comparable object from the Gemini ``"comparables"`` array.
    session_id : str
        The ``AnalysisSession.id`` (integer PK) to associate the record with.

    Returns
    -------
    ComparableSale
        An unsaved ``ComparableSale`` instance ready for ``db.session.add()``.
    """
    from app.models.comparable_sale import ComparableSale
    from app.models.property_facts import PropertyType, ConstructionType, InteriorCondition

    # --- address ---
    try:
        address = str(comp_dict.get('address') or 'Unknown') or 'Unknown'
    except Exception:
        address = 'Unknown'

    # --- sale_date ---
    try:
        sale_date = datetime.strptime(comp_dict['sale_date'], '%Y-%m-%d').date()
    except (KeyError, ValueError, TypeError, AttributeError):
        sale_date = date.today()

    # --- sale_price ---
    try:
        sale_price = float(comp_dict.get('sale_price', 0.0))
    except (ValueError, TypeError):
        sale_price = 0.0

    # --- property_type ---
    property_type = _resolve_enum(
        PropertyType,
        comp_dict.get('property_type'),
        PropertyType.SINGLE_FAMILY,
    )  # store enum instance

    # --- units ---
    try:
        units = int(comp_dict.get('units', 1))
    except (ValueError, TypeError):
        units = 1

    # --- bedrooms ---
    try:
        bedrooms = int(comp_dict.get('bedrooms', 0))
    except (ValueError, TypeError):
        bedrooms = 0

    # --- bathrooms ---
    try:
        bathrooms = float(comp_dict.get('bathrooms', 0.0))
    except (ValueError, TypeError):
        bathrooms = 0.0

    # --- square_footage ---
    try:
        square_footage = int(comp_dict.get('square_footage', 0))
    except (ValueError, TypeError):
        square_footage = 0

    # --- lot_size ---
    try:
        lot_size = int(comp_dict.get('lot_size', 0))
    except (ValueError, TypeError):
        lot_size = 0

    # --- year_built ---
    try:
        year_built = int(comp_dict.get('year_built', 0))
    except (ValueError, TypeError):
        year_built = 0

    # --- construction_type ---
    construction_type = _resolve_enum(
        ConstructionType,
        comp_dict.get('construction_type'),
        ConstructionType.FRAME,
    )  # store enum instance

    # --- interior_condition ---
    interior_condition = _resolve_enum(
        InteriorCondition,
        comp_dict.get('interior_condition'),
        InteriorCondition.AVERAGE,
    )  # store enum instance

    # --- distance_miles ---
    try:
        distance_miles = float(comp_dict.get('distance_miles', 0.0))
    except (ValueError, TypeError):
        distance_miles = 0.0

    # --- latitude (nullable) ---
    try:
        lat_raw = comp_dict.get('latitude')
        latitude = float(lat_raw) if lat_raw is not None else None
    except (ValueError, TypeError):
        latitude = None

    # --- longitude (nullable) ---
    try:
        lon_raw = comp_dict.get('longitude')
        longitude = float(lon_raw) if lon_raw is not None else None
    except (ValueError, TypeError):
        longitude = None

    # --- similarity_notes (nullable) ---
    try:
        notes_raw = comp_dict.get('similarity_notes')
        similarity_notes = str(notes_raw) if notes_raw is not None else None
    except Exception:
        similarity_notes = None

    return ComparableSale(
        session_id=session_id,
        address=address,
        sale_date=sale_date,
        sale_price=sale_price,
        property_type=property_type,
        units=units,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        square_footage=square_footage,
        lot_size=lot_size,
        year_built=year_built,
        construction_type=construction_type,
        interior_condition=interior_condition,
        distance_miles=distance_miles,
        latitude=latitude,
        longitude=longitude,
        similarity_notes=similarity_notes,
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


@celery.task(name='workflow.run_comparable_search')
def run_comparable_search_task(session_id: str) -> dict:
    """Celery task wrapper for running the comparable search workflow step.

    Executes the comparable search in the background, updates session state
    on completion, and sets loading=False so the frontend polling hook can
    detect when the task is done.

    Parameters
    ----------
    session_id : str
        The session to run the comparable search for.

    Returns
    -------
    dict
        The comparable search result, or {'error': ...} on failure.
    """
    from app import create_app
    from app.models import AnalysisSession
    from app.models.analysis_session import WorkflowStep
    from app import db
    from app.services.gemini_comparable_search_service import GeminiComparableSearchService
    from datetime import datetime

    app = create_app()
    with app.app_context():
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        if not session:
            return {'error': 'session not found'}
        if not os.getenv('GOOGLE_AI_API_KEY'):
            session.loading = False
            session.step_results = {**(session.step_results or {}), 'COMPARABLE_SEARCH_ERROR': 'GOOGLE_AI_API_KEY is not set.'}
            db.session.commit()
            return {'error': 'GOOGLE_AI_API_KEY is not set.'}
        try:
            service = GeminiComparableSearchService()
            result = service.search(
                property_facts=_serialize_property_facts(session.subject_property),
                property_type=session.subject_property.property_type,
            )

            # Persist comparables
            for comp_dict in result['comparables']:
                comparable = _map_comparable_to_model(comp_dict, session.id)
                db.session.add(comparable)

            # Store narrative in step_results
            step_results = dict(session.step_results or {})
            step_results['COMPARABLE_SEARCH'] = {
                'comparable_count': len(result['comparables']),
                'narrative': result['narrative'],
                'status': 'complete',
            }

            # Preserve existing session state update logic
            completed_steps = list(session.completed_steps or [])
            if WorkflowStep.PROPERTY_FACTS.name not in completed_steps:
                completed_steps.append(WorkflowStep.PROPERTY_FACTS.name)
            if WorkflowStep.COMPARABLE_SEARCH.name not in completed_steps:
                completed_steps.append(WorkflowStep.COMPARABLE_SEARCH.name)
            session.completed_steps = completed_steps
            session.step_results = step_results
            session.current_step = WorkflowStep.COMPARABLE_SEARCH
            session.loading = False
            session.updated_at = datetime.utcnow()
            db.session.commit()
            return step_results['COMPARABLE_SEARCH']

        except Exception as exc:
            db.session.rollback()
            session.loading = False
            session.step_results = {
                **(session.step_results or {}),
                'COMPARABLE_SEARCH_ERROR': str(exc),
            }
            db.session.commit()
            return {'error': str(exc)}


@celery.task(name='socrata_cache.refresh')
def socrata_cache_refresh_task(dataset: str = 'all') -> dict:
    """Celery task wrapper for refreshing the Cook County Socrata local cache.

    When *dataset* is ``'all'``, runs an incremental refresh for all three
    datasets (parcel_universe, parcel_sales, improvement_characteristics).
    When *dataset* is a specific dataset name, runs an incremental refresh for
    that dataset only.

    Parameters
    ----------
    dataset : str
        ``'all'`` to refresh all datasets, or one of ``'parcel_universe'``,
        ``'parcel_sales'``, ``'improvement_characteristics'`` to refresh a
        single dataset.

    Returns
    -------
    dict
        JSON-serializable summary of the form::

            {
                "results": [
                    {
                        "dataset": "parcel_universe",
                        "status": "success",
                        "rows_upserted": 1234,
                        "error_message": null
                    },
                    ...
                ]
            }
    """
    from app import create_app
    from app.services.cache_loader_service import CacheLoaderService

    app = create_app()
    with app.app_context():
        service = CacheLoaderService()

        if dataset == 'all':
            sync_results = service.load_all(mode='incremental')
        else:
            sync_results = [service.incremental_refresh(dataset)]

        return {
            'results': [
                {
                    'dataset': r.dataset,
                    'status': r.status,
                    'rows_upserted': r.rows_upserted,
                    'error_message': r.error_message,
                }
                for r in sync_results
            ]
        }


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

def _run_om_intake_pipeline_body(app, job_id: int, pdf_b64: str = None) -> None:
    """Thin shim — delegates to the side-effect-free pipeline module.

    Kept for backwards compatibility; new callers should import
    ``run_om_intake_pipeline_body`` from
    ``app.services.om_intake.om_intake_pipeline`` directly.
    """
    from app.services.om_intake.om_intake_pipeline import run_om_intake_pipeline_body
    run_om_intake_pipeline_body(job_id, pdf_b64=pdf_b64)




@celery.task(
    name='om_intake.process_pipeline',
    bind=True,
    max_retries=0,          # no auto-retry — failures transition job to FAILED
    time_limit=120,         # hard kill after 2 minutes (OS-level SIGKILL)
    soft_time_limit=100,    # raises SoftTimeLimitExceeded at 100s for clean shutdown
)
def process_om_intake_pipeline(self, job_id: int, pdf_b64: str = None) -> None:
    """Run the full OM intake pipeline for a single job.

    PDF bytes are passed directly via the Celery task argument (base64-encoded)
    and are NEVER stored in the database. This prevents the pdf_bytes column
    from being fetched on every status poll, which was causing excessive
    network transfer from the cloud database.

    Stages:
      1. PDF text/table extraction
      2. Gemini field extraction
      3. Market rent research + scenario computation

    On any unhandled exception the job is transitioned to FAILED.
    The time_limit=120 ensures the worker is never blocked indefinitely.
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        _run_om_intake_pipeline_body(app, job_id, pdf_b64)


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
    time_limit=1200,
    soft_time_limit=1100,
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
    time_limit=1200,
    soft_time_limit=1100,
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

        # Build set of existing non-dismissed addresses to prevent duplicates.
        # Dismissed comps are excluded so re-fetching after dismissing works correctly.
        from app.models import SaleComp as _SaleComp
        existing_addresses = {
            c.address.lower()
            for c in _SaleComp.query.filter_by(deal_id=deal_id, is_dismissed=False)
            .with_entities(_SaleComp.address).all()
        }

        service = SaleCompService()
        added = 0
        skipped_dupes = 0
        errors = []
        for comp in comps:
            # Skip if this address already exists for this deal
            if comp["address"].lower() in existing_addresses:
                skipped_dupes += 1
                logger.info(
                    "fetch_sale_comps_ai_task: skipping duplicate address: %s",
                    comp["address"],
                )
                continue
            # Mark all AI-fetched comps as suggested — user must confirm before
            # they appear in rollup statistics.
            comp['is_suggested'] = True
            try:
                sp = db.session.begin_nested()
                service.add_sale_comp(deal_id, comp)
                sp.commit()
                existing_addresses.add(comp["address"].lower())
                added += 1
            except Exception as exc:
                sp.rollback()
                errors.append(str(exc))
        db.session.commit()

        logger.info(
            "fetch_sale_comps_ai_task: deal_id=%d added=%d dupes_skipped=%d errors=%d",
            deal_id, added, skipped_dupes, len(errors),
        )
        return {
            'added': added,
            'skipped': len(errors) + skipped_dupes,
            'message': f'Added {added} sale comp(s) from AI research.',
        }


# ---------------------------------------------------------------------------
# HubSpot CRM Migration Tasks
# ---------------------------------------------------------------------------

@celery.task(name='hubspot.import_deals', bind=True, max_retries=3)
def import_hubspot_deals(self, run_id: int) -> None:
    """Paginate and UPSERT all HubSpot deals. Retries on rate-limit/service errors."""
    from app.tasks.hubspot_tasks import run_import_hubspot_deals
    run_import_hubspot_deals(run_id, self_task=self)


@celery.task(name='hubspot.import_contacts', bind=True, max_retries=3)
def import_hubspot_contacts(self, run_id: int) -> None:
    """Paginate and UPSERT all HubSpot contacts. Retries on rate-limit/service errors."""
    from app.tasks.hubspot_tasks import run_import_hubspot_contacts
    run_import_hubspot_contacts(run_id, self_task=self)


@celery.task(name='hubspot.import_companies', bind=True, max_retries=3)
def import_hubspot_companies(self, run_id: int) -> None:
    """Paginate and UPSERT all HubSpot companies. Retries on rate-limit/service errors."""
    from app.tasks.hubspot_tasks import run_import_hubspot_companies
    run_import_hubspot_companies(run_id, self_task=self)


@celery.task(name='hubspot.import_engagements', bind=True, max_retries=3)
def import_hubspot_engagements(self, run_id: int) -> None:
    """Paginate and UPSERT all HubSpot engagements. Retries on rate-limit/service errors."""
    from app.tasks.hubspot_tasks import run_import_hubspot_engagements
    run_import_hubspot_engagements(run_id, self_task=self)


@celery.task(name='hubspot.run_matching')
def run_hubspot_matching(run_id: int = None) -> None:
    """Match all unmatched HubSpot records to internal Lead/Organization records."""
    from app.tasks.hubspot_tasks import run_hubspot_matching as _run
    _run(run_id)


@celery.task(name='hubspot.convert_activities')
def convert_hubspot_activities(run_id: int = None) -> None:
    """Convert all unconverted HubSpot engagements to Interactions/Tasks."""
    from app.tasks.hubspot_tasks import run_convert_hubspot_activities
    run_convert_hubspot_activities(run_id)


@celery.task(name='hubspot.extract_signals')
def extract_hubspot_signals(run_id: int = None) -> None:
    """Extract signals from HubSpot-imported Interactions and apply suppression flags."""
    from app.tasks.hubspot_tasks import run_extract_hubspot_signals
    run_extract_hubspot_signals(run_id)


@celery.task(name='hubspot.rescore_leads')
def rescore_leads_after_import(user_id: str = 'default') -> int:
    """Rescore all leads using LeadScoringEngine after HubSpot signal extraction."""
    from app.tasks.hubspot_tasks import run_rescore_leads_after_import
    return run_rescore_leads_after_import(user_id)


@celery.task(name='hubspot.generate_backup')
def generate_backup_export() -> str:
    """Serialize all raw HubSpot tables to a JSON backup file."""
    from app.tasks.hubspot_tasks import run_generate_backup_export
    return run_generate_backup_export()


# ---------------------------------------------------------------------------
# HubSpot Webhook Processing Tasks
# ---------------------------------------------------------------------------

@celery.task(name='hubspot_webhook.process_event', bind=True, max_retries=3)
def process_webhook_event(self, log_id: int):
    """Process a single webhook event: dedup check, loop guard, then fetch+upsert."""
    from app.tasks.hubspot_webhook_tasks import run_process_webhook_event
    run_process_webhook_event(log_id, self_task=self)


@celery.task(name='hubspot_webhook.fetch_and_upsert', bind=True, max_retries=3)
def fetch_and_upsert_record(self, object_type: str, object_id: str, log_id: int):
    """Fetch the full record from HubSpot API and upsert into the raw table."""
    from app.tasks.hubspot_webhook_tasks import run_fetch_and_upsert_record
    run_fetch_and_upsert_record(object_type, object_id, log_id, self_task=self)


@celery.task(name='hubspot_webhook.incremental_matching')
def run_incremental_matching(object_type: str, object_id: str):
    """Run HubSpotMatcherService for the updated record."""
    from app.tasks.hubspot_webhook_tasks import run_incremental_matching as _run
    _run(object_type, object_id)


@celery.task(name='hubspot_webhook.convert_activity')
def convert_incremental_activity(engagement_id: str):
    """Run HubSpotActivityConverterService for a single engagement."""
    from app.tasks.hubspot_webhook_tasks import run_convert_incremental_activity
    run_convert_incremental_activity(engagement_id)


@celery.task(name='hubspot_webhook.extract_signals')
def extract_incremental_signals(engagement_id: str, lead_id: int):
    """Run HubSpotSignalExtractorService for a single engagement."""
    from app.tasks.hubspot_webhook_tasks import run_extract_incremental_signals
    run_extract_incremental_signals(engagement_id, lead_id)


@celery.task(name='hubspot_webhook.rescore_lead')
def rescore_lead(lead_id: int):
    """Run LeadScoringEngine for a single lead."""
    from app.tasks.hubspot_webhook_tasks import run_rescore_lead
    run_rescore_lead(lead_id)


@celery.task(name='hubspot_webhook.purge_logs')
def purge_old_webhook_logs():
    """Delete HubSpotWebhookLog records older than 30 days."""
    from app.tasks.hubspot_webhook_tasks import run_purge_old_webhook_logs
    return run_purge_old_webhook_logs()


# ---------------------------------------------------------------------------
# Action Engine Tasks
#
# Imported here so Celery discovers the @celery.task decorators defined in
# app/tasks/action_engine_tasks.py at worker startup.
# ---------------------------------------------------------------------------
import app.tasks.action_engine_tasks  # noqa: F401  (side-effect import)


@celery.task(name='tasks.mark_overdue')
def mark_tasks_overdue() -> int:
    """Bulk-update tasks with status='open' and past due_date to status='overdue'.

    Runs hourly via Celery Beat so the follow-up-overdue view stays current
    without relying on individual task reads to trigger the lazy update.
    """
    import logging
    logger = logging.getLogger(__name__)
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    app = create_app()
    with app.app_context():
        from app import db
        from app.models.task import Task
        from datetime import datetime
        updated = Task.query.filter(
            Task.status == 'open',
            Task.due_date.isnot(None),
            Task.due_date < datetime.utcnow(),
        ).update({'status': 'overdue'}, synchronize_session=False)
        db.session.commit()
        if updated:
            logger.info("mark_tasks_overdue: marked %d task(s) as overdue.", updated)
        return updated


@celery.task(name='hubspot.scheduled_engagement_sync')
def scheduled_engagement_sync() -> None:
    """Scheduled task: import new HubSpot engagements and run the full pipeline."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Starting scheduled engagement sync")

    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.models import HubSpotConfig
        from app.services import HubSpotImportService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            logger.info("Scheduled engagement sync skipped: no HubSpot config found")
            return

        svc = HubSpotImportService()
        try:
            runs = svc.start_import(object_types=['engagements'])
            run_ids = [r.id for r in runs]
            logger.info("Scheduled engagement sync: started import run_ids=%s", run_ids)
        except Exception as exc:
            logger.error("Scheduled engagement sync: failed to start import: %s", exc)
            return

    # Chain to post-import pipeline after import completes
    # start_import already dispatched the import tasks; pipeline waits for them
    run_post_import_pipeline.delay(run_ids)
    logger.info("Scheduled engagement sync: pipeline dispatched for run_ids=%s", run_ids)


@celery.task(name='hubspot.post_import_pipeline')
def run_post_import_pipeline(run_ids: list = None) -> None:
    """Run the full post-import pipeline: matching → convert activities → extract signals → rescore.

    Queued automatically after every HubSpot import trigger.  Polls until all
    import runs in the batch are finished (success/partial/failed), then runs
    matching → convert → signals → rescore sequentially.
    """
    import logging
    import time
    logger = logging.getLogger(__name__)
    logger.info("Starting post-import pipeline (triggered by run_ids=%s)", run_ids)

    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    app = create_app()

    # Wait for all import runs in this batch to reach a terminal state
    if run_ids:
        max_wait_seconds = 3600  # 1 hour max
        poll_interval = 15
        elapsed = 0
        with app.app_context():
            from app.models import HubSpotImportRun
            while elapsed < max_wait_seconds:
                runs = HubSpotImportRun.query.filter(HubSpotImportRun.id.in_(run_ids)).all()
                terminal = {'success', 'partial', 'failed'}
                if all(r.status in terminal for r in runs):
                    logger.info("All import runs complete — proceeding with pipeline")
                    break
                logger.info("Waiting for import runs to complete (%ds elapsed)...", elapsed)
                time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                logger.warning("Post-import pipeline timed out waiting for runs %s", run_ids)

    from app.tasks.hubspot_tasks import (
        run_hubspot_matching,
        run_convert_hubspot_activities,
        run_extract_hubspot_signals,
        run_rescore_leads_after_import,
    )

    run_hubspot_matching()
    logger.info("Post-import pipeline: matching complete")

    run_convert_hubspot_activities()
    logger.info("Post-import pipeline: activity conversion complete")

    run_extract_hubspot_signals()
    logger.info("Post-import pipeline: signal extraction complete")

    run_rescore_leads_after_import()
    logger.info("Post-import pipeline: lead rescoring complete")


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
    'hubspot.import_deals',
    'hubspot.import_contacts',
    'hubspot.import_companies',
    'hubspot.import_engagements',
    'hubspot.run_matching',
    'hubspot.convert_activities',
    'hubspot.extract_signals',
    'hubspot.rescore_leads',
    'hubspot.generate_backup',
    'hubspot.post_import_pipeline',
    'hubspot.scheduled_engagement_sync',
    'tasks.mark_overdue',
    'action_engine.recompute_recommended_action',
    'action_engine.bulk_recompute_all_leads',
    'hubspot_webhook.process_event',
    'hubspot_webhook.fetch_and_upsert',
    'hubspot_webhook.incremental_matching',
    'hubspot_webhook.convert_activity',
    'hubspot_webhook.extract_signals',
    'hubspot_webhook.rescore_lead',
    'hubspot_webhook.purge_logs',
}


@worker_ready.connect
def assert_tasks_registered(sender, **kwargs):
    registered = set(sender.app.tasks.keys())
    missing = REQUIRED_TASKS - registered
    assert not missing, (
        f"Worker started with missing tasks: {missing}. "
        f"Check celery_worker.py."
    )
