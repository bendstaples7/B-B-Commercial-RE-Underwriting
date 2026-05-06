"""Multifamily Pro Forma API endpoints.

Provides endpoints for retrieving computed pro forma results, forcing
recomputation, getting valuation, and sources & uses.

Requirements: 8.1-8.14, 9.1-9.5, 10.1-10.7
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from app import db
from app.exceptions import RealEstateAnalysisException
from app.services.multifamily.dashboard_service import DashboardService
from app.services.multifamily.deal_service import DealService

logger = logging.getLogger(__name__)

multifamily_pro_forma_bp = Blueprint('multifamily_pro_forma', __name__)


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


@multifamily_pro_forma_bp.route('/deals/<int:deal_id>/pro-forma', methods=['GET'])
@handle_errors
def get_pro_forma(deal_id):
    """Get the computed pro forma result for a Deal (cached or recomputed).

    Returns the full 24-month schedule, summary metrics, sources & uses,
    and any missing-input flags.

    Requirements: 8.1-8.14, 15.1, 15.2
    """
    user_id = get_user_id()

    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    dashboard_service = DashboardService()
    result = dashboard_service.get_pro_forma(deal_id)
    db.session.commit()

    return jsonify(result), 200


@multifamily_pro_forma_bp.route(
    '/deals/<int:deal_id>/pro-forma/recompute', methods=['POST']
)
@handle_errors
def recompute_pro_forma(deal_id):
    """Force recompute the pro forma, ignoring any cached result.

    Useful for admin/debug purposes or when the user wants to ensure
    fresh computation.

    Requirements: 15.4
    """
    user_id = get_user_id()

    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    dashboard_service = DashboardService()
    result = dashboard_service.force_recompute(deal_id)
    db.session.commit()

    return jsonify(result), 200


@multifamily_pro_forma_bp.route('/deals/<int:deal_id>/valuation', methods=['GET'])
@handle_errors
def get_valuation(deal_id):
    """Get the valuation for a Deal.

    Computes valuation at cap rate (min/median/average/max) and
    price-per-unit (min/median/average/max) from sale comps.

    Requirements: 9.1-9.5
    """
    user_id = get_user_id()

    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    dashboard_service = DashboardService()
    result = dashboard_service.get_valuation(deal_id)
    db.session.commit()

    return jsonify(result), 200


@multifamily_pro_forma_bp.route(
    '/deals/<int:deal_id>/sources-and-uses', methods=['GET']
)
@handle_errors
def get_sources_and_uses(deal_id):
    """Get Sources & Uses for both scenarios.

    Returns per-scenario breakdown of uses (purchase price, closing costs,
    rehab budget, origination fees, interest reserve) and sources
    (loan amount, cash draw, HELOC draws).

    Requirements: 10.1-10.7
    """
    user_id = get_user_id()

    deal_service = DealService()
    if not deal_service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    dashboard_service = DashboardService()
    result = dashboard_service.get_sources_and_uses(deal_id)
    db.session.commit()

    return jsonify(result), 200
