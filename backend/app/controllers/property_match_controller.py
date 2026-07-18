"""Property match review and building ownership API endpoints."""
from flask import Blueprint, g, jsonify, request
from marshmallow import Schema, fields, validate

from app.api_utils import require_auth, require_admin
from app.controllers.decorators import handle_errors
from app.schemas import VALID_BUILDING_SALE_POSSIBLE, VALID_CONDO_RISK_STATUSES
from app.services.building_ownership_service import BuildingOwnershipService
from app.services.property_match_review_service import PropertyMatchReviewService

property_match_bp = Blueprint('property_match', __name__)
_match_svc = PropertyMatchReviewService()
_ownership_svc = BuildingOwnershipService()


class RejectMatchSchema(Schema):
    action = fields.Str(required=True, validate=validate.OneOf([
        'skip_trace', 'manual_edit', 'research_pin',
    ]))
    note = fields.Str(load_default=None)


class AddressUpdateSchema(Schema):
    property_street = fields.Str(load_default=None)
    property_city = fields.Str(load_default=None)
    property_state = fields.Str(load_default=None)
    property_zip = fields.Str(load_default=None)


class OverrideSchema(Schema):
    condo_risk_status = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_CONDO_RISK_STATUSES),
    )
    building_sale_possible = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_BUILDING_SALE_POSSIBLE),
    )
    reason = fields.Str(required=True)


class BackfillSchema(Schema):
    enqueue_async = fields.Boolean(load_default=False)
    per_run_cap = fields.Int(load_default=100, validate=validate.Range(min=1, max=500))
    last_id = fields.Int(load_default=0, validate=validate.Range(min=0))


@property_match_bp.route('/<int:lead_id>/property-match/preview', methods=['GET'])
@require_auth
@handle_errors
def preview_property_match(lead_id: int):
    return jsonify(_match_svc.preview_match(lead_id)), 200


@property_match_bp.route('/<int:lead_id>/property-match/approve', methods=['POST'])
@require_auth
@handle_errors
def approve_property_match(lead_id: int):
    actor = getattr(g, 'user_id', 'anonymous')
    body = request.get_json(silent=True)
    pin = (
        body.get('pin')
        if isinstance(body, dict) and isinstance(body.get('pin'), str)
        else None
    )
    if pin:
        from app.services.plugins.pin_utils import normalize_pin_for_socrata
        digits = normalize_pin_for_socrata(pin)
        if len(digits) != 14 or not digits.isdigit():
            return jsonify({
                'error': 'validation_error',
                'message': 'Invalid Cook County PIN',
            }), 400
    return jsonify(_match_svc.approve_match(lead_id, actor=actor, pin=pin)), 200


@property_match_bp.route('/<int:lead_id>/property-match/reject', methods=['POST'])
@require_auth
@handle_errors
def reject_property_match(lead_id: int):
    data = RejectMatchSchema().load(request.get_json() or {})
    actor = getattr(g, 'user_id', 'anonymous')
    return jsonify(_match_svc.reject_match(
        lead_id, data['action'], actor=actor, note=data.get('note'),
    )), 200


@property_match_bp.route('/<int:lead_id>/property-address', methods=['PATCH'])
@require_auth
@handle_errors
def update_property_address(lead_id: int):
    data = AddressUpdateSchema().load(request.get_json() or {})
    actor = getattr(g, 'user_id', 'anonymous')
    return jsonify(_match_svc.update_property_address(lead_id, actor=actor, **data)), 200


@property_match_bp.route('/building-ownership/backfill', methods=['POST'])
@handle_errors
@require_auth
@require_admin
def backfill_building_ownership():
    """POST /api/leads/building-ownership/backfill — run or enqueue commercial backfill."""
    from app.services.building_ownership_backfill import backfill_building_ownership_analysis

    body = request.get_json(silent=True) or {}
    data = BackfillSchema().load(body)

    summary = backfill_building_ownership_analysis(
        per_run_cap=data['per_run_cap'],
        last_id=data['last_id'],
        enqueue_async=data['enqueue_async'],
    )
    return jsonify(summary), 200


@property_match_bp.route('/<int:lead_id>/building-ownership', methods=['GET'])
@require_auth
@handle_errors
def get_building_ownership(lead_id: int):
    detail = _ownership_svc.get_for_lead(lead_id)
    if detail is None:
        return jsonify({'error': 'Not found', 'message': 'No analysis for lead'}), 404
    return jsonify(detail), 200


@property_match_bp.route('/<int:lead_id>/building-ownership/analyze', methods=['POST'])
@require_auth
@handle_errors
def analyze_building_ownership(lead_id: int):
    body = request.get_json(silent=True) or {}
    force = bool(body.get('force'))
    return jsonify(_ownership_svc.analyze_lead(lead_id, force=force)), 200


@property_match_bp.route('/<int:lead_id>/building-ownership/override', methods=['PUT'])
@require_auth
@handle_errors
def override_building_ownership(lead_id: int):
    data = OverrideSchema().load(request.get_json() or {})
    result = _ownership_svc.apply_override(
        lead_id,
        data['condo_risk_status'],
        data['building_sale_possible'],
        data['reason'],
    )
    return jsonify(result), 200
