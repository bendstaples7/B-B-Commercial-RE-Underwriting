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
        # Nightly association re-sync — re-fetches all deal↔contact associations
        # via the v4 batch API as a catch-all for any links missed by the import
        # backfill or the real-time webhook handler.  Runs at 4 AM UTC, after
        # the signal extraction (2 AM) and rescore (2 AM) jobs.
        'hubspot-nightly-association-sync': {
            'task': 'hubspot.nightly_association_sync',
            'schedule': crontab(hour=4, minute=0),
            'options': {'expires': 7200},
        },
        # Nightly action engine recompute — bulk-recomputes recommended_action
        # for every lead as a catch-all for any stale values that slipped through
        # the per-sync recompute calls (webhook errors, new logic, manual DB edits).
        # Runs at 4:30 AM UTC, after the association sync (4 AM), so any
        # association-driven enrichment changes are already committed before scoring.
        'action-engine-nightly-recompute': {
            'task': 'action_engine.bulk_recompute_all_leads',
            'schedule': crontab(hour=4, minute=30),
            'options': {'expires': 7200},
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
        # Weekly enrichment: pull DuPage acquisition dates from Illinois MyDec PTAX-203 API
        # (data.illinois.gov, updated weekly by IDOR). Runs Sunday 3:30 AM UTC, 30 minutes
        # after the Socrata cache refresh to avoid overlapping heavy DB operations.
        'dupage-acquisition-date-enrichment': {
            'task': 'dupage.enrich_acquisition_dates',
            'schedule': crontab(hour=3, minute=30, day_of_week='sunday'),
            'options': {'expires': 7200},  # expire after 2 hours if not consumed
        },
        # Weekly lead pull: refresh DuPage absentee owner leads from the GIS FeatureServer.
        # Runs Sunday 3:00 AM UTC — before the acquisition date enrichment so any new leads
        # already have their acquisition dates populated in the same weekly run.
        'dupage-absentee-lead-pull': {
            'task': 'dupage.pull_absentee_leads',
            'schedule': crontab(hour=3, minute=0, day_of_week='sunday'),
        },
        # Fix C: GIS backfill — sweep all leads with property_street but has_property_match=False.
        # Catches any lead created by an import path that skipped inline GIS enrichment
        # (Google Sheets, manual CSV, HubSpot, etc.).  Runs every 6 hours; processes up
        # to 200 leads per run to keep the job short and avoid DB lock contention.
        'gis-backfill-property-matches': {
            'task': 'gis.backfill_property_matches',
            'schedule': 6 * 3600,  # every 6 hours
            'options': {'expires': 3600},
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


@celery.task(name='hubspot.enrich_leads')
def enrich_leads_from_hubspot(run_id: int = None) -> dict:
    """Enrich all leads that have confirmed HubSpot deal/contact matches.

    Source-agnostic: works for leads from any import source (Google Sheets,
    Driving for Dollars, DuPage GIS, etc.) as long as they have a confirmed
    HubSpot match.  Safe to run repeatedly — only fills null fields.
    """
    from app.tasks.hubspot_tasks import run_enrich_leads_from_hubspot as _run
    return _run(run_id)


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


@celery.task(name='hubspot_webhook.handle_association', bind=True, max_retries=3)
def handle_association_event(
    self,
    from_object_type: str,
    from_object_id: str,
    to_object_type: str,
    to_object_id: str,
    log_id: int,
):
    """Handle a HubSpot association.created webhook event.

    Merges the new association into the stored raw_payload for the deal and
    immediately enriches the matched lead with the linked contact's data so
    the contact shows up in the platform without waiting for the next import.
    """
    from app.tasks.hubspot_webhook_tasks import run_handle_association_event
    run_handle_association_event(
        from_object_type, from_object_id, to_object_type, to_object_id, log_id
    )


@celery.task(name='hubspot.nightly_association_sync')
def nightly_association_sync():
    """Re-fetch all deal↔contact associations nightly as a catch-all sync.

    Runs after the nightly rescore so any new associations in HubSpot are
    reflected in the platform within 24 hours at most.
    """
    from app.tasks.hubspot_tasks import run_nightly_association_sync
    return run_nightly_association_sync()


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
    """Run the full post-import pipeline via the shared pipeline runner."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Starting post-import pipeline (triggered by run_ids=%s)", run_ids)

    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app
    from app.services.hubspot_pipeline_runner import run_pipeline_after_imports

    app = create_app()
    run_pipeline_after_imports(app, run_ids)


# ---------------------------------------------------------------------------
# DuPage Lead Database — async CSV ingestion task (Requirements 6.9, 9.3–9.5)
# ---------------------------------------------------------------------------

@celery.task(bind=True, name='process_csv_ingestion')
def process_csv_ingestion(self, job_id: int, file_path: str, owner_user_id: str):
    """Async Celery task: process a CSV file of manual distress leads.

    Called by the ingestion controller for CSV files > 500 rows.

    Args:
        job_id: ID of the pre-created ImportJob record.
        file_path: Absolute path to the temporary CSV file.
        owner_user_id: Platform user ID that owns the created leads.

    Requirements: 6.9, 9.3, 9.4, 9.5
    """
    import os

    from app import create_app
    app = create_app()

    with app.app_context():
        try:
            from app.services.deduplication_engine import DeduplicationEngine
            from app.services.gis.base import GISConnectorRegistry
            import app.services.gis.dupage_gis_connector  # triggers self-registration
            from app.services.lead_ingestion_service import LeadIngestionService

            dedup = DeduplicationEngine()
            service = LeadIngestionService(
                dedup_engine=dedup,
                gis_registry=GISConnectorRegistry,
            )
            service.process_csv(job_id, file_path, owner_user_id)
        except Exception as exc:
            # process_csv already marks the ImportJob as failed internally,
            # but if it raised before doing so, mark it here.
            try:
                from app import db
                from app.models.import_job import ImportJob
                from datetime import datetime

                job = db.session.get(ImportJob, job_id)
                if job and job.status not in ('completed', 'failed'):
                    job.status = 'failed'
                    job.error_log = [{'error': str(exc)}]
                    job.completed_at = datetime.utcnow()
                    db.session.commit()
            except Exception:
                pass  # don't mask the original exception
            raise
        finally:
            # Clean up temp file on both success and failure paths
            try:
                os.unlink(file_path)
            except OSError:
                pass


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
    'hubspot.enrich_leads',
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
    'hubspot_webhook.handle_association',
    'hubspot.nightly_association_sync',
    'process_csv_ingestion',
    'dupage.enrich_acquisition_dates',
    'dupage.pull_absentee_leads',
}


# ---------------------------------------------------------------------------
# DuPage acquisition date enrichment — weekly Celery task
# ---------------------------------------------------------------------------

@celery.task(bind=True, name='dupage.enrich_acquisition_dates')
def enrich_dupage_acquisition_dates_task(self):
    """Weekly task: pull DuPage deed transfer dates from Illinois MyDec PTAX-203 API
    and update leads.acquisition_date for matched leads, then rescore.

    Data source: data.illinois.gov (Socrata), dataset it54-y4c6.
    Updated weekly by the Illinois Dept. of Revenue. No auth required.
    """
    import logging
    logger = logging.getLogger('celery.dupage.enrich_acquisition_dates')

    from app import create_app
    app = create_app()

    with app.app_context():
        try:
            # Import the script module inline to reuse its logic
            import sys
            from pathlib import Path
            scripts_dir = Path(__file__).resolve().parent / 'scripts'
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))

            from enrich_dupage_acquisition_dates import (
                fetch_all_dupage_transfers,
                enrich_leads,
                rescore_enriched_leads,
            )

            logger.info("Starting weekly DuPage acquisition date enrichment...")
            pin_to_date = fetch_all_dupage_transfers()

            if not pin_to_date:
                logger.error("No PTAX records fetched — enrichment aborted")
                return {'status': 'aborted', 'reason': 'no records fetched'}

            stats = enrich_leads(pin_to_date, dry_run=False)
            logger.info("Enrichment: %s leads updated", stats.get('updated', 0))

            if stats.get('updated', 0) > 0:
                rescore_enriched_leads(dry_run=False)

            return {'status': 'completed', **stats}

        except Exception as exc:
            logger.error("DuPage acquisition date enrichment failed: %s", exc)
            raise


@worker_ready.connect
def assert_tasks_registered(sender, **kwargs):
    registered = set(sender.app.tasks.keys())
    missing = REQUIRED_TASKS - registered
    assert not missing, (
        f"Worker started with missing tasks: {missing}. "
        f"Check celery_worker.py."
    )


# ---------------------------------------------------------------------------
# DuPage absentee owner lead pull — weekly Celery task
# ---------------------------------------------------------------------------

@celery.task(bind=True, name='dupage.pull_absentee_leads')
def pull_dupage_absentee_leads_task(self):
    """Weekly task: pull all DuPage County residential absentee owner leads
    from the ParcelsWithRealEstateCC GIS FeatureServer and upsert them into
    the leads table.  New leads are scored automatically after insert.

    Data source: gis.dupageco.org ArcGIS FeatureServer (no auth required).
    Run Sunday 3:00 AM UTC — 30 minutes before the acquisition date enrichment
    so new leads have their deed dates populated in the same weekly window.
    """
    import logging
    logger = logging.getLogger('celery.dupage.pull_absentee_leads')

    try:
        import sys
        from pathlib import Path
        scripts_dir = Path(__file__).resolve().parent / 'scripts'
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from pull_dupage_leads import (
            _get_count,
            _fetch_page,
            _feature_to_row,
            ABSENTEE_WHERE,
        )
        import sqlalchemy as sa
        import time
        import os
        from datetime import datetime

        db_url = os.environ.get(
            'DATABASE_URL',
            'postgresql://postgres:postgres@localhost:5432/real_estate_analysis'
        )
        # owner_user_id for userx — the designated DuPage account
        OWNER_USER_ID = os.environ.get('DUPAGE_OWNER_USER_ID', 'f60ca13b-0ca5-4475-8666-9a393f90bff1')
        BATCH_SIZE = 500

        engine = sa.create_engine(db_url, pool_pre_ping=True)

        total = _get_count(ABSENTEE_WHERE)
        logger.info("DuPage absentee pull: %s records available", f"{total:,}")

        offset = 0
        total_upserted = 0
        total_skipped = 0

        with engine.connect() as conn:
            while offset < total:
                fetch_count = min(BATCH_SIZE, total - offset)
                try:
                    features = _fetch_page(ABSENTEE_WHERE, offset, fetch_count)
                except Exception as e:
                    logger.error("Fetch failed at offset %d: %s — skipping batch", offset, e)
                    offset += fetch_count
                    continue

                if not features:
                    break

                rows = []
                for feat in features:
                    row = _feature_to_row(feat.get('attributes', {}), OWNER_USER_ID)
                    if row:
                        rows.append(row)
                    else:
                        total_skipped += 1

                now = datetime.utcnow()
                for row in rows:
                    pin = row.get('county_assessor_pin')
                    sp = conn.begin_nested()
                    try:
                        if pin:
                            existing = conn.execute(
                                sa.text('SELECT id FROM leads WHERE county_assessor_pin = :pin'),
                                {'pin': pin}
                            ).fetchone()
                            if existing:
                                conn.execute(sa.text("""
                                    UPDATE leads SET
                                        owner_first_name = COALESCE(owner_first_name, :owner_first_name),
                                        owner_last_name  = COALESCE(owner_last_name,  :owner_last_name),
                                        property_street  = COALESCE(property_street,  :property_street),
                                        property_city    = COALESCE(property_city,    :property_city),
                                        property_state   = COALESCE(property_state,   :property_state),
                                        property_zip     = COALESCE(property_zip,     :property_zip),
                                        mailing_address  = COALESCE(mailing_address,  :mailing_address),
                                        mailing_city     = COALESCE(mailing_city,     :mailing_city),
                                        mailing_state    = COALESCE(mailing_state,    :mailing_state),
                                        mailing_zip      = COALESCE(mailing_zip,      :mailing_zip),
                                        source_type      = CASE WHEN source_type IS NULL
                                                           THEN :source_type ELSE source_type END,
                                        owner_user_id    = COALESCE(owner_user_id,    :owner_user_id),
                                        updated_at       = :now
                                    WHERE county_assessor_pin = :county_assessor_pin
                                """), {**row, 'now': now})
                                sp.commit()
                                total_upserted += 1
                                continue

                        conn.execute(sa.text("""
                            INSERT INTO leads (
                                county_assessor_pin, owner_first_name, owner_last_name,
                                property_street, property_city, property_state, property_zip,
                                mailing_address, mailing_city, mailing_state, mailing_zip,
                                source_type, data_source, lead_category, owner_user_id,
                                needs_skip_trace, lead_score, created_at, updated_at
                            ) VALUES (
                                :county_assessor_pin, :owner_first_name, :owner_last_name,
                                :property_street, :property_city, :property_state, :property_zip,
                                :mailing_address, :mailing_city, :mailing_state, :mailing_zip,
                                :source_type, :data_source, :lead_category, :owner_user_id,
                                :needs_skip_trace, 0, :now, :now
                            )
                        """), {**row, 'now': now})
                        sp.commit()
                        total_upserted += 1
                    except Exception:
                        sp.rollback()
                        total_skipped += 1

                conn.commit()
                offset += len(features)
                time.sleep(0.3)

        logger.info(
            "DuPage absentee pull complete: %s upserted, %s skipped",
            f"{total_upserted:,}", f"{total_skipped:,}"
        )

        # Score any newly inserted leads (lead_score == 0 means unscored)
        from app import create_app
        app = create_app()
        with app.app_context():
            from app import db
            from app.models.lead import Property
            from app.services.deterministic_scoring_engine import DeterministicScoringEngine
            scoring_engine = DeterministicScoringEngine()
            new_leads = (
                db.session.query(Property)
                .filter(
                    Property.source_type == 'absentee_owner',
                    Property.lead_score == 0,
                )
                .all()
            )
            logger.info("Scoring %d new absentee leads...", len(new_leads))
            for lead in new_leads:
                try:
                    scoring_engine.recalculate_lead_score(lead)
                except Exception as e:
                    logger.error("Score failed for lead %s: %s", lead.id, e)
            logger.info("Scoring complete")

        return {'status': 'completed', 'upserted': total_upserted, 'skipped': total_skipped}

    except Exception as exc:
        logger.error("DuPage absentee lead pull failed: %s", exc)
        raise

# ---------------------------------------------------------------------------
# Fix C: GIS backfill — sweep all leads missing a confirmed parcel match
#
# Any lead with a property_street but has_property_match=False gets a GIS
# lookup attempt.  This is the permanent safety net that catches leads from
# any import path (Sheets, CSV, HubSpot, manual entry) that didn't run GIS
# enrichment inline.  Runs every 6 hours so new imports are cleaned up
# without waiting for the weekly DuPage pull.
# ---------------------------------------------------------------------------

@celery.task(bind=True, name='gis.backfill_property_matches')
def backfill_property_matches_task(self):
    """Periodic task: GIS-enrich all leads where has_property_match=False
    and property_street is populated.

    This is the safety-net that ensures no lead stays perpetually unmatched
    because its import path (Google Sheets, manual CSV, etc.) skipped the
    GIS enrichment step.

    Run schedule: every 6 hours.
    """
    import logging
    _logger = logging.getLogger('celery.gis.backfill_property_matches')

    try:
        from app import create_app
        app = create_app()

        with app.app_context():
            from app import db
            from app.models.lead import Property
            from app.services.gis.base import GISConnectorRegistry
            import app.services.gis.dupage_gis_connector  # noqa: F401 — triggers self-registration
            import app.services.gis.cook_county_gis_connector  # noqa: F401
            from app.services.deduplication_engine import DeduplicationEngine
            from app.services.lead_ingestion_service import LeadIngestionService

            ingestion_svc = LeadIngestionService(
                dedup_engine=DeduplicationEngine(),
                gis_registry=GISConnectorRegistry,
            )

            from app.services.gis.routing import connector_for_lead

            # Sweep leads where:
            # - property_street is populated (something to look up)
            # - has_property_match is still False
            #
            # Forward progress: page through the unmatched set with a strictly
            # increasing id cursor (id > last_id) instead of re-selecting the
            # same first N rows every run. Leads that don't resolve (no
            # connector / no parcel / error) keep has_property_match=False, so
            # without a cursor the task would reprocess the same first batch
            # forever and never reach the rest. The cursor guarantees each lead
            # is touched at most once per run and that the sweep terminates.
            BATCH_SIZE = 200
            # Cap on the number of *network* GIS lookups per invocation. The id
            # cursor already guarantees termination; this just bounds a single
            # run's external-API load. Cheap no-connector skips don't count
            # against it, so out-of-state leads can't starve the lookup budget.
            MAX_GIS_LOOKUPS_PER_RUN = 1000

            matched = 0
            no_match = 0
            errors = 0
            no_connector = 0
            gis_lookups = 0
            processed = 0
            last_id = 0
            capped = False
            failed_pages = 0     # pages whose commit failed and were rolled back
            rolled_back = 0      # leads whose persisted result was discarded

            while not capped:
                batch = (
                    db.session.query(Property)
                    .filter(
                        Property.has_property_match == False,   # noqa: E712
                        Property.property_street != None,        # noqa: E711
                        Property.property_street != '',
                        Property.id > last_id,                   # cursor — forward progress
                    )
                    .order_by(Property.id)
                    .limit(BATCH_SIZE)
                    .all()
                )
                if not batch:
                    break  # swept the whole unmatched set — terminate

                # Per-page tallies of the outcomes we optimistically counted as
                # successful. They are only promoted into the run totals once the
                # page commit succeeds; if the commit is rolled back they are
                # backed out so a flushed-but-not-committed page can't be reported
                # as matched/updated (which would hide the data loss).
                page_first_id = batch[0].id if batch else last_id
                page_matched = 0
                page_no_match = 0

                for lead in batch:
                    last_id = lead.id          # advance cursor past every lead we touch
                    processed += 1
                    # Per-lead isolation: one bad lead is logged and skipped,
                    # never aborting the whole sweep.
                    try:
                        lead_connector = connector_for_lead(lead)
                        if not lead_connector:
                            no_connector += 1
                            continue
                        outcome = ingestion_svc._enrich_with_gis(
                            lead, lead_connector, import_job_id=0
                        )
                        gis_lookups += 1
                        if outcome.get('error'):
                            errors += 1
                        elif outcome.get('match_found'):
                            matched += 1
                            page_matched += 1
                        else:
                            no_match += 1
                            page_no_match += 1
                    except Exception as lead_exc:
                        errors += 1
                        _logger.warning(
                            "gis.backfill_property_matches: skipping lead id=%s "
                            "after unexpected error: %s",
                            getattr(lead, 'id', '?'), lead_exc,
                        )

                    if gis_lookups >= MAX_GIS_LOOKUPS_PER_RUN:
                        capped = True
                        break

                # Persist this page's matches before moving on so a later
                # failure can't discard progress already made.
                try:
                    db.session.commit()
                except Exception as commit_exc:
                    db.session.rollback()
                    # The rollback discarded every write this page made, so the
                    # leads we just counted as matched/no-match were NOT actually
                    # persisted. Back them out of the totals and reclassify the
                    # page as failed — otherwise the task reports rolled-back
                    # leads as successfully matched/updated and hides the loss.
                    page_lost = page_matched + page_no_match
                    matched -= page_matched
                    no_match -= page_no_match
                    errors += page_lost
                    rolled_back += page_lost
                    failed_pages += 1
                    _logger.error(
                        "gis.backfill_property_matches: page commit FAILED for "
                        "leads id %s..%s — rolled back %d lead result(s) "
                        "(%d matched, %d no-match) now counted as errors: %s",
                        page_first_id, last_id, page_lost, page_matched,
                        page_no_match, commit_exc,
                    )

            if processed == 0:
                _logger.info("gis.backfill_property_matches: nothing to do")
            if capped:
                _logger.warning(
                    "gis.backfill_property_matches: hit per-run GIS lookup cap of "
                    "%d; remaining unmatched leads will be swept on the next run",
                    MAX_GIS_LOOKUPS_PER_RUN,
                )
            if failed_pages:
                _logger.error(
                    "gis.backfill_property_matches: %d page(s) failed to commit "
                    "and were rolled back, discarding %d lead result(s); these are "
                    "reported as errors and will be retried on the next run",
                    failed_pages, rolled_back,
                )
            _logger.info(
                "gis.backfill_property_matches: %d matched, %d no-match, %d errors, "
                "%d no-connector (processed=%d, capped=%s, failed_pages=%d, "
                "rolled_back=%d)",
                matched, no_match, errors, no_connector, processed, capped,
                failed_pages, rolled_back,
            )
            return {
                'status': 'completed' if failed_pages == 0 else 'partial',
                'matched': matched,
                'no_match': no_match,
                'errors': errors,
                'no_connector': no_connector,
                'processed': processed,
                'capped': capped,
                'failed_pages': failed_pages,
                'rolled_back': rolled_back,
            }

    except Exception as exc:
        _logger.error("gis.backfill_property_matches failed: %s", exc)
        raise
