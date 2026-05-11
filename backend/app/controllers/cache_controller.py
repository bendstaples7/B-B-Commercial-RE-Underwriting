"""Cache management API endpoints.

Provides endpoints for monitoring the Socrata local cache status and
triggering manual cache refresh tasks.
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.schemas import DatasetStatusResponseSchema, SocrataSyncRequestSchema
from app.services import CacheStatusService

logger = logging.getLogger(__name__)

cache_bp = Blueprint('cache', __name__)

_sync_request_schema = SocrataSyncRequestSchema()
_status_response_schema = DatasetStatusResponseSchema()


# ---------------------------------------------------------------------------
# Error handling decorator (consistent with other controllers)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code

            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@cache_bp.route('/socrata/status', methods=['GET'])
@handle_errors
def cache_status():
    """Return the current state of each Socrata cache table.

    Returns
    -------
    200 with a JSON object containing one entry per dataset:
        dataset_name, row_count, last_synced_at, status, last_error.
    503 if the database is unavailable.
    """
    service = CacheStatusService()
    statuses = service.get_status()

    serialized = [_status_response_schema.dump(s) for s in statuses]

    return jsonify({'datasets': serialized}), 200


@cache_bp.route('/socrata/sync', methods=['POST'])
@handle_errors
def trigger_sync():
    """Enqueue a Socrata cache refresh task.

    Request body
    ------------
    dataset : str (required)
        One of: ``all``, ``parcel_universe``, ``parcel_sales``,
        ``improvement_characteristics``.

    Returns
    -------
    202 with ``{"task_id": "<celery_task_id>", "dataset": "<dataset>"}``.
    400 if the request body is missing, not JSON, or contains an invalid dataset.
    503 if the Celery broker is unavailable.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            'error': 'Invalid request',
            'message': 'Request body is required and must be valid JSON.',
        }), 400

    # Validate the request body — raises ValidationError on invalid dataset
    try:
        data = _sync_request_schema.load(body)
    except ValidationError as e:
        # Include accepted_values in the 400 response so callers know valid options
        from app.schemas import ACCEPTED_SYNC_DATASETS  # noqa: WPS433
        return jsonify({
            'error': 'Invalid dataset',
            'message': str(e.messages),
            'accepted_values': ACCEPTED_SYNC_DATASETS,
        }), 400
    dataset = data['dataset']

    # Import the Celery task lazily so the controller works even before
    # task 10.1 (which adds socrata_cache_refresh_task) has been implemented.
    try:
        from celery_worker import socrata_cache_refresh_task  # noqa: WPS433
    except ImportError:
        logger.error(
            "socrata_cache_refresh_task not found in celery_worker — "
            "task 10.1 may not have been implemented yet."
        )
        return jsonify({
            'error': 'Service unavailable',
            'message': 'Cache refresh task is not available.',
        }), 503

    async_result = socrata_cache_refresh_task.delay(dataset=dataset)

    logger.info(
        "Enqueued socrata_cache_refresh_task for dataset '%s', task_id=%s",
        dataset, async_result.id,
    )

    return jsonify({
        'task_id': async_result.id,
        'dataset': dataset,
    }), 202
