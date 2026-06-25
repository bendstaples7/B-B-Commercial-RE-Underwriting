"""Interaction and Timeline API endpoints.

Provides CRUD endpoints for Interaction records and unified timeline
endpoints for leads and organizations.

Blueprints
----------
interaction_bp : Blueprint
    Prefix ``/api/interactions`` — CRUD for Interaction records.
timeline_bp : Blueprint
    No prefix — timeline endpoints at their canonical paths:
    ``/api/leads/<lead_id>/interaction-timeline`` and
    ``/api/organizations/<org_id>/timeline``.

Requirements: 2.1, 2.2, 2.3, 4.1, 4.4
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.exceptions import RealEstateAnalysisException
from app.services.interaction_service import InteractionService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------

interaction_bp = Blueprint('interaction', __name__)
timeline_bp = Blueprint('timeline', __name__)

# ---------------------------------------------------------------------------
# Service instance
# ---------------------------------------------------------------------------

_interaction_service = InteractionService()

# ---------------------------------------------------------------------------
# Error-handling decorator
# ---------------------------------------------------------------------------


def handle_errors(f):
    """Decorator for consistent JSON error handling on all routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RealEstateAnalysisException as exc:
            logger.warning(
                "%s: %s", exc.__class__.__name__, exc.message,
                extra={'payload': exc.payload},
            )
            response = {
                'success': False,
                'error': {
                    'message': exc.message,
                    'status_code': exc.status_code,
                    **exc.payload,
                },
            }
            return jsonify(response), exc.status_code
        except ValidationError as exc:
            logger.warning("Marshmallow validation error: %s", exc.messages)
            return jsonify({
                'success': False,
                'error': {
                    'message': 'Request validation failed',
                    'status_code': 400,
                    'error_type': 'validation_error',
                    'validation_errors': exc.messages,
                },
            }), 400
        except ValueError as exc:
            logger.warning("Value error: %s", str(exc))
            return jsonify({
                'success': False,
                'error': {
                    'message': str(exc),
                    'status_code': 400,
                    'error_type': 'invalid_request',
                },
            }), 400
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unexpected error in interaction controller: %s", str(exc))
            return jsonify({
                'success': False,
                'error': {
                    'message': 'An unexpected error occurred',
                    'status_code': 500,
                    'error_type': 'internal_server_error',
                },
            }), 500
    return decorated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_interaction(interaction):
    """Serialize an Interaction (with associations) to a dict."""
    associations = []
    try:
        assoc_query = interaction.associations.all()
        associations = [
            {
                'id': a.id,
                'interaction_id': a.interaction_id,
                'target_type': a.target_type,
                'target_id': a.target_id,
            }
            for a in assoc_query
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    return {
        'id': interaction.id,
        'interaction_type': interaction.interaction_type,
        'body': interaction.body,
        'occurred_at': interaction.occurred_at.isoformat() if interaction.occurred_at else None,
        'source': interaction.source,
        'hubspot_engagement_id': interaction.hubspot_engagement_id,
        'is_orphaned': interaction.is_orphaned,
        'created_at': interaction.created_at.isoformat() if interaction.created_at else None,
        'updated_at': interaction.updated_at.isoformat() if interaction.updated_at else None,
        'associations': associations,
    }


def _parse_pagination(args):
    """Extract and clamp pagination parameters from query string."""
    try:
        page = max(1, int(args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(int(args.get('per_page', 20)), 100))
    except (TypeError, ValueError):
        per_page = 20
    return page, per_page


# ---------------------------------------------------------------------------
# Interaction CRUD routes  (prefix: /api/interactions)
# ---------------------------------------------------------------------------


@interaction_bp.route('/', methods=['GET'])
@handle_errors
def list_interactions():
    """List interactions, optionally filtered by target_type and/or target_id.

    Query parameters
    ----------------
    target_type : str — filter by association target_type (lead/organization/contact)
    target_id   : int — filter by association target_id (requires target_type)
    interaction_type : str — exact match on interaction_type
    source      : str — exact match on source
    page        : int (default 1)
    per_page    : int (default 20, max 100)
    """
    args = request.args
    page, per_page = _parse_pagination(args)

    filters = {}
    if args.get('target_type'):
        filters['target_type'] = args['target_type']
    if args.get('target_id') is not None:
        try:
            filters['target_id'] = int(args['target_id'])
        except (TypeError, ValueError):
            pass
    if args.get('interaction_type'):
        filters['interaction_type'] = args['interaction_type']
    if args.get('source'):
        filters['source'] = args['source']

    interactions, total = _interaction_service.list(
        filters=filters, page=page, per_page=per_page
    )

    return jsonify({
        'interactions': [_serialize_interaction(i) for i in interactions],
        'total': total,
        'page': page,
        'per_page': per_page,
    }), 200


@interaction_bp.route('/', methods=['POST'])
@handle_errors
def create_interaction():
    """Create a new Interaction.

    Request body
    ------------
    interaction_type : str (required) — note/call/email/meeting/other
    body             : str (required, non-empty)
    occurred_at      : ISO datetime (required)
    associations     : list of {target_type, target_id} (at least one required)
    source           : str (optional, default 'manual')
    hubspot_engagement_id : str (optional)
    raw_payload      : dict (optional)
    is_orphaned      : bool (optional, default False)
    """
    data = request.get_json(silent=True) or {}
    interaction = _interaction_service.create(data)
    return jsonify(_serialize_interaction(interaction)), 201


@interaction_bp.route('/<int:interaction_id>', methods=['GET'])
@handle_errors
def get_interaction(interaction_id):
    """Get a single Interaction by ID, including its associations."""
    interaction = _interaction_service.get(interaction_id)
    return jsonify(_serialize_interaction(interaction)), 200


@interaction_bp.route('/<int:interaction_id>', methods=['PUT'])
@handle_errors
def update_interaction(interaction_id):
    """Update an existing Interaction.

    Request body (all fields optional — only provided fields are updated)
    ------------
    body             : str
    occurred_at      : ISO datetime
    interaction_type : str
    """
    data = request.get_json(silent=True) or {}
    interaction = _interaction_service.update(interaction_id, data)
    return jsonify(_serialize_interaction(interaction)), 200


@interaction_bp.route('/<int:interaction_id>', methods=['DELETE'])
@handle_errors
def delete_interaction(interaction_id):
    """Delete an Interaction and its associations."""
    _interaction_service.delete(interaction_id)
    return jsonify({'success': True, 'message': f'Interaction {interaction_id} deleted'}), 200


# ---------------------------------------------------------------------------
# Timeline routes  (no prefix — canonical paths)
# ---------------------------------------------------------------------------


@timeline_bp.route('/api/leads/<int:lead_id>/interaction-timeline', methods=['GET'])
@handle_errors
def get_lead_interaction_timeline(lead_id):
    """Return the CRM interaction timeline for a lead (Interactions + Tasks).

    Namespaced separately from command-center ``GET /api/leads/<id>/timeline``
    which serves paginated ``LeadTimelineEntry`` records.

    Query parameters
    ----------------
    entry_type : str — filter by 'interaction' or 'task'
    subtype    : str — filter by interaction_type or task status
    date_from  : ISO datetime — earliest date (inclusive)
    date_to    : ISO datetime — latest date (inclusive)
    """
    args = request.args
    filters = {}
    if args.get('entry_type'):
        filters['entry_type'] = args['entry_type']
    if args.get('subtype'):
        filters['subtype'] = args['subtype']
    if args.get('date_from'):
        filters['date_from'] = args['date_from']
    if args.get('date_to'):
        filters['date_to'] = args['date_to']

    entries = _interaction_service.get_timeline(
        target_type='lead',
        target_id=lead_id,
        filters=filters,
    )
    return jsonify({'timeline': entries, 'lead_id': lead_id}), 200


@timeline_bp.route('/api/organizations/<int:org_id>/timeline', methods=['GET'])
@handle_errors
def get_organization_timeline(org_id):
    """Return the unified timeline for an organization.

    Query parameters
    ----------------
    entry_type : str — filter by 'interaction' or 'task'
    subtype    : str — filter by interaction_type or task status
    date_from  : ISO datetime — earliest date (inclusive)
    date_to    : ISO datetime — latest date (inclusive)
    """
    args = request.args
    filters = {}
    if args.get('entry_type'):
        filters['entry_type'] = args['entry_type']
    if args.get('subtype'):
        filters['subtype'] = args['subtype']
    if args.get('date_from'):
        filters['date_from'] = args['date_from']
    if args.get('date_to'):
        filters['date_to'] = args['date_to']

    entries = _interaction_service.get_timeline(
        target_type='organization',
        target_id=org_id,
        filters=filters,
    )
    return jsonify({'timeline': entries, 'organization_id': org_id}), 200
