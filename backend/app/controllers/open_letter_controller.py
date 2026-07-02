"""Open Letter Connect configuration and catalog API."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.api_utils import require_auth
from app.controllers.mail_api_errors import handle_mail_api_errors as handle_errors
from app.controllers.request_parsing import parse_positive_int
from app.services.open_letter_config_service import OpenLetterConfigService
open_letter_bp = Blueprint('open_letter', __name__)

_config_service = OpenLetterConfigService()


@open_letter_bp.route('/config', methods=['GET'])
@require_auth
@handle_errors
def get_config():
    user_id = g.user_id
    return jsonify(_config_service.serialize_public(user_id)), 200


@open_letter_bp.route('/config', methods=['POST'])
@require_auth
@handle_errors
def save_config():
    user_id = g.user_id
    data = request.get_json(silent=True) or {}
    config = _config_service.save_config(
        user_id,
        api_token=data.get('api_token'),
        use_demo_api=data.get('use_demo_api'),
        default_product_id=data.get('default_product_id'),
        default_template_id=data.get('default_template_id'),
        default_template_name=data.get('default_template_name'),
        batch_minimum=data.get('batch_minimum'),
        allow_send_below_minimum=data.get('allow_send_below_minimum'),
        return_address=data.get('return_address'),
        estimated_cost_per_piece=data.get('estimated_cost_per_piece'),
    )
    return jsonify(_config_service.serialize_public(user_id)), 200


@open_letter_bp.route('/config/test', methods=['POST'])
@require_auth
@handle_errors
def test_config():
    client = _config_service.get_client(g.user_id)
    result = client.test_connection()
    return jsonify(result), 200


@open_letter_bp.route('/products', methods=['GET'])
@require_auth
@handle_errors
def list_products():
    client = _config_service.get_client(g.user_id)
    result = client.list_products()
    return jsonify(result), 200


@open_letter_bp.route('/templates', methods=['GET'])
@require_auth
@handle_errors
def list_templates():
    client = _config_service.get_client(g.user_id)
    try:
        page = parse_positive_int(request.args.get('page'), default=0, minimum=0, field_name='page')
        page_size = parse_positive_int(
            request.args.get('page_size'), default=50, maximum=100, field_name='page_size',
        )
    except ValueError as exc:
        return jsonify({'error': 'Invalid request', 'message': str(exc)}), 400
    product_types = request.args.get('product_types') or None
    result = client.list_templates(
        page=page, page_size=page_size, product_types=product_types,
    )
    return jsonify(result), 200
