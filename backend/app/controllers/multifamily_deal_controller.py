"""Multifamily Deal management API endpoints.

Provides endpoints for creating, listing, retrieving, updating, and
soft-deleting multifamily Deals, as well as linking Deals to Leads.

Requirements: 1.1-1.8, 14.1-14.3
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import db
from app.exceptions import RealEstateAnalysisException
from app.schemas import DealCreateSchema, DealUpdateSchema, DealResponseSchema
from app.services.multifamily.deal_service import DealService

logger = logging.getLogger(__name__)

multifamily_deal_bp = Blueprint('multifamily_deals', __name__)

# Schema instances
_deal_create_schema = DealCreateSchema()
_deal_update_schema = DealUpdateSchema()
_deal_response_schema = DealResponseSchema()


# ---------------------------------------------------------------------------
# Shared error handling decorator for all multifamily controllers
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across multifamily endpoints."""
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
    """Extract user ID from g.user_id (set by before_request hook).

    Falls back to reading the header directly for backwards compatibility,
    then to 'anonymous' for development/testing.
    """
    from app.api_utils import get_current_user_id
    return get_current_user_id()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_deal(deal) -> dict:
    """Serialize a Deal model instance to a response dict."""
    return _deal_response_schema.dump(deal)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@multifamily_deal_bp.route('/deals', methods=['POST'])
@handle_errors
def create_deal():
    """Create a new multifamily Deal.

    Requirements: 1.1, 1.2, 1.3
    """
    payload = _deal_create_schema.load(request.get_json())
    user_id = get_user_id()

    service = DealService()
    deal = service.create_deal(user_id, payload)
    db.session.commit()

    return jsonify(_serialize_deal(deal)), 201


@multifamily_deal_bp.route('/deals', methods=['GET'])
@handle_errors
def list_deals():
    """List all Deals owned by the requesting user.

    Requirements: 1.5
    """
    user_id = get_user_id()
    filters = {}

    if request.args.get('status'):
        filters['status'] = request.args.get('status')

    service = DealService()
    deals = service.list_deals(user_id, filters if filters else None)

    return jsonify({
        'deals': [_serialize_deal(d) for d in deals],
        'total': len(deals),
    }), 200


@multifamily_deal_bp.route('/deals/<int:deal_id>', methods=['GET'])
@handle_errors
def get_deal(deal_id):
    """Get a Deal by ID with permission check.

    Requirements: 1.4, 14.3
    """
    user_id = get_user_id()

    service = DealService()
    if not service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    deal = service.get_deal(user_id, deal_id)
    return jsonify(_serialize_deal(deal)), 200


@multifamily_deal_bp.route('/deals/<int:deal_id>', methods=['PATCH'])
@handle_errors
def update_deal(deal_id):
    """Update a Deal.

    Requirements: 1.6
    """
    payload = _deal_update_schema.load(request.get_json())
    user_id = get_user_id()

    service = DealService()
    if not service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    deal = service.update_deal(user_id, deal_id, payload)
    db.session.commit()

    return jsonify(_serialize_deal(deal)), 200


@multifamily_deal_bp.route('/deals/<int:deal_id>', methods=['DELETE'])
@handle_errors
def delete_deal(deal_id):
    """Soft-delete a Deal and all associated child records.

    Requirements: 1.7
    """
    user_id = get_user_id()

    service = DealService()
    if not service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    service.soft_delete_deal(user_id, deal_id)
    db.session.commit()

    return jsonify({'message': 'Deal deleted'}), 200


@multifamily_deal_bp.route('/deals/<int:deal_id>/link-lead', methods=['POST'])
@handle_errors
def link_deal_to_lead(deal_id):
    """Link a Deal to an existing Lead record.

    Requirements: 1.8, 14.2, 14.3
    """
    data = request.get_json()
    lead_id = data.get('lead_id')
    if lead_id is None:
        return jsonify({
            'error': 'Validation error',
            'details': {'lead_id': ['Missing required field']},
        }), 400

    user_id = get_user_id()

    service = DealService()
    if not service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403

    service.link_to_lead(user_id, deal_id, int(lead_id))
    db.session.commit()

    return jsonify({'message': 'Deal linked to lead', 'deal_id': deal_id, 'lead_id': lead_id}), 200
