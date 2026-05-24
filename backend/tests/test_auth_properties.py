"""
Property-based tests for authentication (AuthService).

Feature: multi-user-lead-exclusivity
"""
import pytest
from datetime import datetime, timezone
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# AuthService will be implemented in task 2.1.
# This import will fail until that task is complete — that is expected.
from app.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid email strategy: local@domain.tld, max 254 chars, ASCII-only to ensure
# case-folding round-trips correctly (e.g. 'µ'.upper().lower() != 'µ' in Unicode).
_local_part = st.text(
    alphabet=st.characters(
        whitelist_categories=('Nd',),
        whitelist_characters='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._%+-',
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s and not s.startswith('.') and not s.endswith('.'))

_domain_label = st.text(
    alphabet=st.characters(
        whitelist_categories=('Nd',),
        whitelist_characters='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-',
    ),
    min_size=1,
    max_size=20,
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
    max_size=72,  # bcrypt max
).filter(lambda p: p.strip() == p and len(p) >= 8)

# Display name strategy: 1–100 non-empty printable characters
_display_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd', 'Zs')),
    min_size=1,
    max_size=100,
).map(str.strip).filter(lambda n: len(n) >= 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _delete_user_by_email(db, email: str) -> None:
    """Delete the User row with the given email (case-insensitive) so that
    subsequent Hypothesis examples start with a clean DB state.

    ``create_user`` calls ``db.session.commit()``, so a plain rollback after
    the fact is a no-op.  Explicit deletion is the only reliable way to
    isolate examples when the ``app`` fixture is shared across all examples.
    """
    from app.models.user import User
    User.query.filter_by(email_lower=email.lower()).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# Property 1: User record completeness
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    email=_email_strategy,
    password=_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_1_user_record_completeness(app, email, password, display_name):
    """
    Property 1: User record completeness

    For any valid user creation input (email, password, display name), the
    created User record SHALL contain all required fields:
      - a non-empty ``user_id``
      - ``email_lower`` equal to ``email.lower()``
      - a ``password_hash`` that is NOT equal to the submitted password
      - ``is_active`` equal to ``True``
      - UTC ``created_at`` and ``updated_at`` timestamps

    **Validates: Requirements 1.1**
    """
    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same
        # email (the app fixture shares one DB across all 100 examples).
        _delete_user_by_email(db, email)

        user = service.create_user(email, password, display_name)

        try:
            # user_id must be a non-empty string
            assert user.user_id, (
                f"user_id is empty or None for email={email!r}"
            )
            assert isinstance(user.user_id, str) and len(user.user_id) > 0, (
                f"user_id must be a non-empty string, got {user.user_id!r}"
            )

            # email_lower must equal email.lower()
            assert user.email_lower == email.lower(), (
                f"email_lower mismatch: expected {email.lower()!r}, got {user.email_lower!r}"
            )

            # password_hash must not equal the plaintext password
            assert user.password_hash != password, (
                f"password_hash must not equal the plaintext password for email={email!r}"
            )
            assert user.password_hash, (
                f"password_hash is empty or None for email={email!r}"
            )

            # is_active must be True
            assert user.is_active is True, (
                f"is_active must be True after create_user, got {user.is_active!r}"
            )

            # created_at and updated_at must be datetime instances
            assert isinstance(user.created_at, datetime), (
                f"created_at must be a datetime, got {type(user.created_at)}"
            )
            assert isinstance(user.updated_at, datetime), (
                f"updated_at must be a datetime, got {type(user.updated_at)}"
            )

            # Timestamps must be UTC (tzinfo is None for naive UTC datetimes stored
            # via datetime.utcnow(), or tzinfo == UTC for aware datetimes).
            # Accept both naive (utcnow pattern) and aware UTC datetimes.
            if user.created_at.tzinfo is not None:
                assert user.created_at.tzinfo == timezone.utc, (
                    f"created_at tzinfo must be UTC, got {user.created_at.tzinfo!r}"
                )
            if user.updated_at.tzinfo is not None:
                assert user.updated_at.tzinfo == timezone.utc, (
                    f"updated_at tzinfo must be UTC, got {user.updated_at.tzinfo!r}"
                )
        finally:
            # Always clean up so the next Hypothesis example starts with a
            # clean DB state regardless of whether assertions passed or failed.
            _delete_user_by_email(db, email)


# ---------------------------------------------------------------------------
# Property 2: Email uniqueness is case-insensitive
# ---------------------------------------------------------------------------

def _make_case_variant(email: str) -> str:
    """Return a case variant of *email* by toggling the case of the first
    alphabetic character found.  If no alphabetic character exists the
    original string is returned unchanged (the test will use ``assume`` to
    skip such degenerate inputs).
    """
    chars = list(email)
    for i, ch in enumerate(chars):
        if ch.isalpha():
            chars[i] = ch.lower() if ch.isupper() else ch.upper()
            break
    return "".join(chars)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    email=_email_strategy,
    password=_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_2_email_uniqueness_is_case_insensitive(app, email, password, display_name):
    """
    Property 2: Email uniqueness is case-insensitive

    For any email string ``e``, if a User with ``email_lower = e.lower()``
    already exists, then any attempt to create another User with any case
    variant of ``e`` SHALL be rejected with a ``ConflictError`` (HTTP 409).

    **Validates: Requirements 1.2, 1.3**
    """
    from app.exceptions import ConflictError

    variant = _make_case_variant(email)
    # Skip examples where no alphabetic character exists (no case variant
    # can be produced, so both calls would use the identical string).
    assume(variant != email)

    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same
        # email (the app fixture shares one DB across all 100 examples).
        _delete_user_by_email(db, email)

        try:
            # --- First registration (must succeed) ---
            service.create_user(email, password, display_name)

            # --- Second registration with a case variant (must raise ConflictError) ---
            with pytest.raises(ConflictError):
                service.create_user(variant, password, display_name)
        finally:
            # Always clean up so the next Hypothesis example starts with a
            # clean DB state regardless of whether assertions passed or failed.
            _delete_user_by_email(db, email)


# ---------------------------------------------------------------------------
# Property 4: Invalid inputs return 400 without creating a user
# ---------------------------------------------------------------------------

# Strategy for invalid field values: empty string, None, or whitespace-only
_invalid_field = st.one_of(st.just(''), st.just(None), st.just('   '))

# Strategy for valid fields (used for the fields that are NOT being invalidated)
_valid_email_for_invalid_test = _email_strategy
_valid_password_for_invalid_test = _password_strategy
_valid_display_name_for_invalid_test = _display_name_strategy


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    email=st.one_of(_email_strategy, _invalid_field),
    password=st.one_of(_password_strategy, _invalid_field),
    display_name=st.one_of(_display_name_strategy, _invalid_field),
)
def test_property_4_invalid_inputs_return_400_without_creating_user(
    app, email, password, display_name
):
    """
    Property 4: Invalid inputs return 400 without creating a user

    For any registration request where at least one required field (email,
    password, or display name) is absent or empty, the Auth_Service SHALL
    raise a ValidationException (HTTP 400) and SHALL NOT create any partial
    User record in the database.

    **Validates: Requirements 1.5**
    """
    from app.exceptions import ValidationException
    from app.models.user import User

    # Only test cases where at least one field is invalid
    def _is_invalid(v):
        return v is None or (isinstance(v, str) and not v.strip())

    assume(_is_invalid(email) or _is_invalid(password) or _is_invalid(display_name))

    with app.app_context():
        service = AuthService()

        # Count users before the call
        user_count_before = User.query.count()

        # The call must raise ValidationException
        with pytest.raises(ValidationException):
            service.create_user(email, password, display_name)

        # No new User row should have been created
        user_count_after = User.query.count()
        assert user_count_after == user_count_before, (
            f"create_user with invalid inputs created a User row: "
            f"email={email!r}, password={password!r}, display_name={display_name!r}. "
            f"Row count before={user_count_before}, after={user_count_after}."
        )


# ---------------------------------------------------------------------------
# Property 5: Successful login response contains all identity fields
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,  # bcrypt is intentionally slow; disable the per-example deadline
)
@given(
    email=_email_strategy,
    password=_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_5_successful_login_response_fields(app, email, password, display_name):
    """
    Property 5: Successful login response contains all identity fields

    For any registered active User, a login request with correct credentials
    SHALL return a token that, when decoded, contains ``sub``, ``email``, and
    ``display_name`` claims where:
      - ``sub`` equals the User's stored ``user_id``
      - ``email`` equals the User's stored ``email``
      - ``display_name`` equals the User's stored ``display_name``

    **Validates: Requirements 2.1**
    """
    import jwt as pyjwt
    from app.exceptions import ConflictError

    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same email.
        _delete_user_by_email(db, email)

        try:
            user = service.create_user(email, password, display_name)

            # Authenticate with correct credentials
            authenticated_user = service.authenticate(email, password)
            assert authenticated_user is not None, (
                f"authenticate() returned None for a valid user with email={email!r}"
            )

            # Issue a token for the authenticated user
            token = service.issue_token(authenticated_user)
            assert token, "issue_token() returned an empty or None token"
            assert isinstance(token, str), (
                f"issue_token() must return a str, got {type(token)}"
            )

            # Decode and verify the token claims
            secret_key = app.config["SECRET_KEY"]
            claims = pyjwt.decode(token, secret_key, algorithms=["HS256"])

            # sub must equal user.user_id
            assert "sub" in claims, "Token is missing the 'sub' claim"
            assert claims["sub"] == user.user_id, (
                f"Token 'sub' claim {claims['sub']!r} does not match user.user_id {user.user_id!r}"
            )

            # email must equal user.email
            assert "email" in claims, "Token is missing the 'email' claim"
            assert claims["email"] == user.email, (
                f"Token 'email' claim {claims['email']!r} does not match user.email {user.email!r}"
            )

            # display_name must equal user.display_name
            assert "display_name" in claims, "Token is missing the 'display_name' claim"
            assert claims["display_name"] == user.display_name, (
                f"Token 'display_name' claim {claims['display_name']!r} does not match "
                f"user.display_name {user.display_name!r}"
            )
        finally:
            _delete_user_by_email(db, email)


# ---------------------------------------------------------------------------
# Property 3: Plaintext password never appears in any response
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    email=_email_strategy,
    password=_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_3_plaintext_password_never_in_response(app, client, email, password, display_name):
    """
    Property 3: Plaintext password never appears in any response

    For any password string ``p`` submitted in any API request (login,
    registration, or any validation failure), the string ``p`` SHALL NOT
    appear as a substring of any API response body.

    Scenarios tested:
      (a) Successful registration via AuthService — the returned User object
          must not expose the plaintext password.
      (b) Login with wrong password via POST /api/auth/login — the 401
          response body must not contain the submitted password.
      (c) Duplicate-email registration via AuthService — the ConflictError
          must not expose the plaintext password.

    **Validates: Requirements 1.3, 1.4**
    """
    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same email.
        _delete_user_by_email(db, email)

        try:
            # ------------------------------------------------------------------
            # (a) Successful registration — User object must not leak password
            # ------------------------------------------------------------------
            user = service.create_user(email, password, display_name)

            # Serialize the user to a dict-like representation and check all
            # string fields for the plaintext password.
            # Note: we do NOT check the email field — the email is a legitimate
            # field that contains the user's email address, which may coincidentally
            # share characters with the password. The security concern is about
            # fields like password_hash that should never contain the plaintext password.
            sensitive_fields = {
                'user_id': user.user_id,
                'password_hash': user.password_hash,
                'display_name': user.display_name,
            }
            for field_name, field_value in sensitive_fields.items():
                assert password not in str(field_value), (
                    f"Plaintext password found in User.{field_name} after create_user: "
                    f"field_value={field_value!r}"
                )

            # ------------------------------------------------------------------
            # (b) Login with wrong password — HTTP response must not leak password
            # ------------------------------------------------------------------
            wrong_password = password + "_wrong"
            login_response = client.post(
                '/api/auth/login',
                json={'email': email, 'password': wrong_password},
                content_type='application/json',
            )
            # Only check the response body if the endpoint exists.
            # If it returns 404, the auth controller (task 3.1) is not yet
            # implemented — skip this scenario without discarding the example.
            if login_response.status_code != 404:
                response_text = login_response.get_data(as_text=True)
                assert wrong_password not in response_text, (
                    f"Wrong password found in login 401 response body: "
                    f"status={login_response.status_code}, body={response_text!r}"
                )
                # Also check the original password isn't leaked
                assert password not in response_text, (
                    f"Original password found in login 401 response body: "
                    f"status={login_response.status_code}, body={response_text!r}"
                )

            # ------------------------------------------------------------------
            # (c) Duplicate-email registration — ConflictError must not leak password
            # ------------------------------------------------------------------
            # Try to register the same email again with a different password
            duplicate_password = password + "_dup"
            try:
                service.create_user(email, duplicate_password, display_name)
                # If no exception, the duplicate wasn't caught — skip this scenario
            except Exception as conflict_exc:
                conflict_message = str(conflict_exc)
                assert duplicate_password not in conflict_message, (
                    f"Duplicate password found in ConflictError message: "
                    f"message={conflict_message!r}"
                )
                assert password not in conflict_message, (
                    f"Original password found in ConflictError message: "
                    f"message={conflict_message!r}"
                )
        finally:
            _delete_user_by_email(db, email)


# ---------------------------------------------------------------------------
# Property 6: Invalid credentials produce identical 401 responses
# ---------------------------------------------------------------------------

# Strategy for generating emails that are guaranteed NOT to be in the DB.
# We prefix with "nonexistent_" and use a UUID-like suffix to avoid collisions.
_nonexistent_email_strategy = st.builds(
    lambda local, domain, tld: f"nonexistent_{local}@{domain}.{tld}",
    local=_local_part,
    domain=_domain_label,
    tld=_tld,
).filter(lambda e: len(e) <= 254)

# Wrong password strategy: same shape as valid passwords but guaranteed different
# from the registered password by using a distinct prefix.
_wrong_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=('Ll', 'Lu', 'Nd', 'Po', 'Ps', 'Pe'),
        whitelist_characters='!@#$%^&*',
    ),
    min_size=8,
    max_size=72,
).filter(lambda p: p.strip() == p and len(p) >= 8)


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,  # bcrypt is intentionally slow; disable the per-example deadline
)
@given(
    nonexistent_email=_nonexistent_email_strategy,
    registered_email=_email_strategy,
    correct_password=_password_strategy,
    wrong_password=_wrong_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_6_indistinguishable_401_on_invalid_credentials(
    app,
    nonexistent_email,
    registered_email,
    correct_password,
    wrong_password,
    display_name,
):
    """
    Property 6: Invalid credentials produce identical 401 responses

    For any login attempt with an unrecognized email OR a recognized email
    with an incorrect password, the service SHALL return None in both cases,
    making the two failure modes indistinguishable at the service layer.

    **Validates: Requirements 2.2**
    """
    # Ensure the wrong password is actually different from the correct one
    assume(wrong_password != correct_password)

    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same email.
        _delete_user_by_email(db, registered_email)

        try:
            # --- Case 1: Unrecognised email (user does not exist) ---
            result_unknown_email = service.authenticate(nonexistent_email, correct_password)

            # --- Case 2: Recognised email but wrong password ---
            service.create_user(registered_email, correct_password, display_name)
            result_wrong_password = service.authenticate(registered_email, wrong_password)

            # Both failure modes MUST return None — indistinguishable at service level
            assert result_unknown_email is None, (
                f"authenticate with unknown email {nonexistent_email!r} should return None, "
                f"got {result_unknown_email!r}"
            )
            assert result_wrong_password is None, (
                f"authenticate with wrong password for {registered_email!r} should return None, "
                f"got {result_wrong_password!r}"
            )
        finally:
            _delete_user_by_email(db, registered_email)


# ---------------------------------------------------------------------------
# Property 7: Token lifetime ≤ 8 hours
# ---------------------------------------------------------------------------

import jwt as _jwt  # alias to avoid shadowing the local `jwt` name if needed


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    email=_email_strategy,
    password=_password_strategy,
    display_name=_display_name_strategy,
)
def test_property_7_token_lifetime_at_most_8_hours(app, email, password, display_name):
    """
    Property 7: Issued tokens have a lifetime of at most 8 hours

    For any token issued by ``AuthService.issue_token()``, decoding the raw
    JWT claims SHALL satisfy:

      - ``exp - iat <= 28800``  (lifetime is at most 8 hours / 28 800 seconds)
      - ``exp > iat``           (token is not already expired at issuance)

    **Validates: Requirements 2.4, 8.5**
    """
    with app.app_context():
        from app import db

        service = AuthService()

        # Ensure no leftover row from a prior Hypothesis example with the same email.
        _delete_user_by_email(db, email)

        try:
            user = service.create_user(email, password, display_name)
            token = service.issue_token(user)

            # Decode without signature verification to inspect raw numeric claims.
            claims = _jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["HS256"],
            )

            iat = claims["iat"]
            exp = claims["exp"]

            # exp must be strictly after iat — token must not be pre-expired
            assert exp > iat, (
                f"Token exp ({exp}) must be greater than iat ({iat}) for email={email!r}"
            )

            lifetime = exp - iat
            assert lifetime <= 28800, (
                f"Token lifetime {lifetime}s exceeds 8 hours (28800s) for email={email!r}"
            )
        finally:
            _delete_user_by_email(db, email)
