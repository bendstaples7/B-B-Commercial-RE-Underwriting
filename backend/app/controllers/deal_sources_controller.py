"""Deal source catalog API — list + create for Source dropdowns."""
from flask import Blueprint, g, jsonify, request

from app.api_utils import require_auth
from app.controllers.decorators import handle_errors
from app.services.deal_source_service import DealSourceService

deal_sources_bp = Blueprint('deal_sources', __name__)
_service = DealSourceService()


@deal_sources_bp.route('', methods=['GET'])
@handle_errors
@require_auth
def list_deal_sources():
    """GET /api/deal-sources — builtins + custom + historically used labels."""
    return jsonify({'sources': _service.list_sources()}), 200


@deal_sources_bp.route('', methods=['POST'])
@handle_errors
@require_auth
def create_deal_source():
    """POST /api/deal-sources — register a custom source from the dropdown."""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        raise ValueError('JSON body must be an object')
    payload = data or {}
    name = payload.get('name')
    actor = getattr(g, 'user_id', None)
    result = _service.create_source(name if isinstance(name, str) else str(name or ''), created_by=actor)
    status = 201 if result.get('created') else 200
    return jsonify(result), status
