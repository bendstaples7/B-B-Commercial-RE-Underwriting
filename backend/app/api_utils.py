"""Shared API utilities.

Provides:
  - ``get_current_user_id()``  — reads g.user_id (set by before_request hook)
  - ``@require_user``          — decorator that injects user_id into route functions
  - ``@require_auth``          — decorator that verifies Bearer JWT and populates g.user_id

Usage
-----
Option A — read directly::

    from app.api_utils import get_current_user_id

    @bp.route('/example', methods=['POST'])
    def example():
        user_id = get_current_user_id()
        ...

Option B — inject via decorator::

    from app.api_utils import require_user

    @bp.route('/example', methods=['POST'])
    @require_user
    def example(user_id):
        ...

Option C — JWT-verified auth::

    from app.api_utils import require_auth

    @bp.route('/example', methods=['POST'])
    @require_auth
    def example():
        user_id = g.user_id  # populated from verified Bearer token
        ...

Both ``require_user`` and ``require_auth`` read from ``g.user_id``.
``require_auth`` verifies the JWT signature and expiry; ``require_user``
trusts whatever ``set_user_identity`` already placed in ``g.user_id``.
No controller should ever read ``X-User-Id`` directly or parse
``user_id`` from the request body.
"""
from functools import wraps

import jwt
from flask import g, jsonify, request


def get_current_user_id() -> str:
    """Return the authenticated user ID for the current request.

    Reads from ``g.user_id``, which is set by the ``set_user_identity``
    before_request hook from the ``X-User-Id`` header.  Falls back to
    the ``user_id`` field in the JSON request body (for backwards
    compatibility with clients that send it there), then to 'anonymous'.

    Returns
    -------
    str
        The user ID string, never None.
    """
    user_id = getattr(g, 'user_id', None)
    if user_id and user_id != 'anonymous':
        return user_id
    return 'anonymous'


def require_user(f):
    """Decorator that injects ``user_id`` as a keyword argument into a route.

    Use this on any route that needs the current user's identity.  The
    ``user_id`` value comes from ``g.user_id`` (set by the before_request
    hook) — never from the request body or a schema field.

    Example
    -------
    ::

        @bp.route('/deals', methods=['POST'])
        @handle_errors
        @require_user
        def create_deal(user_id):
            service.create_deal(user_id, payload)

    Notes
    -----
    - Apply ``@require_user`` *after* ``@handle_errors`` so that errors
      raised inside the route are still caught by the error handler.
    - The decorated function must accept ``user_id`` as a keyword argument.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        kwargs['user_id'] = get_current_user_id()
        return f(*args, **kwargs)
    return decorated


def require_auth(f):
    """Decorator that verifies a Bearer JWT and populates ``g.user_id``.

    Reads the ``Authorization: Bearer <token>`` header, verifies the JWT
    via ``AuthService.verify_token()``, and sets ``g.user_id`` to the
    token's ``sub`` claim.

    Falls back to the ``X-User-Id`` header **only** when no
    ``Authorization`` header is present (backward-compatibility during
    the transition period).  Once all clients send Bearer tokens the
    fallback can be removed.

    Returns 401 for:
    - Missing ``Authorization`` header (and no ``X-User-Id`` fallback)
    - Non-Bearer ``Authorization`` scheme
    - Expired JWT (``jwt.ExpiredSignatureError``)
    - Malformed or invalid-signature JWT (``jwt.InvalidTokenError``)

    Example
    -------
    ::

        @bp.route('/leads', methods=['GET'])
        @handle_errors
        @require_auth
        def list_leads():
            user_id = g.user_id
            ...

    Notes
    -----
    - Apply ``@require_auth`` *after* ``@handle_errors`` so that errors
      raised inside the route are still caught by the error handler.
    - Requirements: 3.1, 3.2, 3.4
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from app.services.auth_service import AuthService

        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                claims = AuthService().verify_token(token)
                g.user_id = claims['sub']
                is_admin_claim = claims.get('is_admin', False)
                g.is_admin = is_admin_claim if isinstance(is_admin_claim, bool) else False
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401
        elif request.headers.get('X-User-Id'):
            # Legacy fallback — only used during transition period.
            # Bearer token takes precedence when both headers are present.
            g.user_id = request.headers.get('X-User-Id')
        else:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator that verifies the authenticated user is an admin.

    Must be applied AFTER @require_auth (which populates g.user_id and g.is_admin).
    Returns 403 if g.is_admin is not True.
    Logs the unauthorized access attempt including user_id and path.

    Example
    -------
    ::

        @bp.route('/admin/users', methods=['GET'])
        @handle_errors
        @require_auth
        @require_admin
        def list_users():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)

        if not getattr(g, 'is_admin', False):
            user_id = getattr(g, 'user_id', 'unknown')
            logger.warning(
                'Admin access denied: user_id=%s attempted to access %s',
                user_id,
                request.path
            )
            return jsonify({
                'error': 'Forbidden',
                'message': 'Admin access required.'
            }), 403
        return f(*args, **kwargs)
    return decorated
