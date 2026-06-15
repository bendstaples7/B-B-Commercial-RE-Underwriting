"""Data Sources Panel API endpoints.

Provides a single read-only endpoint that aggregates the health and coverage
status of every data source feeding lead ingestion, enrichment, and scoring.

URL prefix: /api/data-sources  (registered in app/__init__.py)
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, g
from marshmallow import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api_utils import require_auth
from app.schemas import DataSourceStatusSchema
from app.services.data_source_status_service import DataSourceStatusService

logger = logging.getLogger(__name__)

data_sources_bp = Blueprint('data_sources', __name__)

_status_schema = DataSourceStatusSchema()


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across data-sources endpoints."""
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
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Service unavailable',
                'message': 'Database unavailable — please try again later.',
            }), 503
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

@data_sources_bp.route('/status', methods=['GET'])
@handle_errors
@require_auth
def get_data_source_status():
    """Return the aggregated data-source status for the authenticated user.

    Returns
    -------
    200  JSON payload with ``socrata_datasets``, ``enrichment_sources``,
         ``import_source``, and ``hubspot_source`` keys.
    401  Missing or invalid Bearer token (raised by ``@require_auth``).
    503  Database unavailable (``SQLAlchemyError`` caught by ``@handle_errors``).
    """
    svc = DataSourceStatusService()
    payload = svc.get_all_statuses(g.user_id)
    return jsonify(_status_schema.dump(payload)), 200
