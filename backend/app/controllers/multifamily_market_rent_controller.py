"""Multifamily Market Rent Assumptions and Rent Comps API endpoints.

Provides endpoints for managing market rent assumptions per unit type
and rent comparables used to justify those assumptions.

Requirements: 3.1-3.5
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import MarketRentAssumptionSchema, RentCompCreateSchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.market_rent_service import MarketRentService

logger = logging.getLogger(__name__)

multifamily_market_rent_bp = Blueprint('multifamily_market_rent', __name__)

# Schema instances
_market_rent_schema = MarketRentAssumptionSchema()
_rent_comp_create_schema = RentCompCreateSchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_assumption(assumption) -> dict:
    """Serialize a MarketRentAssumption model instance."""
    return {
        'id': assumption.id,
        'deal_id': assumption.deal_id,
        'unit_type': assumption.unit_type,
        'target_rent': float(assumption.target_rent) if assumption.target_rent is not None else None,
        'post_reno_target_rent': float(assumption.post_reno_target_rent) if assumption.post_reno_target_rent is not None else None,
    }


def _serialize_rent_comp(comp) -> dict:
    """Serialize a RentComp model instance."""
    return {
        'id': comp.id,
        'deal_id': comp.deal_id,
        'address': comp.address,
        'neighborhood': comp.neighborhood,
        'unit_type': comp.unit_type,
        'observed_rent': float(comp.observed_rent) if comp.observed_rent is not None else None,
        'sqft': comp.sqft,
        'rent_per_sqft': float(comp.rent_per_sqft) if comp.rent_per_sqft is not None else None,
        'observation_date': comp.observation_date.isoformat() if comp.observation_date else None,
        'source_url': comp.source_url,
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

@multifamily_market_rent_bp.route('/deals/<int:deal_id>/market-rents/<unit_type>', methods=['PUT'])
@handle_errors
def set_market_rent_assumption(deal_id, unit_type):
    """Set (create or update) a market rent assumption for a unit type.

    Requirements: 3.1
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = request.get_json() or {}
    # unit_type comes from URL, inject into payload for schema validation
    payload['unit_type'] = unit_type
    validated = _market_rent_schema.load(payload)

    service = MarketRentService()
    assumption = service.set_assumption(deal_id, unit_type, validated)
    db.session.commit()

    return jsonify(_serialize_assumption(assumption)), 200


@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps', methods=['POST'])
@handle_errors
def add_rent_comp(deal_id):
    """Add a rent comparable to a Deal.

    Requirements: 3.2, 3.3
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _rent_comp_create_schema.load(request.get_json())

    service = MarketRentService()
    comp = service.add_rent_comp(deal_id, payload)
    db.session.commit()

    return jsonify(_serialize_rent_comp(comp)), 201


@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps/<int:comp_id>', methods=['DELETE'])
@handle_errors
def delete_rent_comp(deal_id, comp_id):
    """Delete a rent comparable."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = MarketRentService()
    service.delete_rent_comp(deal_id, comp_id)
    db.session.commit()

    return jsonify({'message': 'Rent comp deleted'}), 200


@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps/rollup', methods=['GET'])
@handle_errors
def get_rent_comps_rollup(deal_id):
    """Get rent comp rollup statistics by unit type.

    Requirements: 3.4
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    unit_type = request.args.get('unit_type')
    if not unit_type:
        return jsonify({
            'error': 'Validation error',
            'details': {'unit_type': ['Query parameter unit_type is required']},
        }), 400

    service = MarketRentService()
    rollup = service.get_comps_rollup(deal_id, unit_type)

    result = {
        'Average_Observed_Rent': float(rollup['Average_Observed_Rent']) if rollup['Average_Observed_Rent'] is not None else None,
        'Median_Observed_Rent': float(rollup['Median_Observed_Rent']) if rollup['Median_Observed_Rent'] is not None else None,
        'Average_Rent_Per_SqFt': float(rollup['Average_Rent_Per_SqFt']) if rollup['Average_Rent_Per_SqFt'] is not None else None,
        'comps': [_serialize_rent_comp(c) for c in rollup['comps']],
    }

    return jsonify(result), 200
