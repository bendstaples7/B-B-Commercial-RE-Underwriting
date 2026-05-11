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


celery = Celery(
    'real_estate_analysis',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
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

celery.conf.beat_schedule = {
    'socrata-cache-refresh': {
        'task': 'socrata_cache.refresh',
        'schedule': _socrata_schedule,
        'args': (),
        'kwargs': {'dataset': 'all'},
    },
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
    ).value  # pass the string value, not the enum object

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
    ).value  # pass the string value, not the enum object

    # --- interior_condition ---
    interior_condition = _resolve_enum(
        InteriorCondition,
        comp_dict.get('interior_condition'),
        InteriorCondition.AVERAGE,
    ).value  # pass the string value, not the enum object

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


@celery.task(name='lead_scoring.bulk_rescore')
def bulk_rescore_task(user_id: str, lead_ids: list[int] | None = None) -> int:
    """Celery task wrapper for bulk lead rescoring.

    Parameters
    ----------
    user_id : str
        The user whose scoring weights to use.
    lead_ids : list[int] or None
        Specific lead IDs to rescore, or None for all leads.

    Returns
    -------
    int
        Number of leads rescored.
    """
    from app import create_app
    from app.services.lead_scoring_engine import LeadScoringEngine

    app = create_app()
    with app.app_context():
        engine = LeadScoringEngine()
        return engine.bulk_rescore(user_id, lead_ids)


@celery.task(name='import.process')
def import_task(job_id: int, lead_category: str = 'residential') -> dict:
    """Celery task wrapper for processing a Google Sheets import job.

    Parameters
    ----------
    job_id : int
        Primary key of the ImportJob to process.
    lead_category : str
        Category to assign to imported leads ('residential' or 'commercial').

    Returns
    -------
    dict
        Summary with status, rows_imported, rows_skipped, total_rows.
    """
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
    """Celery task wrapper for bulk lead enrichment.

    Parameters
    ----------
    lead_ids : list[int]
        IDs of leads to enrich.
    source_name : str
        Name of the registered data source plugin.

    Returns
    -------
    int
        Number of enrichment records created.
    """
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
            session.current_step = WorkflowStep.COMPARABLE_REVIEW
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
    """Celery task wrapper for bulk multifamily pro forma recomputation.

    Iterates all active Deals and forces a cache warm by calling
    DashboardService.get_dashboard for each.

    Returns
    -------
    int
        Number of deals processed.
    """
    from app.tasks.multifamily_recompute import recompute_all_deals
    return recompute_all_deals()
