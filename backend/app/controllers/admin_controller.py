"""Admin API endpoints — cross-user visibility for admin users.

All routes are read-only and require both authentication and admin status.
Blueprint is registered at prefix ``/api/admin`` in ``app/__init__.py``.
"""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request

from app.api_utils import require_auth, require_admin
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.admin_service import AdminService

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across admin endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except NotFoundError as e:
            logger.warning("Not found: %s", e.message)
            return jsonify({
                'error': 'Not found',
                'message': e.message,
            }), 404
        except ValidationError as e:
            logger.warning("Validation error: %s", e.message)
            return jsonify({
                'error': 'Validation error',
                'message': e.message,
            }), 400
        except ConflictError as e:
            logger.warning("Conflict: %s", e.message)
            return jsonify({
                'error': 'Conflict',
                'message': e.message,
            }), 409
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code

            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@admin_bp.route('/users', methods=['GET'])
@handle_errors
@require_auth
@require_admin
def list_users():
    """Return all registered users ordered by created_at ascending.

    Returns a JSON array of user objects. Credential fields (password_hash)
    are never included.

    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    users = AdminService().list_users()
    return jsonify(users), 200


@admin_bp.route('/users/<user_id>/summary', methods=['GET'])
@handle_errors
@require_auth
@require_admin
def get_user_summary(user_id):
    """Return a user's profile plus activity counts.

    Returns a JSON object with user fields and lead_count,
    marketing_list_count, import_job_count.

    Returns 404 if the user_id does not exist.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
    """
    summary = AdminService().get_user_summary(user_id)
    return jsonify(summary), 200


@admin_bp.route('/leads', methods=['GET'])
@handle_errors
@require_auth
@require_admin
def list_leads():
    """Return a paginated list of leads across all users.

    Query parameters:
        owner_user_id (str, optional): Filter leads by owner.
        page (int, default 1): Page number (1-based).
        page_size (int, default 50): Results per page (max 200).

    Returns a paginated envelope with leads, total_count, page, page_size.
    Returns 400 if page_size exceeds 200.

    Requirements: 5.1, 5.2, 5.3, 5.4
    """
    owner_user_id = request.args.get('owner_user_id', None) or None

    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1

    try:
        page_size = int(request.args.get('page_size', 50))
    except (ValueError, TypeError):
        page_size = 50

    result = AdminService().list_leads(
        owner_user_id=owner_user_id,
        page=page,
        page_size=page_size,
    )
    return jsonify(result), 200


@admin_bp.route('/users/<user_id>/reset-password', methods=['POST'])
@handle_errors
@require_auth
@require_admin
def reset_user_password(user_id):
    """Reset a user's password. Admin-only.

    Request body (JSON):
        new_password: str (required, min 8 chars)

    Returns 200 {"message": "Password reset successfully."}
    Returns 400 if password too short or admin trying to reset own password.
    Returns 403 if not admin.
    Returns 404 if user not found.

    Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
    """
    body = request.get_json(silent=True) or {}
    new_password = body.get('new_password', '')
    AdminService().reset_user_password(user_id, new_password, g.user_id)
    return jsonify({'message': 'Password reset successfully.'}), 200


@admin_bp.route('/users/<user_id>', methods=['PATCH'])
@handle_errors
@require_auth
@require_admin
def update_user(user_id):
    """Update a user's display_name and/or email. Admin-only.

    Request body (JSON):
        display_name: str (optional)
        email: str (optional)

    Returns 200 with updated user object.
    Returns 400 if neither field provided or validation fails.
    Returns 403 if not admin.
    Returns 404 if user not found.
    Returns 409 if new email already in use.

    Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
    """
    body = request.get_json(silent=True) or {}
    display_name = body.get('display_name', None)
    email = body.get('email', None)
    result = AdminService().update_user(user_id, display_name, email)
    return jsonify(result), 200


@admin_bp.route('/background-jobs', methods=['GET'])
@handle_errors
@require_auth
@require_admin
def get_background_jobs():
    """Return Celery active/reserved/queued work, HubSpot pipeline stage, mail in-flight.

    Admin-only. Used by ``/admin/background-jobs``.
    """
    from app.services.background_jobs_service import get_background_jobs_snapshot

    return jsonify(get_background_jobs_snapshot()), 200
