"""Celery worker configuration."""
from celery import Celery
import os

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
def import_task(job_id: int) -> dict:
    """Celery task wrapper for processing a Google Sheets import job.

    Parameters
    ----------
    job_id : int
        Primary key of the ImportJob to process.

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
        result = importer_service.process_import(job_id)
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
