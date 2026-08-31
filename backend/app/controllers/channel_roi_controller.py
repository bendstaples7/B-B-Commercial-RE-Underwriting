"""Channel ROI API — marketing spend efficiency across Direct Mail and Facebook."""
from flask import Blueprint, jsonify, request

from app.api_utils import require_auth, require_admin
from app.controllers.decorators import handle_errors
from app.services.channel_roi_service import ChannelRoiService

channel_roi_bp = Blueprint('channel_roi', __name__)
_service = ChannelRoiService()


def _optional_number(data: dict, key: str) -> float | None:
    """Return float, None (explicit clear), or raise ValueError for bad input.

    Missing key is signalled by raising KeyError so callers can skip the field.
    """
    if key not in data:
        raise KeyError(key)
    raw = data[key]
    if raw is None or raw == '':
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{key} must be a number') from exc


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
    data = request.get_json()
    if data is not None and not isinstance(data, dict):
        raise ValueError('JSON body must be an object')
    data = data or {}
    kwargs: dict = {}
    try:
        kwargs['expected_profit_per_deal'] = _optional_number(data, 'expected_profit_per_deal')
    except KeyError:
        pass
    try:
        kwargs['assumed_close_rate'] = _optional_number(data, 'assumed_close_rate')
    except KeyError:
        pass
    if 'meta_ad_account_id' in data:
        raw = data['meta_ad_account_id']
        if raw is not None and not isinstance(raw, str):
            raise ValueError('meta_ad_account_id must be a string')
        kwargs['meta_ad_account_id'] = raw or ''
    if data.get('clear_meta_token'):
        kwargs['clear_meta_token'] = True
    elif data.get('meta_access_token'):
        token = data['meta_access_token']
        if not isinstance(token, str):
            raise ValueError('meta_access_token must be a string')
        kwargs['meta_access_token'] = token
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
