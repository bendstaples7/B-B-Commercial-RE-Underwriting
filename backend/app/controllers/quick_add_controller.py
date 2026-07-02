"""Quick-add API — POST /api/leads/quick-add, GET /api/leads/quick-add/lookup"""
import logging

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

from app import limiter
from app.api_utils import require_auth
from app.exceptions import RealEstateAnalysisException
from app.schemas import QuickAddLookupSchema, QuickAddSchema
from app.services.hubspot_writeback_service import hubspot_write_back_enabled
from app.services.quick_add_service import QuickAddService

logger = logging.getLogger(__name__)

quick_add_bp = Blueprint('quick_add', __name__)
_service = QuickAddService()


def handle_errors(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as exc:
            return jsonify({'error': 'Validation error', 'messages': exc.messages}), 400
        except ValueError as exc:
            return jsonify({'error': 'Validation error', 'message': str(exc)}), 400
        except RealEstateAnalysisException as exc:
            return jsonify({'error': exc.message, **getattr(exc, 'payload', {})}), exc.status_code
        except Exception:
            logger.exception('Quick-add error')
            return jsonify({'error': 'Internal server error'}), 500

    return wrapper


@quick_add_bp.route('/quick-add/lookup', methods=['GET'])
@require_auth
@limiter.limit('60 per minute')
@handle_errors
def quick_add_lookup():
    """Address-focused lookup for existing leads before quick-add submit."""
    params = QuickAddLookupSchema().load(request.args)
    matches = _service.lookup_existing_leads(
        user_id=g.user_id,
        query=params['q'],
        limit=params.get('limit', 5),
    )
    return jsonify({'matches': matches})


@quick_add_bp.route('/quick-add', methods=['POST'])
@require_auth
@limiter.limit('30 per minute')
@handle_errors
def quick_add_lead():
    """Create a lead from the mobile quick-add workflow."""
    data = QuickAddSchema().load(request.get_json() or {})
    user_id = g.user_id

    lead, created = _service.create_lead(
        user_id=user_id,
        property_street=data['property_street'],
        note=data.get('note'),
        priority=data.get('priority'),
        deal_source=data.get('deal_source'),
        date_identified=data.get('date_identified'),
        capture_latitude=data.get('capture_latitude'),
        capture_longitude=data.get('capture_longitude'),
        capture_location_label=data.get('capture_location_label'),
    )

    write_back_enabled = hubspot_write_back_enabled()
    if not write_back_enabled:
        hubspot_push_status = 'disabled'
    else:
        hubspot_push_status = 'queued'
        try:
            from celery_worker import run_quick_add_followup
            run_quick_add_followup.delay(lead.id)
        except Exception as exc:
            logger.warning('Could not enqueue quick-add followup for lead %s: %s', lead.id, exc)
            hubspot_push_status = 'queue_failed'

    return jsonify({
        'lead_id': lead.id,
        'created': created,
        'property_street': lead.property_street,
        'lead_status': lead.lead_status,
        'deal_source': lead.deal_source,
        'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
        'hubspot_push_status': hubspot_push_status,
        'hubspot_write_back_enabled': write_back_enabled,
    }), 201
