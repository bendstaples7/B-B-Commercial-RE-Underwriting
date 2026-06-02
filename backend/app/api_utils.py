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


def _allow_legacy_header() -> bool:
    """Return True only when the ALLOW_LEGACY_X_USER_ID config flag is set.

    This flag must never be enabled in production. It exists solely to
    support the transition period where some internal test clients still
    send X-User-Id instead of a Bearer token.
    """
    from flask import current_app
    return bool(current_app.config.get('ALLOW_LEGACY_X_USER_ID', False))


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
        auth_header_lower = auth_header.lower()
        if auth_header_lower.startswith('bearer '):
            token = auth_header[7:]
            try:
                claims = AuthService().verify_token(token)
                # Reject setup tokens — they may only be used with POST /api/auth/set-password
                if claims.get('setup_required') is True:
                    return jsonify({'error': 'Setup token cannot be used for authentication'}), 401
                g.user_id = claims['sub']
                is_admin_claim = claims.get('is_admin', False)
                g.is_admin = is_admin_claim if isinstance(is_admin_claim, bool) else False
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401
        elif auth_header_lower:
            # A non-Bearer Authorization header (e.g. Basic) is not supported.
            # Reject it explicitly rather than falling through to the X-User-Id
            # fallback, which would allow bypassing JWT verification.
            return jsonify({'error': 'Authentication required'}), 401
        elif request.headers.get('X-User-Id') and _allow_legacy_header():
            # Legacy fallback — only accepted when ALLOW_LEGACY_X_USER_ID is
            # explicitly enabled (non-production environments only).
            g.user_id = request.headers.get('X-User-Id')
            g.is_admin = False
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


# ---------------------------------------------------------------------------
# APIFailoverHandler — try multiple data sources in order, failing over on error
# ---------------------------------------------------------------------------

class APIFailoverHandler:
    """Try a list of data sources in order, returning the first successful result.

    Tracks which sources were attempted so callers can raise ``APIFailoverException``
    with the full list when all sources fail.

    Usage::

        handler = APIFailoverHandler()
        sources = [
            ('Source1', fetch_from_source1),
            ('Source2', fetch_from_source2, arg1, arg2),
        ]
        result = handler.try_sources(sources, field='square_footage')
    """

    def __init__(self):
        self.attempted_sources: list[str] = []

    def try_sources(self, sources: list, field: str | None = None):
        """Try each source in order, returning the first successful result.

        Args:
            sources: List of tuples ``(name, callable, *args)``.
            field: Optional field name for error context.

        Returns:
            The return value of the first callable that succeeds.

        Raises:
            APIFailoverException: If all sources raise an exception.
        """
        from app.exceptions import APIFailoverException

        self.attempted_sources = []
        last_error: Exception | None = None

        for entry in sources:
            name = entry[0]
            func = entry[1]
            args = entry[2:] if len(entry) > 2 else ()
            self.attempted_sources.append(name)
            try:
                return func(*args)
            except Exception as exc:
                last_error = exc
                continue

        raise APIFailoverException(
            f"All API sources failed{f' for field {field!r}' if field else ''}.",
            attempted_sources=list(self.attempted_sources),
        )


# ---------------------------------------------------------------------------
# RateLimitHandler — retry a callable on RateLimitException with backoff
# ---------------------------------------------------------------------------

class RateLimitHandler:
    """Retry a callable when it raises ``RateLimitException``, with exponential backoff.

    Usage::

        handler = RateLimitHandler(max_retries=3, base_delay=1.0)
        result = handler.handle_rate_limit(my_api_call)
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    def handle_rate_limit(self, func, *args, **kwargs):
        """Call ``func(*args, **kwargs)``, retrying on ``RateLimitException``.

        Args:
            func: The callable to invoke.
            *args: Positional arguments forwarded to ``func``.
            **kwargs: Keyword arguments forwarded to ``func``.

        Returns:
            The return value of ``func`` on success.

        Raises:
            RateLimitException: If ``max_retries`` is exhausted.
            Any other exception raised by ``func`` is re-raised immediately.
        """
        import time as _time
        from app.exceptions import RateLimitException

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except RateLimitException as exc:
                if attempt >= self.max_retries:
                    raise
                retry_after_hint = exc.payload.get('retry_after')
                retry_after = self.base_delay * (2 ** attempt) if retry_after_hint is None else retry_after_hint
                _time.sleep(float(retry_after))
