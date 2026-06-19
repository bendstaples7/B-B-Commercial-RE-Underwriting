"""Task management API endpoints.

Flask Blueprint for Task CRUD and lifecycle operations.

Requirements: 3.1, 3.2, 3.3, 3.5
"""
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.exceptions import RealEstateAnalysisException
from app.schemas import TaskSchema, TaskAssociationSchema
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

task_bp = Blueprint('task', __name__)

_task_schema = TaskSchema()
_task_list_schema = TaskSchema(many=True)
_assoc_schema = TaskAssociationSchema(many=True)

_service = TaskService()


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across task endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RealEstateAnalysisException as e:
            logger.warning("Application error [%s]: %s", type(e).__name__, e.message)
            response = {'error': type(e).__name__, 'message': e.message}
            response.update(e.payload)
            return jsonify(response), e.status_code
        except ValidationError as e:
            logger.warning("Marshmallow validation error: %s", e.messages)
            return jsonify({
                'error': 'ValidationError',
                'message': 'Request data failed validation.',
                'details': e.messages,
            }), 400
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'InvalidRequest',
                'message': str(e),
            }), 400
        except Exception as e:
            logger.error("Unexpected error in task controller: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'InternalServerError',
                'message': 'An unexpected error occurred.',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_task(task):
    """Serialize a Task instance to a dict, including its associations."""
    data = _task_schema.dump(task)
    associations = task.associations.all()
    data['associations'] = _assoc_schema.dump(associations)
    return data


def _refresh_associated_leads(task):
    """Refresh lead_score + recommended_action for every lead this task touches.

    A Task may be linked to a lead via its direct ``lead_id`` FK and/or via
    ``TaskAssociation`` rows with ``target_type='lead'``. Open-task count feeds
    the action engine, so creating/updating/completing a task must refresh the
    affected lead(s). Uses the error-isolated ``refresh_lead_scoring`` helper.
    """
    from app.services.lead_refresh import refresh_lead_scoring

    lead_ids = set()
    direct = getattr(task, 'lead_id', None)
    if direct is not None:
        lead_ids.add(direct)
    try:
        for assoc in task.associations.all():
            if assoc.target_type == 'lead' and assoc.target_id is not None:
                lead_ids.add(assoc.target_id)
    except Exception:  # pragma: no cover — association load is best-effort
        logger.debug("Could not enumerate task associations for refresh", exc_info=True)

    for lead_id in lead_ids:
        refresh_lead_scoring(lead_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@task_bp.route('/', methods=['GET'])
@handle_errors
def list_tasks():
    """List tasks with optional filtering.

    Query parameters
    ----------------
    status        : str  — filter by task status (open/completed/cancelled/overdue)
    priority      : str  — filter by priority (high/medium/low)
    due_date_from : str  — ISO 8601 datetime; tasks with due_date >= this value
    due_date_to   : str  — ISO 8601 datetime; tasks with due_date <= this value
    target_type   : str  — filter by association target_type (lead/organization)
    target_id     : int  — filter by association target_id (requires target_type)
    page          : int  — 1-based page number (default 1)
    per_page      : int  — results per page (default 20)
    """
    args = request.args
    filters = {}

    if args.get('status'):
        filters['status'] = args['status']

    if args.get('priority'):
        filters['priority'] = args['priority']

    if args.get('due_date_from'):
        filters['due_date_from'] = datetime.fromisoformat(args['due_date_from'])

    if args.get('due_date_to'):
        filters['due_date_to'] = datetime.fromisoformat(args['due_date_to'])

    if args.get('target_type'):
        filters['target_type'] = args['target_type']

    if args.get('target_id'):
        try:
            filters['target_id'] = int(args['target_id'])
        except (TypeError, ValueError):
            return jsonify({
                'error': 'InvalidRequest',
                'message': 'target_id must be an integer.',
            }), 400

    try:
        page = int(args.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(args.get('per_page', 20))
    except (TypeError, ValueError):
        per_page = 20

    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    tasks, total = _service.list(filters=filters, page=page, per_page=per_page)

    return jsonify({
        'tasks': [_serialize_task(t) for t in tasks],
        'total': total,
        'page': page,
        'per_page': per_page,
    }), 200


@task_bp.route('/', methods=['POST'])
@handle_errors
def create_task():
    """Create a new task.

    Request body
    ------------
    title        : str  (required)
    body         : str  (optional)
    due_date     : str  ISO 8601 datetime (optional)
    status       : str  open/completed/cancelled/overdue (default: open)
    priority     : str  high/medium/low (default: medium)
    source       : str  manual/hubspot_import (default: manual)
    associations : list of {target_type, target_id} (optional)
    """
    body = request.json or {}
    data = _task_schema.load(body)

    # Parse associations from raw request body (task_id is not known yet,
    # so load with partial=True to skip the required task_id check).
    raw_associations = body.get('associations', [])
    assoc_schema = TaskAssociationSchema(many=True, partial=('task_id',))
    associations = assoc_schema.load(raw_associations) if raw_associations else []
    data['associations'] = associations

    task = _service.create(data)
    _refresh_associated_leads(task)
    return jsonify(_serialize_task(task)), 201


@task_bp.route('/<int:task_id>', methods=['GET'])
@handle_errors
def get_task(task_id):
    """Get a single task by ID.

    Applies overdue check on read (Requirement 3.6).
    """
    task = _service.get(task_id)
    return jsonify(_serialize_task(task)), 200


@task_bp.route('/<int:task_id>', methods=['PUT'])
@handle_errors
def update_task(task_id):
    """Update an existing task.

    Request body
    ------------
    title    : str  (optional)
    body     : str  (optional)
    due_date : str  ISO 8601 datetime (optional)
    status   : str  (optional)
    priority : str  (optional)
    """
    body = request.json or {}
    # Use partial=True so only provided fields are validated/updated
    data = _task_schema.load(body, partial=True)
    task = _service.update(task_id, data)
    _refresh_associated_leads(task)
    return jsonify(_serialize_task(task)), 200


@task_bp.route('/<int:task_id>', methods=['DELETE'])
@handle_errors
def delete_task(task_id):
    """Delete a task and its associations."""
    _service.delete(task_id)
    return jsonify({'message': f'Task {task_id} deleted successfully.'}), 200


@task_bp.route('/<int:task_id>/complete', methods=['POST'])
@handle_errors
def complete_task(task_id):
    """Mark a task as completed and record the completion timestamp.

    Requirement 3.2: WHEN a user marks a Task as completed, THE Platform
    SHALL record the completion timestamp.
    """
    task = _service.complete(task_id)
    _refresh_associated_leads(task)
    return jsonify(_serialize_task(task)), 200
