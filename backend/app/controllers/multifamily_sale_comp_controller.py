"""Multifamily Sale Comps API endpoints.

Provides endpoints for managing sale comparables and retrieving
cap rate / price-per-unit rollup statistics.

Requirements: 4.1-4.5
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import SaleCompCreateSchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.sale_comp_service import SaleCompService

logger = logging.getLogger(__name__)

multifamily_sale_comp_bp = Blueprint('multifamily_sale_comp', __name__)

# Schema instances
_sale_comp_create_schema = SaleCompCreateSchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_sale_comp(comp) -> dict:
    """Serialize a SaleComp model instance."""
    return {
        'id': comp.id,
        'deal_id': comp.deal_id,
        'address': comp.address,
        'unit_count': comp.unit_count,
        'status': comp.status,
        'sale_price': float(comp.sale_price) if comp.sale_price is not None else None,
        'close_date': comp.close_date.isoformat() if comp.close_date else None,
        'observed_cap_rate': float(comp.observed_cap_rate) if comp.observed_cap_rate is not None else None,
        'observed_ppu': float(comp.observed_ppu) if comp.observed_ppu is not None else None,
        'distance_miles': float(comp.distance_miles) if comp.distance_miles is not None else None,
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

@multifamily_sale_comp_bp.route('/deals/<int:deal_id>/sale-comps', methods=['POST'])
@handle_errors
def add_sale_comp(deal_id):
    """Add a sale comparable to a Deal.

    Requirements: 4.1, 4.2, 4.3
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _sale_comp_create_schema.load(request.get_json())

    service = SaleCompService()
    comp = service.add_sale_comp(deal_id, payload)
    db.session.commit()

    return jsonify(_serialize_sale_comp(comp)), 201


@multifamily_sale_comp_bp.route('/deals/<int:deal_id>/sale-comps/<int:comp_id>', methods=['DELETE'])
@handle_errors
def delete_sale_comp(deal_id, comp_id):
    """Delete a sale comparable."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = SaleCompService()
    service.delete_sale_comp(deal_id, comp_id)
    db.session.commit()

    return jsonify({'message': 'Sale comp deleted'}), 200


@multifamily_sale_comp_bp.route('/deals/<int:deal_id>/sale-comps/rollup', methods=['GET'])
@handle_errors
def get_sale_comps_rollup(deal_id):
    """Get sale comp rollup statistics (cap rate and PPU min/median/avg/max).

    Requirements: 4.4, 4.5
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = SaleCompService()
    rollup = service.get_comps_rollup(deal_id)

    def _to_float(val):
        return float(val) if val is not None else None

    result = {
        'Cap_Rate_Min': _to_float(rollup['Cap_Rate_Min']),
        'Cap_Rate_Median': _to_float(rollup['Cap_Rate_Median']),
        'Cap_Rate_Average': _to_float(rollup['Cap_Rate_Average']),
        'Cap_Rate_Max': _to_float(rollup['Cap_Rate_Max']),
        'PPU_Min': _to_float(rollup['PPU_Min']),
        'PPU_Median': _to_float(rollup['PPU_Median']),
        'PPU_Average': _to_float(rollup['PPU_Average']),
        'PPU_Max': _to_float(rollup['PPU_Max']),
        'comps': [_serialize_sale_comp(c) for c in rollup['comps']],
        'warnings': rollup['warnings'],
    }

    return jsonify(result), 200
