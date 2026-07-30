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
    pin_hint = request.args.get('pin')
    if isinstance(pin_hint, str):
        pin_hint = pin_hint.strip() or None
    else:
        pin_hint = None
    return jsonify(_match_svc.preview_match(lead_id, pin=pin_hint)), 200


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
    # PIN length/format rules are market-specific (Cook 14-digit vs DuPage native);
    # validate in PropertyMatchReviewService after resolving the GIS connector.
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
    tax_situs = body.get('tax_situs_street')
    if isinstance(tax_situs, str):
        tax_situs = tax_situs.strip() or None
    else:
        tax_situs = None
    raw_pins = body.get('candidate_pins')
    candidate_pins = None
    if isinstance(raw_pins, list):
        candidate_pins = [
            str(p).strip() for p in raw_pins if isinstance(p, (str, int)) and str(p).strip()
        ] or None
    apply_closest = bool(body.get('apply_closest_pin'))
    persist_aka = body.get('persist_aka')
    if persist_aka is None:
        persist_aka = True
    else:
        persist_aka = bool(persist_aka)
    return jsonify(_ownership_svc.analyze_lead(
        lead_id,
        force=force,
        tax_situs_street=tax_situs,
        candidate_pins=candidate_pins,
        apply_closest_pin=apply_closest,
        persist_aka=persist_aka,
    )), 200


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
