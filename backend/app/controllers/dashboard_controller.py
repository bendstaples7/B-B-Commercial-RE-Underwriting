"""CRM activity dashboard API — counts and goals for the logged-in user."""
from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import Unauthorized

from app.api_utils import require_auth
from app.controllers.decorators import handle_errors
from app.services.activity_dashboard_service import (
    PERIOD_ALIASES,
    ActivityDashboardService,
)

dashboard_bp = Blueprint('dashboard', __name__)
_service = ActivityDashboardService()


def _require_authenticated_user() -> str:
    user_id = getattr(g, 'user_id', None)
    if not user_id or user_id == 'anonymous':
        raise Unauthorized('Authentication required')
    return user_id


@dashboard_bp.route('/activity', methods=['GET'])
@handle_errors
@require_auth
def get_activity():
    """Return activity counts and goals for the current user.

    Query params:
      period — ``week`` (default) or ``month``
    """
    user_id = _require_authenticated_user()
    period = request.args.get('period', 'week')
    payload = _service.get_activity(user_id, period=period)
    return jsonify(payload), 200


@dashboard_bp.route('/goals', methods=['PUT'])
@handle_errors
@require_auth
def put_goals():
    """Upsert weekly or monthly goal targets for the current user.

    Body::
        {
          "period_type": "weekly" | "monthly",
          "targets": { "calls": 50, "mailers": null, ... }
        }

    A ``null`` target clears that metric's goal.
    """
    user_id = _require_authenticated_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Request body must be a JSON object')
    period_type = data.get('period_type')
    targets = data.get('targets')
    if period_type is not None and not isinstance(period_type, str):
        raise ValueError("period_type must be a string ('weekly' or 'monthly')")
    if targets is not None and not isinstance(targets, dict):
        raise ValueError('targets must be an object')
    goals = _service.upsert_goals(user_id, period_type, targets)
    normalized = PERIOD_ALIASES.get((period_type or '').strip().lower(), period_type)
    return jsonify({
        'period_type': normalized,
        'goals': goals,
    }), 200
