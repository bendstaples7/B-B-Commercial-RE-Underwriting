"""Multifamily Lender Profiles and Deal-Scenario Attachment API endpoints.

Provides endpoints for managing reusable lender profiles and attaching/
detaching them to Deal scenarios (A or B).

Requirements: 6.1-6.7
"""
import logging

from flask import Blueprint, jsonify, request

from app import db
from app.controllers.multifamily_deal_controller import handle_errors, get_user_id
from app.schemas import LenderProfileCreateSchema, DealLenderSelectionSchema
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.lender_service import LenderService

logger = logging.getLogger(__name__)

multifamily_lender_bp = Blueprint('multifamily_lender', __name__)

# Schema instances
_lender_create_schema = LenderProfileCreateSchema()
_deal_lender_selection_schema = DealLenderSelectionSchema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_lender_profile(profile) -> dict:
    """Serialize a LenderProfile model instance."""
    result = {
        'id': profile.id,
        'created_by_user_id': profile.created_by_user_id,
        'company': profile.company,
        'lender_type': profile.lender_type,
        'origination_fee_rate': float(profile.origination_fee_rate) if profile.origination_fee_rate is not None else None,
        'prepay_penalty_description': profile.prepay_penalty_description,
    }

    if profile.lender_type == 'Construction_To_Perm':
        result.update({
            'ltv_total_cost': float(profile.ltv_total_cost) if profile.ltv_total_cost is not None else None,
            'construction_rate': float(profile.construction_rate) if profile.construction_rate is not None else None,
            'construction_io_months': profile.construction_io_months,
            'construction_term_months': profile.construction_term_months,
            'perm_rate': float(profile.perm_rate) if profile.perm_rate is not None else None,
            'perm_amort_years': profile.perm_amort_years,
            'min_interest_or_yield': float(profile.min_interest_or_yield) if profile.min_interest_or_yield is not None else None,
        })
    elif profile.lender_type == 'Self_Funded_Reno':
        result.update({
            'max_purchase_ltv': float(profile.max_purchase_ltv) if profile.max_purchase_ltv is not None else None,
            'treasury_5y_rate': float(profile.treasury_5y_rate) if profile.treasury_5y_rate is not None else None,
            'spread_bps': profile.spread_bps,
            'term_years': profile.term_years,
            'amort_years': profile.amort_years,
            'all_in_rate': float(profile.all_in_rate) if hasattr(profile, 'all_in_rate') and profile.all_in_rate is not None else None,
        })

    return result


def _serialize_selection(selection) -> dict:
    """Serialize a DealLenderSelection model instance."""
    return {
        'id': selection.id,
        'deal_id': selection.deal_id,
        'lender_profile_id': selection.lender_profile_id,
        'scenario': selection.scenario,
        'is_primary': selection.is_primary,
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
# Lender Profile CRUD Routes
# ---------------------------------------------------------------------------

@multifamily_lender_bp.route('/lender-profiles', methods=['POST'])
@handle_errors
def create_lender_profile():
    """Create a new Lender Profile.

    Requirements: 6.1, 6.2, 6.3, 6.4
    """
    payload = _lender_create_schema.load(request.get_json())
    user_id = get_user_id()

    service = LenderService()
    profile = service.create_profile(user_id, payload)
    db.session.commit()

    return jsonify(_serialize_lender_profile(profile)), 201


@multifamily_lender_bp.route('/lender-profiles', methods=['GET'])
@handle_errors
def list_lender_profiles():
    """List lender profiles for the current user.

    Requirements: 6.1, 6.2
    """
    user_id = get_user_id()
    lender_type = request.args.get('lender_type')

    service = LenderService()
    profiles = service.list_profiles(user_id, lender_type)

    return jsonify({
        'profiles': [_serialize_lender_profile(p) for p in profiles],
        'total': len(profiles),
    }), 200


@multifamily_lender_bp.route('/lender-profiles/<int:profile_id>', methods=['PATCH'])
@handle_errors
def update_lender_profile(profile_id):
    """Update a Lender Profile."""
    payload = request.get_json()
    user_id = get_user_id()

    service = LenderService()
    profile = service.update_profile(user_id, profile_id, payload)
    db.session.commit()

    return jsonify(_serialize_lender_profile(profile)), 200


@multifamily_lender_bp.route('/lender-profiles/<int:profile_id>', methods=['DELETE'])
@handle_errors
def delete_lender_profile(profile_id):
    """Delete a Lender Profile."""
    user_id = get_user_id()

    service = LenderService()
    service.delete_profile(user_id, profile_id)
    db.session.commit()

    return jsonify({'message': 'Lender profile deleted'}), 200


# ---------------------------------------------------------------------------
# Deal-Scenario Lender Attachment Routes
# ---------------------------------------------------------------------------

@multifamily_lender_bp.route('/deals/<int:deal_id>/scenarios/<scenario>/lenders', methods=['POST'])
@handle_errors
def attach_lender_to_deal(deal_id, scenario):
    """Attach a Lender Profile to a Deal scenario.

    Requirements: 6.5, 6.6, 6.7
    """
    if scenario not in ('A', 'B'):
        return jsonify({
            'error': 'Validation error',
            'details': {'scenario': ['Must be A or B']},
        }), 400

    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    payload = _deal_lender_selection_schema.load(request.get_json())

    service = LenderService()
    selection = service.attach_to_deal(
        deal_id=deal_id,
        scenario=scenario,
        profile_id=payload['lender_profile_id'],
        is_primary=payload.get('is_primary', False),
    )
    db.session.commit()

    return jsonify(_serialize_selection(selection)), 201


@multifamily_lender_bp.route('/deals/<int:deal_id>/scenarios/<scenario>/lenders/<int:selection_id>', methods=['DELETE'])
@handle_errors
def detach_lender_from_deal(deal_id, scenario, selection_id):
    """Detach a Lender Profile from a Deal scenario."""
    if scenario not in ('A', 'B'):
        return jsonify({
            'error': 'Validation error',
            'details': {'scenario': ['Must be A or B']},
        }), 400

    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = LenderService()
    service.detach_from_deal(deal_id, selection_id)
    db.session.commit()

    return jsonify({'message': 'Lender detached from deal'}), 200
