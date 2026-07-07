"""Queue API endpoints for the Actionable Lead Command Center."""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

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


def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({'error': 'Validation error', 'details': e.messages}), 400
        except ValueError as e:
            return jsonify({'error': 'Invalid request', 'message': str(e)}), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                return jsonify({'error': getattr(e, 'name', 'HTTP error'), 'message': e.description}), e.code
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({'error': 'Internal server error', 'message': 'An unexpected error occurred'}), 500
    return decorated_function


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
