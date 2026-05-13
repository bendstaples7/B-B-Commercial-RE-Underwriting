"""Shared API utilities.

Provides:
  - ``get_current_user_id()``  — reads g.user_id (set by before_request hook)
  - ``@require_user``          — decorator that injects user_id into route functions

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

Both approaches read from ``g.user_id``, which is populated by the
``set_user_identity`` before_request hook in ``app/__init__.py``.
No controller should ever read ``X-User-Id`` directly or parse
``user_id`` from the request body.
"""
from functools import wraps

from flask import g


def get_current_user_id() -> str:
    """Return the authenticated user ID for the current request.

    Reads from ``g.user_id``, which is set by the ``set_user_identity``
    before_request hook.  Falls back to 'anonymous' if the hook has not
    run (e.g. in unit tests that call route functions directly).

    Returns
    -------
    str
        The user ID string, never None.
    """
    return getattr(g, 'user_id', 'anonymous')


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
