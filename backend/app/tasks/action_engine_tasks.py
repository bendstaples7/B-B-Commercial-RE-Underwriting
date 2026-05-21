"""Celery tasks for Action Engine recomputation."""
from celery_worker import celery
from app.services.action_engine_service import ActionEngineService


@celery.task(name='action_engine.recompute_recommended_action')
def recompute_recommended_action(lead_id: int):
    """
    Single-lead Action Engine recomputation task.
    Called when a lead's signals change (e.g., after logging a call, completing a task).
    """
    ActionEngineService.recompute_and_persist(lead_id)


@celery.task(name='action_engine.bulk_recompute_all_leads')
def bulk_recompute_all_leads():
    """
    Bulk Action Engine recomputation task.
    Processes all leads in batches of 500.
    Target: 10,000 leads in 60 seconds.
    """
    ActionEngineService.bulk_recompute()
