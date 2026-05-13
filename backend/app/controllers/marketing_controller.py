"""Marketing list API endpoints.

Provides endpoints for CRUD operations on marketing lists, membership
management, and outreach status tracking.
"""
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import db, limiter
from app.api_utils import get_current_user_id
from app.models import Lead, MarketingList, MarketingListMember
from app.services.marketing_manager import MarketingManager

logger = logging.getLogger(__name__)

marketing_bp = Blueprint('marketing', __name__)

manager = MarketingManager()

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100


# ---------------------------------------------------------------------------
# Error handling decorator (consistent with other controllers)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
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
# Helpers
# ---------------------------------------------------------------------------

def _parse_pagination(args):
    """Extract and validate pagination parameters from query string."""
    try:
        page = int(args.get('page', DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        per_page = int(args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE

    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _serialize_marketing_list(ml):
    """Serialize a MarketingList to a dictionary."""
    member_count = ml.members.count() if ml.members else 0
    return {
        'id': ml.id,
        'name': ml.name,
        'user_id': ml.user_id,
        'filter_criteria': ml.filter_criteria,
        'member_count': member_count,
        'created_at': ml.created_at.isoformat() if ml.created_at else None,
        'updated_at': ml.updated_at.isoformat() if ml.updated_at else None,
    }


def _serialize_list_member(member):
    """Serialize a MarketingListMember with associated lead data."""
    lead = member.lead if hasattr(member, 'lead') else None
    result = {
        'id': member.id,
        'marketing_list_id': member.marketing_list_id,
        'lead_id': member.lead_id,
        'outreach_status': member.outreach_status,
        'added_at': member.added_at.isoformat() if member.added_at else None,
        'status_updated_at': (
            member.status_updated_at.isoformat()
            if member.status_updated_at else None
        ),
    }
    if lead:
        result['lead'] = {
            'id': lead.id,
            'property_street': lead.property_street,
            'owner_first_name': lead.owner_first_name,
            'owner_last_name': lead.owner_last_name,
            'lead_score': lead.lead_score,
            'phone_1': lead.phone_1,
            'email_1': lead.email_1,
            'mailing_city': lead.mailing_city,
            'mailing_state': lead.mailing_state,
        }
    return result


# ---------------------------------------------------------------------------
# Routes — List CRUD
# ---------------------------------------------------------------------------

@marketing_bp.route('/lists', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def list_marketing_lists():
    """List marketing lists with optional user filtering.

    Query parameters
    ----------------
    user_id : str (optional — filter by owner)
    page : int (default 1)
    per_page : int (default 25, max 100)

    Returns
    -------
    200 with paginated list of marketing lists.
    """
    args = request.args
    page, per_page = _parse_pagination(args)

    query = MarketingList.query

    user_id = args.get('user_id')
    if user_id:
        query = query.filter(MarketingList.user_id == user_id)

    query = query.order_by(MarketingList.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'lists': [_serialize_marketing_list(ml) for ml in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }), 200


@marketing_bp.route('/lists', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def create_marketing_list():
    """Create a new marketing list.

    Request body
    ------------
    name : str (required)
    user_id : str (required)
    filter_criteria : dict (optional)
        If provided, the list is populated with leads matching the filters.
        Leads with "opted_out" status in any list are excluded.

    Returns
    -------
    201 with the new marketing list.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    name = data.get('name')
    user_id = get_current_user_id()

    missing = []
    if not name:
        missing.append('name')
    if not user_id or user_id == 'anonymous':
        missing.append('user_id')
    if missing:
        return jsonify({
            'error': 'Validation error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    filter_criteria = data.get('filter_criteria')

    if filter_criteria and isinstance(filter_criteria, dict):
        ml = manager.create_list_from_filters(name, user_id, filter_criteria)
    else:
        ml = manager.create_list(name, user_id)

    return jsonify(_serialize_marketing_list(ml)), 201


@marketing_bp.route('/lists/<int:list_id>', methods=['PUT'])
@limiter.limit("10 per minute")
@handle_errors
def rename_marketing_list(list_id):
    """Rename an existing marketing list.

    Request body
    ------------
    name : str (required)

    Returns
    -------
    200 with the updated marketing list.
    404 if list not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    name = data.get('name')
    if not name:
        return jsonify({
            'error': 'Validation error',
            'message': 'name is required',
        }), 400

    ml = manager.rename_list(list_id, name)

    return jsonify(_serialize_marketing_list(ml)), 200


@marketing_bp.route('/lists/<int:list_id>', methods=['DELETE'])
@limiter.limit("10 per minute")
@handle_errors
def delete_marketing_list(list_id):
    """Delete a marketing list and all its memberships.

    Returns
    -------
    200 with confirmation message.
    404 if list not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    list_name = ml.name
    manager.delete_list(list_id)

    return jsonify({
        'message': f"Marketing list '{list_name}' deleted successfully",
        'id': list_id,
    }), 200


# ---------------------------------------------------------------------------
# Routes — Membership management
# ---------------------------------------------------------------------------

@marketing_bp.route('/lists/<int:list_id>/members', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_list_members(list_id):
    """Get paginated members of a marketing list.

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 25, max 100)

    Returns
    -------
    200 with paginated list of members including lead data.
    404 if list not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    page, per_page = _parse_pagination(request.args)

    result = manager.get_list_members(list_id, page=page, per_page=per_page)

    return jsonify({
        'list_id': list_id,
        'list_name': ml.name,
        'members': [_serialize_list_member(m) for m in result.items],
        'total': result.total,
        'page': result.page,
        'per_page': result.per_page,
        'pages': result.pages,
    }), 200


@marketing_bp.route('/lists/<int:list_id>/members', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def add_list_members(list_id):
    """Add leads to a marketing list.

    Request body
    ------------
    lead_ids : list[int] (required)

    Returns
    -------
    200 with count of leads added.
    404 if list not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    lead_ids = data.get('lead_ids')
    if not lead_ids:
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids is required',
        }), 400

    if not isinstance(lead_ids, list):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    try:
        lead_ids = [int(lid) for lid in lead_ids]
    except (TypeError, ValueError):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    added = manager.add_leads(list_id, lead_ids)

    return jsonify({
        'list_id': list_id,
        'leads_added': added,
        'leads_requested': len(lead_ids),
    }), 200


@marketing_bp.route('/lists/<int:list_id>/members', methods=['DELETE'])
@limiter.limit("10 per minute")
@handle_errors
def remove_list_members(list_id):
    """Remove leads from a marketing list.

    Request body
    ------------
    lead_ids : list[int] (required)

    Returns
    -------
    200 with count of leads removed.
    404 if list not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    lead_ids = data.get('lead_ids')
    if not lead_ids:
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids is required',
        }), 400

    if not isinstance(lead_ids, list):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    try:
        lead_ids = [int(lid) for lid in lead_ids]
    except (TypeError, ValueError):
        return jsonify({
            'error': 'Validation error',
            'message': 'lead_ids must be a list of integers',
        }), 400

    removed = manager.remove_leads(list_id, lead_ids)

    return jsonify({
        'list_id': list_id,
        'leads_removed': removed,
        'leads_requested': len(lead_ids),
    }), 200


# ---------------------------------------------------------------------------
# Routes — Outreach status
# ---------------------------------------------------------------------------

@marketing_bp.route(
    '/lists/<int:list_id>/members/<int:lead_id>/status',
    methods=['PUT'],
)
@limiter.limit("20 per minute")
@handle_errors
def update_member_status(list_id, lead_id):
    """Update the outreach status for a lead within a marketing list.

    Request body
    ------------
    status : str (required)
        One of: "not_contacted", "contacted", "responded", "converted",
        "opted_out".

    Returns
    -------
    200 with the updated membership record.
    404 if list or membership not found.
    """
    ml = db.session.get(MarketingList, list_id)
    if not ml:
        return jsonify({
            'error': 'Marketing list not found',
            'message': f'Marketing list {list_id} does not exist',
        }), 404

    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    status = data.get('status')
    if not status:
        return jsonify({
            'error': 'Validation error',
            'message': 'status is required',
        }), 400

    member = manager.update_outreach_status(list_id, lead_id, status)

    return jsonify({
        'list_id': list_id,
        'lead_id': lead_id,
        'outreach_status': member.outreach_status,
        'status_updated_at': (
            member.status_updated_at.isoformat()
            if member.status_updated_at else None
        ),
    }), 200
