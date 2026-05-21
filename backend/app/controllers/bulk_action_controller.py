"""Bulk Action API endpoints for the Actionable Lead Command Center."""
import logging
from functools import wraps
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g
from marshmallow import ValidationError

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.schemas import BulkActionRequestSchema, BulkActionResultSchema
from app.services.lead_task_service import LeadTaskService

logger = logging.getLogger(__name__)

bulk_action_bp = Blueprint('bulk_action', __name__)
_lead_task_service = LeadTaskService()


def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({'error': 'Validation error', 'details': e.messages}), 400
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({'error': 'Internal server error', 'message': str(e)}), 500
    return decorated_function


@bulk_action_bp.route('/suppress', methods=['POST'])
@handle_errors
def bulk_suppress():
    """POST /api/leads/bulk/suppress — suppress multiple leads."""
    data = BulkActionRequestSchema().load(request.get_json() or {})
    lead_ids = data['lead_ids']
    actor = getattr(g, 'user_id', 'anonymous')

    successes = 0
    failures = 0

    for lead_id in lead_ids:
        try:
            lead = Lead.query.get(lead_id)
            if lead is None:
                failures += 1
                continue
            old_status = lead.lead_status
            lead.lead_status = 'suppressed'
            lead.recommended_action = None
            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type='status_changed',
                occurred_at=datetime.now(timezone.utc),
                source='manual',
                actor=actor,
                summary="Lead suppressed (bulk action).",
                event_metadata={'previous_status': old_status, 'new_status': 'suppressed'},
            )
            db.session.add(lead)
            db.session.add(entry)
            db.session.commit()
            successes += 1
        except Exception:
            db.session.rollback()
            failures += 1

    return jsonify({'successes': successes, 'failures': failures}), 200


@bulk_action_bp.route('/create-task', methods=['POST'])
@handle_errors
def bulk_create_task():
    """POST /api/leads/bulk/create-task — create a task for multiple leads."""
    body = request.get_json() or {}
    lead_ids = body.get('lead_ids', [])
    task_data = body.get('task_data', {})
    actor = getattr(g, 'user_id', 'anonymous')

    if not lead_ids:
        return jsonify({'error': 'lead_ids is required'}), 400

    successes = 0
    failures = 0

    for lead_id in lead_ids:
        try:
            _lead_task_service.create(lead_id, task_data, actor=actor)
            successes += 1
        except Exception:
            failures += 1

    return jsonify({'successes': successes, 'failures': failures}), 200


@bulk_action_bp.route('/do-not-contact', methods=['POST'])
@handle_errors
def bulk_do_not_contact():
    """POST /api/leads/bulk/do-not-contact — mark multiple leads as DNC."""
    data = BulkActionRequestSchema().load(request.get_json() or {})
    lead_ids = data['lead_ids']
    actor = getattr(g, 'user_id', 'anonymous')

    successes = 0
    failures = 0

    for lead_id in lead_ids:
        try:
            lead = Lead.query.get(lead_id)
            if lead is None:
                failures += 1
                continue
            old_status = lead.lead_status
            lead.lead_status = 'do_not_contact'
            lead.recommended_action = None
            LeadTask.query.filter_by(lead_id=lead_id, status='open').update({'status': 'cancelled'})
            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type='status_changed',
                occurred_at=datetime.now(timezone.utc),
                source='manual',
                actor=actor,
                summary="Lead marked Do Not Contact (bulk action).",
                event_metadata={'previous_status': old_status, 'new_status': 'do_not_contact'},
            )
            db.session.add(lead)
            db.session.add(entry)
            db.session.commit()
            successes += 1
        except Exception:
            db.session.rollback()
            failures += 1

    return jsonify({'successes': successes, 'failures': failures}), 200
