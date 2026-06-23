"""Search API endpoint.

Provides a single GET /api/search endpoint that searches across leads
(by owner name or property address) and analysis sessions (by property
address). Results are ownership-scoped: regular users see only their own
records; admin users see all records.

Uses SearchService for ranked fuzzy multi-token matching (pg_trgm).
"""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

from app.api_utils import require_auth
from app.services.search_service import (
    DEFAULT_PAGE,
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    SearchService,
)

logger = logging.getLogger(__name__)

search_bp = Blueprint('search', __name__)


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


def _parse_page(default: int = DEFAULT_PAGE) -> int:
    raw = request.args.get('page', default)
    try:
        page = int(raw)
    except (TypeError, ValueError):
        raise ValueError('page must be a positive integer')
    if page < 1:
        raise ValueError('page must be a positive integer')
    return page


def _parse_per_page(default: int = DEFAULT_PER_PAGE) -> int:
    raw = request.args.get('per_page', default)
    try:
        per_page = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f'per_page must be an integer between 1 and {MAX_PER_PAGE}')
    if per_page < 1 or per_page > MAX_PER_PAGE:
        raise ValueError(f'per_page must be an integer between 1 and {MAX_PER_PAGE}')
    return per_page


@search_bp.route('/search', methods=['GET'])
@handle_errors
@require_auth
def search():
    """Search across leads and analysis sessions with ranked fuzzy matching."""
    q = request.args.get('q')

    if q is None:
        return jsonify({'message': 'Missing required parameter: q'}), 400

    q_trimmed = q.strip()

    if len(q_trimmed) < 2:
        return jsonify({'message': 'Query must be at least 2 characters'}), 400

    if len(q_trimmed) > 200:
        return jsonify({'message': 'Query must not exceed 200 characters'}), 400

    try:
        page = _parse_page()
        per_page = _parse_per_page()
    except ValueError as exc:
        return jsonify({'message': str(exc)}), 400

    result = SearchService().search(
        q=q_trimmed,
        user_id=g.user_id,
        is_admin=g.is_admin,
        page=page,
        per_page=per_page,
    )

    return jsonify({
        'q': result.q,
        'page': result.page,
        'per_page': result.per_page,
        'leads': result.leads,
        'leads_total': result.leads_total,
        'sessions': result.sessions,
        'sessions_total': result.sessions_total,
    }), 200
