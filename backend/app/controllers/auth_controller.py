"""Authentication endpoints.

Provides the login endpoint for credential-based authentication.
The Blueprint is registered at ``/api/auth`` in ``app/__init__.py``.

Public endpoints (no token required):
  - POST /api/auth/login
  - POST /api/auth/set-password
  - GET  /api/health  (defined in routes.py, listed here for documentation)
"""
import logging
from functools import wraps

import bcrypt
import jwt
from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import db, limiter
from app.exceptions import PasswordSetupRequiredException
from app.models.user import User
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
    'POST /api/auth/set-password',
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

    try:
        user = _auth_service.authenticate(email, password)
    except PasswordSetupRequiredException as exc:
        setup_token = _auth_service.issue_setup_token(exc.user)
        return jsonify({'setup_required': True, 'setup_token': setup_token}), 200

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


@auth_bp.route('/set-password', methods=['POST'])
@handle_errors
def set_password():
    """Set password for a user who was provisioned without one.

    Requires Authorization: Bearer <setup_token> where setup_token has
    setup_required=True claim. Returns a normal session token on success.

    Request headers
    ---------------
    Authorization : Bearer <setup_token> (required)

    Request body (JSON)
    -------------------
    new_password : str (required, minimum 8 characters)

    Returns
    -------
    200 — ``{"session_token": str, "user_id": str, "email": str, "display_name": str}``
    400 — Missing or too-short new_password.
    401 — Missing, expired, or invalid setup token; or token is not a setup token.
    404 — User record not found.

    Requirements: 9.2, 9.3, 9.4, 9.5
    """
    # 1. Read and validate the Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.lower().startswith('bearer '):
        return jsonify({'error': 'Authentication required'}), 401
    token = auth_header[7:]

    # 2. Verify the token
    auth_service = AuthService()
    try:
        claims = auth_service.verify_token(token)
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    # 3. Ensure it is a setup token
    if claims.get('setup_required') is not True:
        return jsonify({'error': 'Invalid setup token'}), 401

    # 4. Look up the user
    user_id = claims['sub']
    user = User.query.filter_by(user_id=user_id).first()
    if user is None:
        return jsonify({'error': 'User not found'}), 404

    # 5. Validate new_password from request body
    body = request.get_json(silent=True) or {}
    new_password = body.get('new_password')
    if not new_password or len(new_password) < 8:
        return jsonify({
            'error': 'Validation error',
            'message': 'Password must be at least 8 characters.',
        }), 400

    # 6. Hash with bcrypt work factor 12, persist, and mark password as set
    password_hash = bcrypt.hashpw(
        new_password.encode('utf-8'),
        bcrypt.gensalt(rounds=12),
    ).decode('utf-8')
    user.password_hash = password_hash
    user.password_set = True
    db.session.commit()

    # 7. Issue a normal session token and return the user payload
    session_token = auth_service.issue_token(user)
    return jsonify({
        'session_token': session_token,
        'user_id': user.user_id,
        'email': user.email,
        'display_name': user.display_name,
    }), 200
