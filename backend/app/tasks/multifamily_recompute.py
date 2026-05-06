"""Celery task for bulk pro forma recomputation.

Provides a task that iterates all active Deals and forces a cache warm
by calling DashboardService.get_dashboard for each, plus a Flask Blueprint
with an admin route to enqueue the task.

Requirements: 15.5
"""
import logging

from flask import Blueprint, jsonify

from app import db

logger = logging.getLogger(__name__)

# Import celery at module level so tests can patch 'app.tasks.multifamily_recompute.celery'.
# Use a lazy fallback so the module can be imported even when celery_worker is unavailable
# (e.g. during unit tests that don't start a Celery worker).
try:
    from celery_worker import celery  # noqa: F401
except Exception:  # pragma: no cover
    celery = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Flask Blueprint for admin route
# ---------------------------------------------------------------------------

multifamily_admin_bp = Blueprint('multifamily_admin', __name__)


@multifamily_admin_bp.route('/admin/recompute-all', methods=['POST'])
def recompute_all():
    """Enqueue the bulk recompute Celery task.

    Requirements: 15.5
    """
    import app.tasks.multifamily_recompute as _mf_recompute

    task = _mf_recompute.celery.send_task('multifamily.recompute_all_deals')
    return jsonify({
        'message': 'Bulk recompute task enqueued',
        'task_id': task.id,
    }), 202


# ---------------------------------------------------------------------------
# Celery task (registered via celery_worker.py)
# ---------------------------------------------------------------------------


def recompute_all_deals() -> int:
    """Iterate all active Deals and force cache warm.

    For each Deal, calls DashboardService.get_dashboard(deal_id) which
    will recompute and cache the pro forma if the cache is stale.

    Returns:
        Number of deals processed.

    Requirements: 15.5
    """
    from flask import has_app_context

    from app.models.deal import Deal
    from app.services.multifamily.dashboard_service import DashboardService

    def _run():
        # Get all active (non-deleted) deals
        deals = Deal.query.filter(Deal.deleted_at.is_(None)).all()
        dashboard_service = DashboardService()
        processed = 0

        for deal in deals:
            try:
                dashboard_service.get_dashboard(deal.id)
                db.session.commit()
                processed += 1
                logger.info(
                    "Recomputed pro forma for deal_id=%d (%d/%d)",
                    deal.id,
                    processed,
                    len(deals),
                )
            except Exception as e:
                logger.error(
                    "Failed to recompute deal_id=%d: %s",
                    deal.id,
                    str(e),
                )
                db.session.rollback()

        logger.info(
            "Bulk recompute complete: %d/%d deals processed",
            processed,
            len(deals),
        )
        return processed

    if has_app_context():
        # Already inside an app context (e.g. during tests) — run directly.
        return _run()

    # Running as a standalone Celery worker — create a fresh app context.
    from app import create_app as _create_app
    _app = _create_app()
    with _app.app_context():
        return _run()
