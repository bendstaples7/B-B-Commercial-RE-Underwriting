"""Condo filter analysis API endpoints.

Provides endpoints for running condo filter analysis, viewing results,
applying manual overrides, and exporting data as CSV.
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request, Response
from marshmallow import ValidationError

from app import db, limiter
from app.models import AddressGroupAnalysis
from app.schemas import CondoFilterResultsQuerySchema, CondoFilterOverrideSchema
from app.services.condo_filter_service import CondoFilterService

logger = logging.getLogger(__name__)

condo_filter_bp = Blueprint('condo_filter', __name__)

condo_filter_service = CondoFilterService()

# Schema instances
results_query_schema = CondoFilterResultsQuerySchema()
override_schema = CondoFilterOverrideSchema()


# ---------------------------------------------------------------------------
# Error handling decorator (mirrors lead_controller.py pattern)
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

@condo_filter_bp.route('/analyze', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def run_analysis():
    """Trigger full condo filter analysis pipeline.

    Queries commercial and mixed-use leads, groups by normalized address,
    computes metrics, applies classification rules, and persists results.

    Returns
    -------
    JSON with summary counts by condo_risk_status and building_sale_possible,
    total address groups analyzed, and total properties processed.
    """
    summary = condo_filter_service.run_analysis()
    return jsonify(summary), 200


@condo_filter_bp.route('/results', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_results():
    """List condo filter analysis results with pagination and filtering.

    Query parameters
    ----------------
    condo_risk_status : str — filter by risk status
    building_sale_possible : str — filter by building sale assessment
    manually_reviewed : bool — filter by manual review status
    page : int (default 1)
    per_page : int (default 20, max 100)
    """
    params = results_query_schema.load(request.args)
    filters = {}
    if params.get('condo_risk_status') is not None:
        filters['condo_risk_status'] = params['condo_risk_status']
    if params.get('building_sale_possible') is not None:
        filters['building_sale_possible'] = params['building_sale_possible']
    if params.get('manually_reviewed') is not None:
        filters['manually_reviewed'] = params['manually_reviewed']

    results = condo_filter_service.get_results(
        filters=filters,
        page=params['page'],
        per_page=params['per_page'],
    )
    return jsonify(results), 200


@condo_filter_bp.route('/results/<int:analysis_id>', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_detail(analysis_id):
    """Get full detail for a single address group including linked leads.

    Parameters
    ----------
    analysis_id : int — ID of the AddressGroupAnalysis record

    Returns 404 if the record does not exist.
    """
    detail = condo_filter_service.get_detail(analysis_id)
    if detail is None:
        return jsonify({
            'error': 'Not found',
            'message': f'Address group analysis {analysis_id} does not exist',
        }), 404
    return jsonify(detail), 200


@condo_filter_bp.route('/results/<int:analysis_id>/override', methods=['PUT'])
@limiter.limit("10 per minute")
@handle_errors
def apply_override(analysis_id):
    """Apply manual override to an address group classification.

    Request body
    ------------
    condo_risk_status : str (required) — new risk status
    building_sale_possible : str (required) — new building sale assessment
    reason : str (required) — justification for the override

    Returns 404 if the record does not exist.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    validated = override_schema.load(data)

    # Check record exists
    analysis = db.session.get(AddressGroupAnalysis, analysis_id)
    if analysis is None:
        return jsonify({
            'error': 'Not found',
            'message': f'Address group analysis {analysis_id} does not exist',
        }), 404

    result = condo_filter_service.apply_override(
        analysis_id=analysis_id,
        status=validated['condo_risk_status'],
        building_sale=validated['building_sale_possible'],
        reason=validated['reason'],
    )
    return jsonify(result), 200


@condo_filter_bp.route('/export/csv', methods=['GET'])
@limiter.limit("10 per minute")
@handle_errors
def export_csv():
    """Export filtered condo filter results as a CSV file download.

    Query parameters
    ----------------
    Same filter parameters as GET /results (condo_risk_status,
    building_sale_possible, manually_reviewed). Pagination is ignored.
    """
    params = results_query_schema.load(request.args)
    filters = {}
    if params.get('condo_risk_status') is not None:
        filters['condo_risk_status'] = params['condo_risk_status']
    if params.get('building_sale_possible') is not None:
        filters['building_sale_possible'] = params['building_sale_possible']
    if params.get('manually_reviewed') is not None:
        filters['manually_reviewed'] = params['manually_reviewed']

    csv_content = condo_filter_service.export_csv(filters)

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename=condo_filter_results.csv',
        },
    )
