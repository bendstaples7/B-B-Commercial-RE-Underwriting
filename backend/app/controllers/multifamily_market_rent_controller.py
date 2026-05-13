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


@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps/fetch-ai', methods=['POST'])
@handle_errors
def fetch_rent_comps_ai(deal_id):
    """Use Gemini AI with web search to fetch and bulk-insert rent comps.

    Option 1 (synchronous): Calls Gemini inline and returns the result.
    Option 2 (async): If ?async=true, enqueues a Celery task and returns
    a job_id immediately. The client polls /fetch-ai/status/:job_id.

    Requirements: 3.2
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    use_async = request.args.get('async', 'false').lower() == 'true'

    if use_async:
        # Option 2: enqueue Celery task, return job_id immediately
        from celery_worker import fetch_rent_comps_ai_task
        user_id = get_user_id()
        task = fetch_rent_comps_ai_task.apply_async(args=[deal_id, user_id])
        return jsonify({'job_id': task.id, 'status': 'pending'}), 202

    # Option 1: synchronous inline execution
    from app.models.deal import Deal
    from app.models.unit import Unit
    from app.services.multifamily.ai_comp_service import fetch_rent_comps

    deal = Deal.query.get(deal_id)
    if deal is None:
        return jsonify({'error': 'Deal not found'}), 404

    # Build unit mix summary from the deal's units
    units = Unit.query.filter_by(deal_id=deal_id).all()
    unit_type_map: dict[str, dict] = {}
    for u in units:
        key = u.unit_type
        if key not in unit_type_map:
            unit_type_map[key] = {'unit_type': key, 'count': 0, 'sqft': u.sqft}
        unit_type_map[key]['count'] += 1

    unit_mix = list(unit_type_map.values())

    # Build full address string
    address_parts = [deal.property_address]
    if deal.property_city:
        address_parts.append(deal.property_city)
    if deal.property_state:
        address_parts.append(deal.property_state)
    if deal.property_zip:
        address_parts.append(deal.property_zip)
    full_address = ', '.join(address_parts)

    try:
        comps = fetch_rent_comps(full_address, unit_mix)
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 502

    if not comps:
        return jsonify({'added': 0, 'message': 'Gemini returned no comps for this property.'}), 200

    service = MarketRentService()
    added = 0
    errors = []
    for comp in comps:
        try:
            service.add_rent_comp(deal_id, comp)
            added += 1
        except Exception as exc:
            errors.append(str(exc))

    db.session.commit()

    return jsonify({
        'added': added,
        'skipped': len(errors),
        'message': f'Added {added} rent comp(s) from AI research.',
    }), 200


@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps/fetch-ai/status/<job_id>', methods=['GET'])
@handle_errors
def get_rent_comps_ai_job_status(deal_id, job_id):
    """Poll the status of an async AI rent comp fetch job.

    Returns:
      - status: 'pending' | 'running' | 'done' | 'failed'
      - added, skipped, message (when done)
      - error (when failed)

    Requirements: 3.2
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    from celery_worker import celery
    result = celery.AsyncResult(job_id)

    state = result.state  # PENDING, STARTED, SUCCESS, FAILURE, REVOKED

    if state == 'PENDING':
        return jsonify({'status': 'pending'}), 200
    elif state == 'STARTED':
        return jsonify({'status': 'running'}), 200
    elif state == 'SUCCESS':
        data = result.result or {}
        return jsonify({
            'status': 'done',
            'added': data.get('added', 0),
            'skipped': data.get('skipped', 0),
            'message': data.get('message', ''),
        }), 200
    else:
        # FAILURE or REVOKED
        error_msg = str(result.result) if result.result else 'Task failed'
        return jsonify({'status': 'failed', 'error': error_msg}), 200



@multifamily_market_rent_bp.route('/deals/<int:deal_id>/rent-comps/rollup', methods=['GET'])
@handle_errors
def get_rent_comps_rollup(deal_id):
    """Get rent comp rollup statistics by unit type.

    When ``unit_type`` query param is omitted, returns rollups for ALL unit
    types that have comps for this deal (as a list).  When ``unit_type`` is
    provided, returns a single-element list filtered to that unit type.

    Requirements: 3.4
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    service = MarketRentService()
    unit_type = request.args.get('unit_type')

    if unit_type:
        # Single unit type — wrap in a list for a consistent response shape
        rollup = service.get_comps_rollup(deal_id, unit_type)
        rollups = [{**rollup, 'unit_type': unit_type}]
    else:
        # All unit types
        rollups = service.get_all_comps_rollups(deal_id)

    result = [
        {
            'unit_type': r['unit_type'],
            'average_observed_rent': float(r['Average_Observed_Rent']) if r['Average_Observed_Rent'] is not None else None,
            'median_observed_rent': float(r['Median_Observed_Rent']) if r['Median_Observed_Rent'] is not None else None,
            'average_rent_per_sqft': float(r['Average_Rent_Per_SqFt']) if r['Average_Rent_Per_SqFt'] is not None else None,
            'comps': [_serialize_rent_comp(c) for c in r['comps']],
        }
        for r in rollups
    ]

    return jsonify(result), 200
