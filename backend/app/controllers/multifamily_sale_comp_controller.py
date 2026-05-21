"""Multifamily Sale Comps API endpoints.

Provides endpoints for managing sale comparables and retrieving
cap rate / price-per-unit rollup statistics.

Requirements: 4.1-4.5
"""
import logging

from flask import Blueprint, jsonify, request

from app import db, limiter
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
        'noi': float(comp.noi) if comp.noi is not None else None,
        'cap_rate_confidence': comp.cap_rate_confidence,
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

@multifamily_sale_comp_bp.route('/deals/<int:deal_id>/sale-comps/fetch-ai', methods=['POST'])
@limiter.limit("10 per hour")
@handle_errors
def fetch_sale_comps_ai(deal_id):
    """Use Gemini AI with web search to fetch and bulk-insert sale comps.

    Option 1 (synchronous): Calls Gemini inline and returns the result.
    Option 2 (async): If ?async=true, enqueues a Celery task and returns
    a job_id immediately. The client polls /fetch-ai/status/:job_id.

    Requirements: 4.1
    """
    resp, status = _check_deal_access(deal_id)
    if resp is not None:
        return resp, status

    use_async = request.args.get('async', 'false').lower() == 'true'

    if use_async:
        # Option 2: enqueue Celery task, return job_id immediately
        from celery_worker import fetch_sale_comps_ai_task
        user_id = get_user_id()
        task = fetch_sale_comps_ai_task.apply_async(args=[deal_id, user_id])
        return jsonify({'job_id': task.id, 'status': 'pending'}), 202

    # Option 1: synchronous inline execution
    from app.models.deal import Deal
    from app.models.unit import Unit
    from app.services.multifamily.ai_comp_service import fetch_sale_comps

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
        comps = fetch_sale_comps(full_address, deal.unit_count, unit_mix)
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 502

    if not comps:
        return jsonify({'added': 0, 'message': 'Gemini returned no comps for this property.'}), 200

    service = SaleCompService()
    added = 0
    errors = []
    for comp in comps:
        # Use a savepoint so a failed insert doesn't roll back earlier successes
        try:
            sp = db.session.begin_nested()
            service.add_sale_comp(deal_id, comp)
            sp.commit()
            added += 1
        except (ValueError, KeyError) as exc:
            # Expected data-quality failures (missing/invalid fields from Gemini)
            sp.rollback()
            errors.append(str(exc))
        except Exception:
            # Unexpected error — roll back everything and propagate
            db.session.rollback()
            raise

    db.session.commit()

    return jsonify({
        'added': added,
        'skipped': len(errors),
        'message': f'Added {added} sale comp(s) from AI research.',
    }), 200


@multifamily_sale_comp_bp.route('/deals/<int:deal_id>/sale-comps/fetch-ai/status/<job_id>', methods=['GET'])
@handle_errors
def get_sale_comps_ai_job_status(deal_id, job_id):
    """Poll the status of an async AI sale comp fetch job.

    Returns:
      - status: 'pending' | 'running' | 'done' | 'failed'
      - added, skipped, message (when done)
      - error (when failed)

    Requirements: 4.1
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
        'cap_rate_min': _to_float(rollup['Cap_Rate_Min']),
        'cap_rate_median': _to_float(rollup['Cap_Rate_Median']),
        'cap_rate_average': _to_float(rollup['Cap_Rate_Average']),
        'cap_rate_max': _to_float(rollup['Cap_Rate_Max']),
        'ppu_min': _to_float(rollup['PPU_Min']),
        'ppu_median': _to_float(rollup['PPU_Median']),
        'ppu_average': _to_float(rollup['PPU_Average']),
        'ppu_max': _to_float(rollup['PPU_Max']),
        'comps': [_serialize_sale_comp(c) for c in rollup['comps']],
        'sale_comps_insufficient': bool(rollup['warnings']),
    }

    return jsonify(result), 200
