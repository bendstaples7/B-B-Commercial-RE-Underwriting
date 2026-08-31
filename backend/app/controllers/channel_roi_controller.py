"""Channel ROI API — marketing spend efficiency across Direct Mail and Facebook."""
from flask import Blueprint, jsonify, request

from app.api_utils import require_auth, require_admin
from app.controllers.decorators import handle_errors
from app.services.channel_roi_service import ChannelRoiService

channel_roi_bp = Blueprint('channel_roi', __name__)
_service = ChannelRoiService()


@channel_roi_bp.route('', methods=['GET'])
@handle_errors
@require_auth
def get_channel_roi():
    """GET /api/marketing/channel-roi — rollup + per-campaign breakdowns."""
    return jsonify(_service.get_dashboard()), 200


@channel_roi_bp.route('/settings', methods=['GET'])
@handle_errors
@require_auth
def get_settings():
    return jsonify(_service.settings_public()), 200


@channel_roi_bp.route('/settings', methods=['PATCH'])
@handle_errors
@require_auth
@require_admin
def patch_settings():
    """Admin-only: update projection knobs and/or Meta credentials."""
    data = request.get_json() or {}
    kwargs: dict = {}
    if 'expected_profit_per_deal' in data and data['expected_profit_per_deal'] is not None:
        kwargs['expected_profit_per_deal'] = data['expected_profit_per_deal']
    if 'assumed_close_rate' in data and data['assumed_close_rate'] is not None:
        kwargs['assumed_close_rate'] = data['assumed_close_rate']
    if 'meta_ad_account_id' in data:
        kwargs['meta_ad_account_id'] = data['meta_ad_account_id'] or ''
    if data.get('clear_meta_token'):
        kwargs['clear_meta_token'] = True
    elif data.get('meta_access_token'):
        kwargs['meta_access_token'] = data['meta_access_token']
    config = _service.update_settings(**kwargs)
    return jsonify(_service.settings_public(config)), 200


@channel_roi_bp.route('/sync', methods=['POST'])
@handle_errors
@require_auth
@require_admin
def sync_meta():
    """Admin-only: pull Facebook campaigns + spend from Meta."""
    result = _service.sync_facebook_campaigns()
    return jsonify(result), 200


@channel_roi_bp.route('/facebook-campaigns', methods=['GET'])
@handle_errors
@require_auth
def list_facebook_campaigns():
    """Campaigns available for call-log attribution."""
    return jsonify({'campaigns': _service.list_facebook_campaigns_for_attribution()}), 200
