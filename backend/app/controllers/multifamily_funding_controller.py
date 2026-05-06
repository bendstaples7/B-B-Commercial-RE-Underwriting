"""Multifamily Funding Sources API endpoints.

Provides endpoints for managing funding sources (Cash, HELOC_1, HELOC_2)
attached to a Deal.

Requirements: 7.1-7.6
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import FundingSourceSchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.funding_service import FundingService

logger = logging.getLogger(__name__)

multifamily_funding_bp = Blueprint('multifamily_funding', __name__)

# Schema instances
_funding_source_schema = FundingSourceSchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_funding_source(source) -> dict:
    """Serialize a FundingSource model instance."""
    return {
        'id': source.id,
        'deal_id': source.deal_id,
        'source_type': source.source_type,
        'total_available': float(source.total_available) if source.total_available is not None else None,
        'interest_rate': float(source.interest_rate) if source.interest_rate is not None else None,
        'origination_fee_rate': float(source.origination_fee_rate) if source.origination_fee_rate is not None else None,
    }


def _check_deal_access(deal_id: int):
    """Check user has access to the deal."""
    user_id = get_user_id()
    service = DealService()
    if not service.user_has_access(user_id, deal_id):
        return jsonify({
            'error': 'Access denied',
            'error_type': 'authorization_error',
        }), 403
    return None, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@multifamily_funding_bp.route('/deals/<int:deal_id>/funding-sources', methods=['POST'])
@handle_errors
def add_funding_source(deal_id):
    """Add a funding source to a Deal.

    Requirements: 7.1, 7.2
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _funding_source_schema.load(request.get_json())

    service = FundingService()
    source = service.add_source(deal_id, payload)
    db.session.commit()

    return jsonify(_serialize_funding_source(source)), 201


@multifamily_funding_bp.route('/deals/<int:deal_id>/funding-sources/<int:source_id>', methods=['PATCH'])
@handle_errors
def update_funding_source(deal_id, source_id):
    """Update a funding source."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = request.get_json()

    service = FundingService()
    source = service.update_source(deal_id, source_id, payload)
    db.session.commit()

    return jsonify(_serialize_funding_source(source)), 200


@multifamily_funding_bp.route('/deals/<int:deal_id>/funding-sources/<int:source_id>', methods=['DELETE'])
@handle_errors
def delete_funding_source(deal_id, source_id):
    """Delete a funding source from a Deal."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = FundingService()
    service.delete_source(deal_id, source_id)
    db.session.commit()

    return jsonify({'message': 'Funding source deleted'}), 200
