"""Prospect candidate review queue API."""
import logging
from functools import wraps
from typing import Optional

from flask import Blueprint, g, jsonify, request

from app.services.cook_county_prospect_config import motivation_pct
from app.services.prospect_area_filter_service import (
    clear_area_filter,
    get_area_filter,
    save_area_filter,
    serialize_area_filter,
)
from app.services.prospect_review_service import (
    approve_candidate,
    count_pending_candidates,
    get_prospect_feed_status,
    list_candidates,
    reject_candidate,
)

logger = logging.getLogger(__name__)

prospect_bp = Blueprint('prospects', __name__)


def handle_errors(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            logger.error('Prospect API error: %s', exc, exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500
    return decorated


def _user_id():
    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        return None
    return user_id


def _is_admin() -> bool:
    from app.controllers.property_controller import _current_user_is_admin
    return _current_user_is_admin()


@prospect_bp.route('/candidates/count', methods=['GET'])
@handle_errors
def get_candidate_count():
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    from app.services.prospect_review_service import _fetch_eligible_candidates
    from app.services.prospect_area_filter_service import apply_area_filter_to_candidates

    rows = _fetch_eligible_candidates(user_id, status='pending', is_admin=_is_admin())
    _, stats = apply_area_filter_to_candidates(rows, user_id)
    payload = {'prospect_candidates': stats.total_filtered}
    payload.update(stats.as_dict())
    return jsonify(payload), 200


@prospect_bp.route('/candidates', methods=['GET'])
@handle_errors
def get_candidates():
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    status = request.args.get('status', 'pending')
    min_score = float(request.args.get('min_score', 0))
    rows, total, area_filter = list_candidates(
        user_id,
        status=status,
        page=page,
        per_page=per_page,
        min_score=min_score,
        is_admin=_is_admin(),
    )
    return jsonify({
        'rows': [_serialize_candidate(row) for row in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        'area_filter': area_filter,
    }), 200


@prospect_bp.route('/candidates/<int:candidate_id>', methods=['GET'])
@handle_errors
def get_candidate(candidate_id: int):
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    from app.models.motivation_signal import ProspectCandidate
    candidate = ProspectCandidate.query.filter_by(id=candidate_id).first()
    if candidate is None:
        return jsonify({'error': 'Not found'}), 404
    if not _is_admin() and candidate.owner_user_id != user_id:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(_serialize_candidate(candidate, include_raw=True)), 200


@prospect_bp.route('/status', methods=['GET'])
@handle_errors
def get_feed_status():
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(get_prospect_feed_status()), 200


@prospect_bp.route('/area-filter', methods=['GET'])
@handle_errors
def get_area_filter_config():
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(serialize_area_filter(get_area_filter(user_id))), 200


@prospect_bp.route('/area-filter', methods=['PUT'])
@handle_errors
def put_area_filter_config():
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    if body.get('clear'):
        clear_area_filter(user_id)
        return jsonify(serialize_area_filter(get_area_filter(user_id))), 200
    row = save_area_filter(
        user_id,
        enabled=bool(body.get('enabled', False)),
        geometry=body.get('geometry'),
        label=body.get('label'),
    )
    return jsonify(serialize_area_filter(row)), 200


@prospect_bp.route('/sync', methods=['POST'])
@handle_errors
def sync_feeds():
    """Pull Cook County prospect feeds now (same job as nightly Celery task)."""
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    from app.services.cook_county_prospect_config import resolve_cook_county_prospect_owner_user_id
    from app.services.cook_county_prospect_feed_service import sync_all_prospect_feeds

    owner_user_id = resolve_cook_county_prospect_owner_user_id()
    if owner_user_id != user_id:
        logger.info(
            'Prospect sync requested by %s; feeds assign to owner %s',
            user_id,
            owner_user_id,
        )
    summary = sync_all_prospect_feeds(owner_user_id)
    pending = count_pending_candidates(user_id, is_admin=_is_admin())
    status = get_prospect_feed_status()
    return jsonify({
        'summary': summary,
        'prospect_candidates': pending,
        'owner_user_id': owner_user_id,
        'last_sync_at': status['last_sync_at'],
    }), 200


@prospect_bp.route('/candidates/<int:candidate_id>/approve', methods=['POST'])
@handle_errors
def approve(candidate_id: int):
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    result = approve_candidate(candidate_id, user_id, reviewer_id=user_id, is_admin=_is_admin())
    return jsonify(result), 200


@prospect_bp.route('/candidates/<int:candidate_id>/reject', methods=['POST'])
@handle_errors
def reject(candidate_id: int):
    user_id = _user_id()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    candidate = reject_candidate(
        candidate_id,
        user_id,
        reviewer_id=user_id,
        reason=body.get('reason', ''),
        is_admin=_is_admin(),
    )
    return jsonify(_serialize_candidate(candidate)), 200


def _location_hint(candidate) -> Optional[str]:
    if candidate.property_street:
        return None
    raw = candidate.raw_record or {}
    return (raw.get('township_name') or raw.get('township') or '').strip() or None


def _serialize_candidate(candidate, include_raw: bool = False) -> dict:
    payload = {
        'id': candidate.id,
        'pin': candidate.pin,
        'property_street': candidate.property_street,
        'property_city': candidate.property_city,
        'property_state': candidate.property_state,
        'latitude': candidate.latitude,
        'longitude': candidate.longitude,
        'location_hint': _location_hint(candidate),
        'primary_signal_type': candidate.primary_signal_type,
        'motivation_score': candidate.motivation_score,
        'motivation_pct': motivation_pct(candidate.motivation_score),
        'signals': candidate.signals,
        'source_feed': candidate.source_feed,
        'status': candidate.status,
        'duplicate_lead_id': candidate.duplicate_lead_id,
        'imported_lead_id': candidate.imported_lead_id,
        'created_at': candidate.created_at.isoformat() + 'Z' if candidate.created_at else None,
        'reviewed_at': candidate.reviewed_at.isoformat() + 'Z' if candidate.reviewed_at else None,
    }
    if include_raw:
        payload['raw_record'] = candidate.raw_record
    return payload
