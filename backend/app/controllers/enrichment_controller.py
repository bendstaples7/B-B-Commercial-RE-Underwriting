"""Enrichment API endpoints for external data source integration.

Provides endpoints for listing registered data sources, enriching
individual leads, and triggering bulk enrichment via Celery.
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import db, limiter
from app.models import Lead, DataSource, EnrichmentRecord
from app.services.data_source_connector import DataSourceConnector

logger = logging.getLogger(__name__)

enrichment_bp = Blueprint('enrichment', __name__)

connector = DataSourceConnector()


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
# Helpers
# ---------------------------------------------------------------------------

def _serialize_enrichment_record(record):
    """Serialize an EnrichmentRecord to a dictionary."""
    return {
        'id': record.id,
        'lead_id': record.lead_id,
        'data_source_id': record.data_source_id,
        'data_source_name': record.data_source.name if record.data_source else None,
        'status': record.status,
        'retrieved_data': record.retrieved_data,
        'error_reason': record.error_reason,
        'created_at': record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_data_source(source):
    """Serialize a DataSourceInfo to a dictionary."""
    return {
        'id': source.id,
        'name': source.name,
        'is_active': source.is_active,
    }


def _enqueue_bulk_enrich_task(lead_ids, source_name):
    """Attempt to enqueue a bulk enrichment job via Celery.

    Falls back to synchronous processing when the Celery broker is
    unavailable so the API remains functional in development environments
    without a running worker.
    """
    try:
        from celery_worker import bulk_enrich_task  # noqa: WPS433
        bulk_enrich_task.apply_async(
            args=[lead_ids, source_name], ignore_result=True,
        )
        logger.info(
            "Enqueued bulk enrichment task for %d leads from source '%s'",
            len(lead_ids), source_name,
        )
        return True
    except Exception as enqueue_err:
        logger.warning(
            "Could not enqueue Celery bulk enrich task, running synchronously: %s",
            enqueue_err,
        )
        connector.bulk_enrich(lead_ids, source_name)
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@enrichment_bp.route('/enrichment/sources', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def list_sources():
    """List all registered data sources.

    Returns
    -------
    200 with list of data sources.
    """
    sources = connector.list_sources()

    return jsonify({
        'sources': [_serialize_data_source(s) for s in sources],
        'total': len(sources),
    }), 200


@enrichment_bp.route('/<int:lead_id>/enrich', methods=['POST'])
@limiter.limit("20 per minute")
@handle_errors
def enrich_lead(lead_id):
    """Enrich a single lead from a specified data source.

    Request body
    ------------
    source_name : str (required)
        Name of the registered data source to use for enrichment.

    Returns
    -------
    200 with the enrichment record.
    404 if lead or data source not found.
    """
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({
            'error': 'Lead not found',
            'message': f'Lead {lead_id} does not exist',
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    source_name = data.get('source_name')
    if not source_name:
        return jsonify({
            'error': 'Validation error',
            'message': 'source_name is required',
        }), 400

    record = connector.enrich_lead(lead_id, source_name)

    return jsonify(_serialize_enrichment_record(record)), 200


@enrichment_bp.route('/enrichment/bulk', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def bulk_enrich():
    """Bulk enrich leads from a specified data source via Celery.

    Request body
    ------------
    lead_ids : list[int] (required)
        IDs of leads to enrich.
    source_name : str (required)
        Name of the registered data source to use for enrichment.

    Returns
    -------
    202 when the bulk enrichment task has been enqueued.
    400 if required fields are missing or invalid.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    lead_ids = data.get('lead_ids')
    source_name = data.get('source_name')

    missing = []
    if not lead_ids:
        missing.append('lead_ids')
    if not source_name:
        missing.append('source_name')
    if missing:
        return jsonify({
            'error': 'Validation error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    if not isinstance(lead_ids, list):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    # Validate that all IDs are integers
    try:
        lead_ids = [int(lid) for lid in lead_ids]
    except (TypeError, ValueError):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    if len(lead_ids) == 0:
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must not be empty',
        }), 400

    # Validate source exists
    ds = DataSource.query.filter_by(name=source_name).first()
    if not ds:
        return jsonify({
            'error': 'Data source not found',
            'message': f"Data source '{source_name}' does not exist",
        }), 404

    if not ds.is_active:
        return jsonify({
            'error': 'Data source inactive',
            'message': f"Data source '{source_name}' is currently inactive",
        }), 400

    enqueued = _enqueue_bulk_enrich_task(lead_ids, source_name)

    return jsonify({
        'message': 'Bulk enrichment started',
        'lead_count': len(lead_ids),
        'source_name': source_name,
        'async': enqueued,
    }), 202
