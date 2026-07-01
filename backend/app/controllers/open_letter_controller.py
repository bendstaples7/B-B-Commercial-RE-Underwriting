"""Open Letter Connect configuration and catalog API."""
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

from app.api_utils import require_auth
from app.exceptions import MailQueueError, RealEstateAnalysisException
from app.services.open_letter_config_service import OpenLetterConfigService

logger = logging.getLogger(__name__)

open_letter_bp = Blueprint('open_letter', __name__)

_config_service = OpenLetterConfigService()


def handle_errors(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({'error': 'Validation error', 'details': e.messages}), 400
        except MailQueueError as e:
            return jsonify({'error': 'Mail queue error', 'message': e.message}), e.status_code
        except RealEstateAnalysisException as e:
            return jsonify({'error': 'Application error', 'message': e.message, **e.payload}), e.status_code
        except ValueError as e:
            return jsonify({'error': 'Invalid request', 'message': str(e)}), 400
        except Exception as e:
            logger.error('Open Letter API error: %s', e, exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500
    return decorated


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
    data = request.get_json() or {}
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
    page = max(0, int(request.args.get('page', 0)))
    page_size = int(request.args.get('page_size', 50))
    product_types = request.args.get('product_types') or None
    result = client.list_templates(
        page=page, page_size=page_size, product_types=product_types,
    )
    return jsonify(result), 200
