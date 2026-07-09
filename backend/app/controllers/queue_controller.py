"""Queue API endpoints for the Actionable Lead Command Center."""
import logging

from flask import Blueprint, g, jsonify, request

from app.controllers.decorators import handle_errors
from app.services.mail_queue_service import MailQueueService
from app.services.prospect_review_service import count_pending_candidates
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

queue_bp = Blueprint('queue', __name__)


def _get_queue_service():
    """Return a QueueService scoped to the current user.

    Non-admin users only see leads they own.  Admins see all leads.
    Requests without a valid authenticated user_id are rejected with 401.
    """
    from flask import abort
    from app.models.user import User
    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        abort(401)
    user = User.query.filter_by(user_id=user_id).first()
    is_admin = bool(user and user.is_admin)
    owner_filter = None if is_admin else user_id
    return QueueService(owner_user_id=owner_filter)


def _parse_pagination_params():
    """Parse common pagination and sort params from request.args."""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    sort_by = request.args.get('sort_by', 'lead_score')
    sort_order = request.args.get('sort_order', 'desc')
    return page, per_page, sort_by, sort_order


@queue_bp.route('/counts', methods=['GET'])
@handle_errors
def get_counts():
    """GET /api/queues/counts — returns badge counts for all queues."""
    user_id = getattr(g, 'user_id', None)
    svc = _get_queue_service()
    counts = svc.get_counts()
    if user_id and user_id != 'anonymous':
        from app.models.user import User
        user = User.query.filter_by(user_id=user_id).first()
        is_admin = bool(user and user.is_admin)
        mail = MailQueueService().get_summary(user_id)
        counts['ready_to_mail'] = mail['queued_count']
        counts['mail_candidates'] = svc.count_mail_candidates(user_id)
        counts['prospect_candidates'] = count_pending_candidates(user_id, is_admin=is_admin)
    else:
        counts['ready_to_mail'] = 0
        counts['mail_candidates'] = 0
        counts['prospect_candidates'] = 0
    return jsonify(counts), 200


@queue_bp.route('/todays-action', methods=['GET'])
@handle_errors
def get_todays_action():
    """GET /api/queues/todays-action — paginated Today's Action queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_todays_action(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/previously-warm', methods=['GET'])
@handle_errors
def get_previously_warm():
    """GET /api/queues/previously-warm — paginated Previously Warm queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_previously_warm(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/follow-up-overdue', methods=['GET'])
@handle_errors
def get_follow_up_overdue():
    """GET /api/queues/follow-up-overdue — paginated Follow-Up Overdue queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_follow_up_overdue(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/no-next-action', methods=['GET'])
@handle_errors
def get_no_next_action():
    """GET /api/queues/no-next-action — paginated No Next Action queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_no_next_action(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/no-next-action/status-counts', methods=['GET'])
@handle_errors
def get_no_next_action_status_counts():
    """GET /api/queues/no-next-action/status-counts — counts by lead_status."""
    counts = _get_queue_service().get_no_next_action_status_counts()
    return jsonify(counts), 200


@queue_bp.route('/no-next-action/lead-ids', methods=['GET'])
@handle_errors
def get_no_next_action_lead_ids():
    """GET /api/queues/no-next-action/lead-ids?lead_status= — ids in queue for status."""
    lead_status = request.args.get('lead_status')
    if not lead_status:
        raise ValueError('lead_status is required')
    ids = _get_queue_service().get_no_next_action_lead_ids_by_status(lead_status)
    return jsonify({'lead_ids': ids, 'total': len(ids)}), 200


@queue_bp.route('/no-next-action/bulk-update-status', methods=['POST'])
@handle_errors
def bulk_update_no_next_action_status():
    """POST /api/queues/no-next-action/bulk-update-status — queue-wide status update."""
    from app.api_utils import require_auth
    body = request.get_json() or {}
    source_status = body.get('source_status')
    target_status = body.get('status') or body.get('target_status')
    reason = body.get('reason') or ''
    if not source_status or not target_status:
        raise ValueError('source_status and status are required')
    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        from flask import abort
        abort(401)
    result = _get_queue_service().bulk_update_no_next_action_status(
        source_status, target_status, reason=reason, actor=user_id,
    )
    return jsonify(result), 200


@queue_bp.route('/needs-review', methods=['GET'])
@handle_errors
def get_needs_review():
    """GET /api/queues/needs-review — paginated Needs Review queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_needs_review(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/do-not-contact', methods=['GET'])
@handle_errors
def get_do_not_contact():
    """GET /api/queues/do-not-contact — paginated Do Not Contact queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_do_not_contact(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/missing-property-match', methods=['GET'])
@handle_errors
def get_missing_property_match():
    """GET /api/queues/missing-property-match — paginated Missing Property Match queue."""
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_missing_property_match(page, per_page, sort_by, sort_order)
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/mail-candidates', methods=['GET'])
@handle_errors
def get_mail_candidates():
    """GET /api/queues/mail-candidates — paginated mail-ready leads not yet staged."""
    from flask import abort
    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        abort(401)
    page, per_page, sort_by, sort_order = _parse_pagination_params()
    rows, total = _get_queue_service().get_mail_candidates(
        user_id, page, per_page, sort_by, sort_order,
    )
    return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page}), 200


@queue_bp.route('/<queue_key>/navigation', methods=['GET'])
@handle_errors
def get_queue_navigation(queue_key: str):
    """GET /api/queues/<queue_key>/navigation?lead_id= — neighbors for HubSpot-style queue work."""
    from flask import abort

    lead_id_raw = request.args.get('lead_id')
    if lead_id_raw is None:
        raise ValueError('lead_id is required')
    try:
        lead_id = int(lead_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError('lead_id must be an integer') from exc

    sort_by = request.args.get('sort_by') or None
    sort_order = request.args.get('sort_order') or None
    user_id = getattr(g, 'user_id', None)
    mail_user_id = user_id if queue_key == 'mail-candidates' else None

    try:
        payload = _get_queue_service().get_navigation(
            queue_key,
            lead_id,
            sort_by=sort_by,
            sort_order=sort_order,
            mail_user_id=mail_user_id,
        )
    except ValueError as exc:
        if str(exc).startswith('Unknown queue key'):
            abort(404)
        raise
    return jsonify(payload), 200
