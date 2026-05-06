"""Multifamily Rent Roll API endpoints.

Provides endpoints for managing Units and Rent Roll Entries within a Deal.

Requirements: 2.1-2.6
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import UnitCreateSchema, UnitUpdateSchema, RentRollEntrySchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.rent_roll_service import RentRollService

logger = logging.getLogger(__name__)

multifamily_rent_roll_bp = Blueprint('multifamily_rent_roll', __name__)

# Schema instances
_unit_create_schema = UnitCreateSchema()
_unit_update_schema = UnitUpdateSchema()
_rent_roll_entry_schema = RentRollEntrySchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_unit(unit) -> dict:
    """Serialize a Unit model instance."""
    return {
        'id': unit.id,
        'deal_id': unit.deal_id,
        'unit_identifier': unit.unit_identifier,
        'unit_type': unit.unit_type,
        'beds': unit.beds,
        'baths': float(unit.baths) if unit.baths is not None else None,
        'sqft': unit.sqft,
        'occupancy_status': unit.occupancy_status,
    }


def _serialize_rent_roll_entry(entry) -> dict:
    """Serialize a RentRollEntry model instance."""
    return {
        'id': entry.id,
        'unit_id': entry.unit_id,
        'current_rent': float(entry.current_rent) if entry.current_rent is not None else None,
        'lease_start_date': entry.lease_start_date.isoformat() if entry.lease_start_date else None,
        'lease_end_date': entry.lease_end_date.isoformat() if entry.lease_end_date else None,
        'notes': entry.notes,
    }


def _serialize_summary(summary: dict) -> dict:
    """Serialize the rent roll summary, converting Decimals to floats."""
    return {
        'Total_Unit_Count': summary['Total_Unit_Count'],
        'Occupied_Unit_Count': summary['Occupied_Unit_Count'],
        'Vacant_Unit_Count': summary['Vacant_Unit_Count'],
        'Occupancy_Rate': float(summary['Occupancy_Rate']),
        'Total_In_Place_Rent': float(summary['Total_In_Place_Rent']),
        'Average_Rent_Per_Occupied_Unit': float(summary['Average_Rent_Per_Occupied_Unit']),
        'warnings': summary['warnings'],
    }


def _check_deal_access(deal_id: int):
    """Check user has access to the deal. Returns (response, status) or (None, None)."""
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

@multifamily_rent_roll_bp.route('/deals/<int:deal_id>/units', methods=['POST'])
@handle_errors
def add_unit(deal_id):
    """Add a Unit to a Deal.

    Requirements: 2.1, 2.2
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _unit_create_schema.load(request.get_json())

    service = RentRollService()
    unit = service.add_unit(deal_id, payload)
    db.session.commit()

    return jsonify(_serialize_unit(unit)), 201


@multifamily_rent_roll_bp.route('/deals/<int:deal_id>/units/<int:unit_id>', methods=['PATCH'])
@handle_errors
def update_unit(deal_id, unit_id):
    """Update an existing Unit."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _unit_update_schema.load(request.get_json())

    service = RentRollService()
    unit = service.update_unit(deal_id, unit_id, payload)
    db.session.commit()

    return jsonify(_serialize_unit(unit)), 200


@multifamily_rent_roll_bp.route('/deals/<int:deal_id>/units/<int:unit_id>', methods=['DELETE'])
@handle_errors
def delete_unit(deal_id, unit_id):
    """Delete a Unit and its associated entries."""
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = RentRollService()
    service.delete_unit(deal_id, unit_id)
    db.session.commit()

    return jsonify({'message': 'Unit deleted'}), 200


@multifamily_rent_roll_bp.route('/deals/<int:deal_id>/units/<int:unit_id>/rent-roll', methods=['PUT'])
@handle_errors
def set_rent_roll_entry(deal_id, unit_id):
    """Set (create or update) the Rent Roll Entry for a Unit.

    Requirements: 2.3, 2.4
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _rent_roll_entry_schema.load(request.get_json())

    service = RentRollService()
    entry = service.set_rent_roll_entry(deal_id, unit_id, payload)
    db.session.commit()

    return jsonify(_serialize_rent_roll_entry(entry)), 200


@multifamily_rent_roll_bp.route('/deals/<int:deal_id>/rent-roll/summary', methods=['GET'])
@handle_errors
def get_rent_roll_summary(deal_id):
    """Get rent roll summary statistics for a Deal.

    Requirements: 2.5, 2.6
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = RentRollService()
    summary = service.get_rent_roll_summary(deal_id)

    return jsonify(_serialize_summary(summary)), 200
