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
import logging
import uuid
from functools import wraps

import jwt
from flask import g, jsonify, request

logger = logging.getLogger(__name__)

# Fail-closed public allowlist for /api. Everything else requires a real user_id
# (JWT in prod/dev; X-User-Id only in the testing config).
PUBLIC_API_ROUTES = frozenset({
    ('GET', '/api/health'),
    ('GET', '/api/health/runtime'),
    ('GET', '/api/spa-version'),
    ('GET', '/api/version'),
    ('GET', '/api/openapi.json'),
    ('POST', '/api/auth/login'),
    ('POST', '/api/auth/set-password'),
    ('POST', '/api/hubspot/webhook'),
    ('POST', '/api/spa-boot-failure'),
})


def is_public_api_request(method: str | None = None, path: str | None = None) -> bool:
    """Return True when this /api request is allowed without a user session."""
    verb = (method or request.method or '').upper()
    if verb == 'OPTIONS':
        return True
    if verb == 'HEAD':
        verb = 'GET'
    raw_path = path if path is not None else (request.path or '')
    if not raw_path.startswith('/api'):
        return True
    normalized = raw_path.rstrip('/') or '/'
    if (verb, raw_path) in PUBLIC_API_ROUTES:
        return True
    if (verb, normalized) in PUBLIC_API_ROUTES:
        return True
    # Allowlist entries are stored without a trailing slash.
    if not raw_path.endswith('/') and (verb, raw_path + '/') in PUBLIC_API_ROUTES:
        return True
    return False


def anonymous_api_unauthorized_response():
    """JSON 401 used by the global /api identity gate."""
    return jsonify({'error': 'Authentication required'}), 401


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


def _user_id_for_log(value) -> str:
    """Return a PII-safe, log-injection-safe user identifier."""
    if value is None:
        return 'missing'
    candidate = str(value).replace('\r', '').replace('\n', '').strip()
    try:
        return str(uuid.UUID(candidate))
    except (TypeError, ValueError):
        return 'invalid'


def bind_request_jwt_identity(token: str) -> None:
    """Populate ``g.user_id`` / ``g.is_admin`` from a Bearer JWT.

    Setup tokens, missing users, and deactivated accounts are anonymous.
    Failures set ``g.jwt_error`` so ``enforce_api_auth`` can reject the
    request — except a setup token on a public route (set-password).
    """
    from app.models.user import User
    from app.services.auth_service import AuthService

    g.user_id = 'anonymous'
    try:
        claims = AuthService().verify_token(token)
    except jwt.ExpiredSignatureError:
        g.jwt_error = 'expired'
        return
    except jwt.InvalidTokenError:
        g.jwt_error = 'invalid'
        return
    except Exception:
        g.jwt_error = 'invalid'
        return

    if claims.get('setup_required') is True:
        if not is_public_api_request():
            g.jwt_error = 'setup_token'
        return

    subject = claims.get('sub')
    user = User.query.filter_by(user_id=subject).first() if subject else None
    if user is None:
        g.jwt_error = 'user_not_found'
        g.jwt_subject = subject
        return
    if not user.is_active:
        g.jwt_error = 'inactive'
        g.jwt_subject = user.user_id
        return
    g.user_id = user.user_id
    g.is_admin = bool(user.is_admin)


def require_auth(f):
    """Decorator that verifies a Bearer JWT and populates ``g.user_id``.

    Reads the ``Authorization: Bearer <token>`` header, verifies the JWT
    via ``AuthService.verify_token()``, then reloads the user from the
    database so ``is_active`` / ``is_admin`` reflect current state (not
    stale JWT claims). Sets ``g.user_id`` and ``g.is_admin`` from that row.

    Falls back to the ``X-User-Id`` header **only** when no
    ``Authorization`` header is present (backward-compatibility during
    the transition period).  Once all clients send Bearer tokens the
    fallback can be removed.

    Returns 401 for:
    - Missing ``Authorization`` header (and no ``X-User-Id`` fallback)
    - Non-Bearer ``Authorization`` scheme
    - Expired JWT (``jwt.ExpiredSignatureError``)
    - Malformed or invalid-signature JWT (``jwt.InvalidTokenError``)
    - Unknown or inactive user for an otherwise-valid JWT

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
        from app.models.user import User
        from app.services.auth_service import AuthService

        auth_header = request.headers.get('Authorization', '')
        auth_header_lower = auth_header.lower()
        if auth_header_lower.startswith('bearer '):
            if (
                not getattr(g, 'jwt_error', None)
                and getattr(g, 'user_id', None)
                and getattr(g, 'user_id', None) != 'anonymous'
            ):
                return f(*args, **kwargs)
            token = auth_header[7:]
            try:
                claims = AuthService().verify_token(token)
                # Reject setup tokens — they may only be used with POST /api/auth/set-password
                if claims.get('setup_required') is True:
                    logger.warning(
                        "auth_reject reason=setup_token path=%s",
                        request.path,
                    )
                    return jsonify({'error': 'Setup token cannot be used for authentication'}), 401
                user = User.query.filter_by(user_id=claims['sub']).first()
                # Re-check live account state so deactivation / admin revocation
                # take effect before the JWT's long-lived exp claim.
                if user is None:
                    logger.warning(
                        "auth_reject reason=user_not_found path=%s user_id=%s",
                        request.path,
                        _user_id_for_log(claims.get('sub')),
                    )
                    return jsonify({'error': 'Authentication required'}), 401
                if not user.is_active:
                    logger.warning(
                        "auth_reject reason=user_inactive path=%s user_id=%s",
                        request.path,
                        _user_id_for_log(user.user_id),
                    )
                    return jsonify({'error': 'Authentication required'}), 401
                g.user_id = user.user_id
                g.is_admin = bool(user.is_admin)
            except jwt.ExpiredSignatureError:
                logger.warning(
                    "auth_reject reason=token_expired path=%s",
                    request.path,
                )
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                logger.warning(
                    "auth_reject reason=token_invalid path=%s",
                    request.path,
                )
                return jsonify({'error': 'Invalid token'}), 401
        elif auth_header_lower:
            # A non-Bearer Authorization header (e.g. Basic) is not supported.
            # Reject it explicitly rather than falling through to the X-User-Id
            # fallback, which would allow bypassing JWT verification.
            logger.warning(
                "auth_reject reason=missing_auth path=%s",
                request.path,
            )
            return jsonify({'error': 'Authentication required'}), 401
        elif request.headers.get('X-User-Id') and _allow_legacy_header():
            # Legacy fallback — only accepted when ALLOW_LEGACY_X_USER_ID is
            # explicitly enabled (non-production environments only).
            g.user_id = request.headers.get('X-User-Id')
            header_user = User.query.filter_by(user_id=g.user_id).first()
            g.is_admin = bool(header_user and header_user.is_admin)
        else:
            logger.warning(
                "auth_reject reason=missing_auth path=%s",
                request.path,
            )
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


def current_user_is_admin() -> bool:
    """Return True when the authenticated caller is an admin.

    Prefers ``g.is_admin`` from ``require_auth``. Falls back to a User row
    lookup for legacy/test paths. Fail closed on any error.
    """
    try:
        is_admin = getattr(g, 'is_admin', None)
        if is_admin is not None:
            return bool(is_admin)
        user_id = getattr(g, 'user_id', None)
        if not user_id or user_id == 'anonymous':
            return False
        from app.models.user import User
        user = User.query.filter_by(user_id=user_id).first()
        return bool(user and user.is_admin)
    except Exception:
        return False


def user_can_access_lead(lead) -> bool:
    """True when the caller may read/mutate this lead (owner or admin)."""
    if lead is None:
        return False
    if current_user_is_admin():
        return True
    current_user_id = getattr(g, 'user_id', None)
    if not current_user_id or current_user_id == 'anonymous':
        return False
    return lead.owner_user_id == current_user_id


def lead_not_found_response(lead_id: int):
    """Opaque 404 used for missing leads and owner-denied IDOR."""
    return jsonify({
        'error': 'Not found',
        'message': f'Lead {lead_id} not found',
    }), 404


def load_authorized_lead(lead_id: int):
    """Load a lead the caller may access, or return ``(None, 404 response)``."""
    from app import db
    from app.models.lead import Lead

    lead = db.session.get(Lead, lead_id)
    if lead is None or not user_can_access_lead(lead):
        return None, lead_not_found_response(lead_id)
    return lead, None


def user_can_access_analysis_session(session) -> bool:
    """True when the caller owns this analysis session or is admin."""
    if session is None:
        return False
    if current_user_is_admin():
        return True
    current_user_id = getattr(g, 'user_id', None)
    if not current_user_id or current_user_id == 'anonymous':
        return False
    return session.user_id == current_user_id


def analysis_session_not_found_response(session_id: str):
    """Opaque 404 used for missing sessions and owner-denied IDOR."""
    return jsonify({
        'error': 'Session not found',
        'message': f'Session {session_id} not found',
    }), 404


def load_authorized_analysis_session(session_id: str):
    """Load an analysis session the caller may access, or return ``(None, 404)``."""
    from app.models.analysis_session import AnalysisSession

    session = AnalysisSession.query.filter_by(session_id=session_id).first()
    if session is None or not user_can_access_analysis_session(session):
        return None, analysis_session_not_found_response(session_id)
    return session, None


def owned_lead_ids_for_current_user() -> set[int] | None:
    """Lead ids the caller may see.

    ``None`` means admin (no owner filter). An empty set means a non-admin
    with no owned leads.
    """
    if current_user_is_admin():
        return None
    current_user_id = getattr(g, 'user_id', None)
    if not current_user_id or current_user_id == 'anonymous':
        return set()
    from app.models.lead import Lead

    return {
        row[0]
        for row in Lead.query.with_entities(Lead.id)
        .filter(Lead.owner_user_id == current_user_id)
        .all()
    }


def accessible_association_target_ids_for_current_user() -> dict[str, set[int]] | None:
    """Association target ids visible to the current caller, or None for admin."""
    if current_user_is_admin():
        return None
    lead_ids = owned_lead_ids_for_current_user() or set()
    current_user_id = getattr(g, 'user_id', None)
    if not current_user_id or current_user_id == 'anonymous':
        return {'lead': set(), 'organization': set(), 'contact': set()}
    from app.models.contact import Contact
    from app.models.owner_organization_link import OwnerOrganizationLink
    from app.models.property_contact import PropertyContact
    from app.models.property_organization_link import PropertyOrganizationLink

    organization_ids = set()
    contact_ids = set()
    if lead_ids:
        organization_ids.update(
            row[0]
            for row in PropertyOrganizationLink.query.with_entities(
                PropertyOrganizationLink.organization_id,
            )
            .filter(PropertyOrganizationLink.property_id.in_(lead_ids))
            .all()
        )
        organization_ids.update(
            row[0]
            for row in OwnerOrganizationLink.query.with_entities(
                OwnerOrganizationLink.organization_id,
            )
            .filter(OwnerOrganizationLink.owner_id.in_(lead_ids))
            .all()
        )
        contact_ids.update(
            row[0]
            for row in PropertyContact.query.with_entities(PropertyContact.contact_id)
            .filter(PropertyContact.property_id.in_(lead_ids))
            .all()
        )

    contact_ids.update(
        row[0]
        for row in Contact.query.with_entities(Contact.id)
        .filter(Contact.created_by_user_id == current_user_id)
        .filter(~Contact.property_contacts.any())
        .all()
    )
    return {
        'lead': set(lead_ids),
        'organization': organization_ids,
        'contact': contact_ids,
    }


def apply_association_access_scope_filter(
    query,
    *,
    parent_model,
    association_model,
    parent_fk_column,
    association_access_scope: dict[str, set[int]],
    direct_lead_column=None,
):
    """Restrict a query to rows whose complete association set is accessible."""
    from sqlalchemy import and_, or_
    from app import db

    lead_ids = association_access_scope.get('lead', set())
    organization_ids = association_access_scope.get('organization', set())
    contact_ids = association_access_scope.get('contact', set())
    supported_types = tuple(getattr(association_model.target_type.type, 'enums', ()) or ())
    type_scopes = {
        'lead': lead_ids,
        'organization': organization_ids,
        'contact': contact_ids,
    }
    inaccessible_predicates = [
        and_(
            association_model.target_type == target_type,
            ~association_model.target_id.in_(type_scopes[target_type]),
        )
        for target_type in supported_types
        if target_type in type_scopes
    ]
    inaccessible_predicates.append(~association_model.target_type.in_(supported_types))
    inaccessible_assoc = db.session.query(association_model.id).filter(
        parent_fk_column == parent_model.id,
        or_(*inaccessible_predicates),
    ).correlate(parent_model).exists()
    any_assoc = db.session.query(association_model.id).filter(
        parent_fk_column == parent_model.id,
    ).correlate(parent_model).exists()
    query = query.filter(~inaccessible_assoc)
    if direct_lead_column is None:
        return query.filter(any_assoc)
    return query.filter(
        or_(direct_lead_column.is_(None), direct_lead_column.in_(lead_ids)),
        or_(direct_lead_column.in_(lead_ids), any_assoc),
    )


def _association_pairs(associations):
    """Normalize association dicts or ORM rows to ``(target_type, target_id)``.

    Returns ``None`` when any target_id cannot be parsed (caller must deny).
    """
    pairs = []
    for assoc in associations or []:
        if isinstance(assoc, dict):
            target_type = assoc.get('target_type')
            target_id = assoc.get('target_id')
        else:
            target_type = getattr(assoc, 'target_type', None)
            target_id = getattr(assoc, 'target_id', None)
        if not target_type or target_id is None:
            return None
        try:
            pairs.append((str(target_type), int(target_id)))
        except (TypeError, ValueError):
            return None
    return pairs


def user_can_access_association_target(target_type: str, target_id: int) -> bool:
    """True when the caller may attach to / read this association target."""
    if current_user_is_admin():
        return True
    from app import db

    if target_type == 'lead':
        from app.models.lead import Lead

        return user_can_access_lead(db.session.get(Lead, int(target_id)))

    if target_type == 'organization':
        from app.models.lead import Lead
        from app.models.owner_organization_link import OwnerOrganizationLink
        from app.models.organization import Organization
        from app.models.property_organization_link import PropertyOrganizationLink

        org = db.session.get(Organization, int(target_id))
        if org is None:
            return False
        links = [
            ('property', link.property_id)
            for link in PropertyOrganizationLink.query.filter_by(
                organization_id=org.id,
            ).all()
        ]
        links.extend(
            ('owner', link.owner_id)
            for link in OwnerOrganizationLink.query.filter_by(
                organization_id=org.id,
            ).all()
        )
        if not links:
            return False
        for _kind, lead_id in links:
            if user_can_access_lead(db.session.get(Lead, lead_id)):
                return True
        return False

    if target_type == 'contact':
        from app.models.contact import Contact
        from app.models.lead import Lead

        contact = db.session.get(Contact, int(target_id))
        if contact is None:
            return False
        links = list(contact.property_contacts.all())
        if not links:
            actor = getattr(g, 'user_id', None)
            created_by = getattr(contact, 'created_by_user_id', None)
            return bool(
                actor and actor != 'anonymous' and created_by and created_by == actor
            )
        for pc in links:
            if user_can_access_lead(db.session.get(Lead, pc.property_id)):
                return True
        return False

    return False


def user_can_access_association_targets(associations) -> bool:
    """True when every association target is accessible.

    An empty list is denied for non-admins (fail closed).
    """
    if current_user_is_admin():
        return True
    pairs = _association_pairs(associations)
    if not pairs:
        return False
    return all(user_can_access_association_target(kind, tid) for kind, tid in pairs)


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
