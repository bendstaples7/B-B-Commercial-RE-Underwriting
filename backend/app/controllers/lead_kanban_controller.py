"""LeadKanbanController — REST endpoints for the lead-based kanban board."""

import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.exceptions import RealEstateAnalysisException
from app.services.lead_kanban_service import LeadKanbanService

logger = logging.getLogger(__name__)

lead_kanban_bp = Blueprint("lead_kanban", __name__)
_service = LeadKanbanService()


# ---------------------------------------------------------------------------
# Shared error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Consistent error-handling decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({"error": "Validation error", "details": e.messages}), 400
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({"error": str(e)}), 400
        except RealEstateAnalysisException as e:
            logger.warning("Application error [%s]: %s", e.status_code, e.message)
            return jsonify({"error": e.message, **e.payload}), e.status_code
        except Exception as e:
            if hasattr(e, "code") and hasattr(e, "description"):
                return jsonify({"error": getattr(e, "name", "HTTP error"), "message": e.description}), e.code
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({"error": "Internal server error", "message": "An unexpected error occurred"}), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@lead_kanban_bp.route("/api/kanban/leads", methods=["GET"])
@handle_errors
def get_kanban_leads():
    """Return kanban columns with leads grouped by recommended_action.

    Query parameters:
        limit (int, optional): max leads per column, default 50, max 200.
        column_id (str, optional): expand a specific column (returns all its leads).
    """
    limit = request.args.get("limit", 50, type=int)
    column_id = request.args.get("column_id", None, type=str)

    # Clamp limit to max 200
    if limit < 0:
        limit = 50
    if limit > 200:
        limit = 200

    result = _service.get_columns(limit=limit, column_id=column_id)
    return jsonify(result), 200


@lead_kanban_bp.route("/api/kanban/leads/<int:lead_id>/move", methods=["PATCH"])
@handle_errors
def move_kanban_lead(lead_id: int):
    """Move a lead to a different recommended_action column."""
    data = request.get_json(silent=True) or {}
    target_action = data.get("target_action")
    if not target_action:
        return jsonify({"error": "Missing required field: target_action"}), 400

    lead = _service.move_lead(lead_id, target_action)
    return jsonify({"lead": lead}), 200