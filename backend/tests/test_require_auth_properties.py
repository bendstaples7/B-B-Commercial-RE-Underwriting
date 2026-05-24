"""
Property-based tests for the ``require_auth`` decorator and Bearer token
precedence over ``X-User-Id``.

Feature: multi-user-lead-exclusivity
"""
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid email strategy: local@domain.tld, ASCII-only
_local_part = st.text(
    alphabet=st.characters(
        whitelist_categories=('Nd',),
        whitelist_characters='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._%+-',
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s and not s.startswith('.') and not s.endswith('.'))

_domain_label = st.text(
    alphabet=st.characters(
        whitelist_categories=('Nd',),
        whitelist_characters='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-',
    ),
    min_size=1,
    max_size=15,
).filter(lambda s: s and not s.startswith('-') and not s.endswith('-'))

_tld = st.sampled_from(['com', 'net', 'org', 'io', 'co'])

_email_strategy = st.builds(
    lambda local, domain, tld: f"{local}@{domain}.{tld}",
    local=_local_part,
    domain=_domain_label,
    tld=_tld,
).filter(lambda e: len(e) <= 254)

# Password strategy: at least 8 printable ASCII chars, no whitespace
_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=('Ll', 'Lu', 'Nd', 'Po', 'Ps', 'Pe'),
        whitelist_characters='!@#$%^&*',
    ),
    min_size=8,
    max_size=72,
).filter(lambda p: p.strip() == p and len(p) >= 8)

# Display name strategy: 1–100 non-empty printable characters
_display_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd', 'Zs')),
    min_size=1,
    max_size=50,
).map(str.strip).filter(lambda n: len(n) >= 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _delete_user_by_email(db, email: str) -> None:
    """Delete the User row with the given email (case-insensitive)."""
    from app.models.user import User
    User.query.filter_by(email_lower=email.lower()).delete()
    db.session.commit()


def _register_whoami_route(app):
    """Register a ``GET /api/test/whoami`` route that returns ``g.user_id``.

    The route uses ``require_auth`` so it verifies the Bearer token and
    populates ``g.user_id`` before returning it.  Idempotent — safe to call
    multiple times (Flask silently ignores duplicate endpoint registrations
    when the function object is the same).
    """
    from flask import g, jsonify
    from app.api_utils import require_auth

    endpoint_name = 'test_whoami'

    # Only register once per app instance
    if endpoint_name in app.view_functions:
        return

    @app.route('/api/test/whoami', methods=['GET'], endpoint=endpoint_name)
    @require_auth
    def whoami():
        return jsonify({'user_id': g.user_id}), 200


# ---------------------------------------------------------------------------
# Property 10: Bearer token identity takes precedence over X-User-Id
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    email_a=_email_strategy,
    email_b=_email_strategy,
    password_a=_password_strategy,
    password_b=_password_strategy,
    display_name_a=_display_name_strategy,
    display_name_b=_display_name_strategy,
)
def test_property_10_bearer_takes_precedence_over_x_user_id(
    app,
    client,
    email_a,
    email_b,
    password_a,
    password_b,
    display_name_a,
    display_name_b,
):
    """
    Property 10: Bearer token identity takes precedence over X-User-Id

    For any request carrying both a valid Bearer token with subject ``user_a``
    and an ``X-User-Id`` header with value ``user_b`` (where ``user_a ≠ user_b``),
    ``g.user_id`` SHALL equal ``user_a``.

    **Validates: Requirements 3.4**
    """
    # Ensure the two users have distinct emails (and therefore distinct user_ids)
    assume(email_a.lower() != email_b.lower())

    with app.app_context():
        from app import db

        service = AuthService()

        # Register the test whoami route (idempotent)
        _register_whoami_route(app)

        # Clean up any leftover rows from prior Hypothesis examples
        _delete_user_by_email(db, email_a)
        _delete_user_by_email(db, email_b)

        try:
            # Create both users
            user_a = service.create_user(email_a, password_a, display_name_a)
            user_b = service.create_user(email_b, password_b, display_name_b)

            # Ensure the two users have distinct user_ids (they always should,
            # but be explicit so the assertion below is meaningful)
            assume(user_a.user_id != user_b.user_id)

            # Issue a Bearer token for user_a
            token_a = service.issue_token(user_a)

            # Send a request with:
            #   Authorization: Bearer <token_a>   (identifies user_a)
            #   X-User-Id: <user_b.user_id>       (would identify user_b if Bearer absent)
            response = client.get(
                '/api/test/whoami',
                headers={
                    'Authorization': f'Bearer {token_a}',
                    'X-User-Id': user_b.user_id,
                },
            )

            assert response.status_code == 200, (
                f"Expected 200 from /api/test/whoami with valid Bearer token, "
                f"got {response.status_code}: {response.get_data(as_text=True)}"
            )

            body = response.get_json()
            assert body is not None, "Response body is not valid JSON"

            returned_user_id = body.get('user_id')

            # The Bearer token's subject (user_a.user_id) MUST win over
            # the X-User-Id header (user_b.user_id)
            assert returned_user_id == user_a.user_id, (
                f"Bearer token identity should take precedence over X-User-Id header.\n"
                f"Expected g.user_id == {user_a.user_id!r} (from Bearer token sub claim),\n"
                f"but got {returned_user_id!r}.\n"
                f"X-User-Id header was set to {user_b.user_id!r}.\n"
                f"email_a={email_a!r}, email_b={email_b!r}"
            )

            # Also assert the returned user_id is NOT user_b's id
            assert returned_user_id != user_b.user_id, (
                f"g.user_id must not equal user_b.user_id ({user_b.user_id!r}) — "
                f"the X-User-Id header must be ignored when a valid Bearer token is present."
            )

        finally:
            # Always clean up so the next Hypothesis example starts fresh
            _delete_user_by_email(db, email_a)
            _delete_user_by_email(db, email_b)
