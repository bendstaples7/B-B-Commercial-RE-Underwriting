"""Multifamily Dashboard API endpoint.

Provides the Summary Dashboard endpoint that returns side-by-side
Scenario A and Scenario B outputs for a Deal.

Requirements: 11.1, 11.2
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from app import db
from app.exceptions import RealEstateAnalysisException
from app.services.multifamily.dashboard_service import DashboardService
from app.services.multifamily.deal_service import DealService

logger = logging.getLogger(__name__)

multifamily_dashboard_bp = Blueprint('multifamily_dashboard', __name__)


# ---------------------------------------------------------------------------
# Shared helpers (same pattern as multifamily_deal_controller)
# ---------------------------------------------------------------------------


def handle_errors(f):
    """Decorator for consistent error handling across multifamily endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RealEstateAnalysisException as e:
            logger.warning("Application error [%s]: %s", e.status_code, e.message)
            return jsonify({
                'error': e.message,
                **e.payload,
            }), e.status_code
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


def get_user_id() -> str:
    """Extract user ID from request headers."""
    return request.headers.get('X-User-Id', 'anonymous')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@multifamily_dashboard_bp.route('/deals/<int:deal_id>/dashboard', methods=['GET'])
@handle_errors
def get_dashboard(deal_id):
    """Get the Summary Dashboard for a Deal.

    Returns side-by-side Scenario A (Construction-to-Perm) and Scenario B
    (Self-Funded Renovation) summaries including NOI, DSCR, valuation,
    sources & uses, and cash-on-cash metrics.

    When a scenario has missing inputs, its summary fields are returned as
    null with the missing_inputs list identifying each absent input.

    Requirements: 11.1, 11.2
    """
    user_id = get_user_id()

    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    dashboard_service = DashboardService()
    result = dashboard_service.get_dashboard(deal_id)
    db.session.commit()

    return jsonify(result), 200
