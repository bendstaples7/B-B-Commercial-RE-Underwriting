"""Multifamily Rehab Plan API endpoints.

Provides endpoints for managing per-unit rehab plan entries
and retrieving monthly rehab rollup statistics.

Requirements: 5.1-5.7
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import RehabPlanEntrySchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.rehab_service import RehabService

logger = logging.getLogger(__name__)

multifamily_rehab_bp = Blueprint('multifamily_rehab', __name__)

# Schema instances
_rehab_plan_schema = RehabPlanEntrySchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_rehab_entry(entry) -> dict:
    """Serialize a RehabPlanEntry model instance."""
    return {
        'id': entry.id,
        'unit_id': entry.unit_id,
        'renovate_flag': entry.renovate_flag,
        'current_rent': float(entry.current_rent) if entry.current_rent is not None else None,
        'suggested_post_reno_rent': float(entry.suggested_post_reno_rent) if entry.suggested_post_reno_rent is not None else None,
        'underwritten_post_reno_rent': float(entry.underwritten_post_reno_rent) if entry.underwritten_post_reno_rent is not None else None,
        'rehab_start_month': entry.rehab_start_month,
        'downtime_months': entry.downtime_months,
        'stabilized_month': entry.stabilized_month,
        'rehab_budget': float(entry.rehab_budget) if entry.rehab_budget is not None else None,
        'scope_notes': entry.scope_notes,
        'stabilizes_after_horizon': entry.stabilizes_after_horizon,
    }


def _serialize_monthly_rollup(rollup: list[dict]) -> list[dict]:
    """Serialize monthly rollup, converting Decimals to floats and keys to snake_case."""
    return [
        {
            'month': row['month'],
            'units_starting_rehab_count': row['Units_Starting_Rehab_Count'],
            'units_offline_count': row['Units_Offline_Count'],
            'units_stabilizing_count': row['Units_Stabilizing_Count'],
            'capex_spend': float(row['CapEx_Spend']),
        }
        for row in rollup
    ]


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

@multifamily_rehab_bp.route('/deals/<int:deal_id>/units/<int:unit_id>/rehab', methods=['PUT'])
@handle_errors
def set_rehab_plan_entry(deal_id, unit_id):
    """Set (create or update) the Rehab Plan Entry for a Unit.

    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _rehab_plan_schema.load(request.get_json())

    service = RehabService()
    entry = service.set_plan_entry(deal_id, unit_id, payload)
    db.session.commit()

    return jsonify(_serialize_rehab_entry(entry)), 200


@multifamily_rehab_bp.route('/deals/<int:deal_id>/rehab/rollup', methods=['GET'])
@handle_errors
def get_rehab_rollup(deal_id):
    """Get monthly rehab rollup for months 1-24.

    Requirements: 5.6, 5.7
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = RehabService()
    rollup = service.get_monthly_rollup(deal_id)

    return jsonify(_serialize_monthly_rollup(rollup)), 200
