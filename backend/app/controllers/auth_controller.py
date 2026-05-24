"""Authentication endpoints.

Provides the login endpoint for credential-based authentication.
The Blueprint is registered at ``/api/auth`` in ``app/__init__.py``.

Public endpoints (no token required):
  - POST /api/auth/login
  - GET  /api/health  (defined in routes.py, listed here for documentation)
"""
import logging
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import limiter
from app.schemas import LoginSchema
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# ---------------------------------------------------------------------------
# Public-endpoint allowlist
#
# Paths listed here are skipped by the ``require_auth`` decorator (task 3.2).
# The login endpoint must always be on this list so unauthenticated clients
# can obtain a token.
# ---------------------------------------------------------------------------
PUBLIC_ENDPOINTS = {
    'POST /api/auth/login',
    'GET /api/health',
}

_login_schema = LoginSchema()
_auth_service = AuthService()


# ---------------------------------------------------------------------------
# Error handling decorator (consistent with other controllers)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across auth endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error in auth endpoint: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except ValueError as e:
            logger.warning("Value error in auth endpoint: %s", str(e))
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
            logger.error("Unexpected error in auth endpoint: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def login():
    """Authenticate a user and return a signed JWT.

    Request body (JSON)
    -------------------
    email : str (required)
    password : str (required)

    Returns
    -------
    200 — ``{"session_token": str, "user_id": str, "email": str, "display_name": str}``
    400 — Missing or invalid fields (Marshmallow validation error).
    401 — Invalid credentials or inactive account.

    Requirements: 2.1, 2.2, 2.3, 3.3
    """
    body = request.get_json(silent=True) or {}

    # Validate with Marshmallow — raises ValidationError (caught by @handle_errors)
    # on missing/invalid fields, returning HTTP 400.
    data = _login_schema.load(body)

    email: str = data['email']
    password: str = data['password']

    user = _auth_service.authenticate(email, password)

    if user is None:
        # Return identical 401 for wrong email and wrong password (Req 2.2)
        return jsonify({'error': 'Invalid email or password.'}), 401

    token = _auth_service.issue_token(user)

    return jsonify({
        'session_token': token,
        'user_id': user.user_id,
        'email': user.email,
        'display_name': user.display_name,
    }), 200
