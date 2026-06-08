"""Property-based tests for the admin panel feature.

Feature: admin-panel
"""
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from unittest.mock import MagicMock
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Property 1: JWT is_admin claim round-trip
# ---------------------------------------------------------------------------

@given(is_admin=st.booleans())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_jwt_is_admin_claim_round_trip(is_admin, app):
    """For any user with a given is_admin value, the JWT issued by
    AuthService.issue_token SHALL contain an is_admin claim that is a
    boolean equal to the user's is_admin field.

    **Validates: Requirements 1.4**
    """
    with app.app_context():
        from app.services.auth_service import AuthService
        import jwt as pyjwt
        from flask import current_app

        # Build a mock user with the given is_admin value
        mock_user = MagicMock()
        mock_user.user_id = 'test-user-id'
        mock_user.email = 'test@example.com'
        mock_user.display_name = 'Test User'
        mock_user.is_admin = is_admin

        # Issue a token
        token = AuthService().issue_token(mock_user)

        # Decode the JWT (with verification)
        payload = pyjwt.decode(
            token,
            current_app.config['SECRET_KEY'],
            algorithms=['HS256']
        )

        # Assert is_admin claim is present, is a boolean, and matches the user
        assert 'is_admin' in payload, "JWT payload must contain is_admin claim"
        assert isinstance(payload['is_admin'], bool), "is_admin claim must be a boolean"
        assert payload['is_admin'] == is_admin, (
            f"Expected is_admin={is_admin}, got {payload['is_admin']}"
        )


# ---------------------------------------------------------------------------
# Helpers for seeding test data
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timedelta
from app import db
from app.models.user import User


def _make_user(email_suffix: str, created_at: datetime = None, is_admin: bool = False) -> User:
    """Create and add a User to the session (not committed)."""
    uid = str(uuid.uuid4())
    email = f'user_{uid[:8]}@{email_suffix}'
    user = User(
        user_id=uid,
        email=email,
        email_lower=email.lower(),
        password_hash='hashed_password',
        display_name=f'User {uid[:8]}',
        is_active=True,
        is_admin=is_admin,
        created_at=created_at or datetime.utcnow(),
    )
    db.session.add(user)
    return user


# ---------------------------------------------------------------------------
# Property 4: User list excludes credential fields
# ---------------------------------------------------------------------------

@given(user_count=st.integers(min_value=1, max_value=10))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_list_excludes_credential_fields(user_count, app):
    """For any set of users in the database, the response from AdminService.list_users()
    SHALL NOT include password_hash or any other credential field.

    **Validates: Requirements 3.1, 3.2**
    """
    with app.app_context():
        from app.services.admin_service import AdminService

        # Seed users
        for i in range(user_count):
            _make_user(f'test{i}.com')
        db.session.flush()

        try:
            result = AdminService().list_users()

            assert len(result) >= user_count, "Should return at least the seeded users"
            for user_dict in result:
                assert 'password_hash' not in user_dict, "password_hash must not be in user list response"
                # Verify expected fields are present
                assert 'user_id' in user_dict
                assert 'email' in user_dict
                assert 'display_name' in user_dict
                assert 'is_active' in user_dict
                assert 'is_admin' in user_dict
                assert 'created_at' in user_dict
        finally:
            # Clean up seeded data
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 5: User list ordering invariant
# ---------------------------------------------------------------------------

@given(user_count=st.integers(min_value=2, max_value=20))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_list_ordering_invariant(user_count, app):
    """For any set of users with distinct created_at timestamps, the array
    returned by AdminService.list_users() SHALL be sorted ascending by created_at.

    **Validates: Requirements 3.4**
    """
    with app.app_context():
        from app.services.admin_service import AdminService

        # Seed users with distinct created_at values (1 second apart)
        base_time = datetime.utcnow() - timedelta(seconds=user_count)
        for i in range(user_count):
            _make_user(f'order{i}.com', created_at=base_time + timedelta(seconds=i))
        db.session.flush()

        try:
            result = AdminService().list_users()

            # Filter to only the users we seeded (there may be others)
            # The result should be sorted ascending by created_at
            created_ats = [r['created_at'] for r in result if r['created_at'] is not None]
            assert created_ats == sorted(created_ats), (
                f"User list must be sorted ascending by created_at, got: {created_ats}"
            )
        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 6: User summary count accuracy
# ---------------------------------------------------------------------------

@given(
    lead_count=st.integers(min_value=0, max_value=10),
    list_count=st.integers(min_value=0, max_value=5),
    job_count=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_summary_count_accuracy(lead_count, list_count, job_count, app):
    """For any user with N leads, M marketing lists, and K import jobs,
    AdminService.get_user_summary() SHALL return lead_count=N, marketing_list_count=M,
    import_job_count=K.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    with app.app_context():
        from app.services.admin_service import AdminService
        from app.models.lead import Property as Lead
        from app.models.marketing import MarketingList
        from app.models.import_job import ImportJob

        # Seed a user
        user = _make_user('summary_test.com')
        db.session.flush()  # get user.user_id

        # Seed leads — property_street has a unique constraint so use uuid-based values
        for _ in range(lead_count):
            lead = Lead(
                owner_user_id=user.user_id,
                property_street=f'Test St {uuid.uuid4().hex[:8]}',
                lead_status='awaiting_skip_trace',
                lead_score=50,
            )
            db.session.add(lead)

        # Seed marketing lists
        for _ in range(list_count):
            ml = MarketingList(
                user_id=user.user_id,
                name=f'List {uuid.uuid4().hex[:6]}',
            )
            db.session.add(ml)

        # Seed import jobs
        for _ in range(job_count):
            job = ImportJob(
                user_id=user.user_id,
                spreadsheet_id=f'sheet_{uuid.uuid4().hex[:8]}',
                sheet_name='Sheet1',
                status='completed',
                total_rows=0,
                rows_processed=0,
                rows_imported=0,
                rows_skipped=0,
            )
            db.session.add(job)

        db.session.commit()

        try:
            summary = AdminService().get_user_summary(user.user_id)
            assert summary['lead_count'] == lead_count, (
                f"Expected lead_count={lead_count}, got {summary['lead_count']}"
            )
            assert summary['marketing_list_count'] == list_count, (
                f"Expected marketing_list_count={list_count}, got {summary['marketing_list_count']}"
            )
            assert summary['import_job_count'] == job_count, (
                f"Expected import_job_count={job_count}, got {summary['import_job_count']}"
            )
        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 7: Cross-user lead visibility
# ---------------------------------------------------------------------------

@given(user_count=st.integers(1, 5), leads_per_user=st.integers(0, 10))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_cross_user_lead_visibility(user_count, leads_per_user, app):
    """For any set of leads owned by different users, AdminService.list_leads(None, 1, 200)
    SHALL return all leads regardless of owner_user_id, and each lead record SHALL include
    the owner_display_name of the owning user.

    **Validates: Requirements 5.1**
    """
    with app.app_context():
        from app.services.admin_service import AdminService
        from app.models.lead import Property as Lead

        # Seed users each with leads_per_user leads
        users = []
        for i in range(user_count):
            user = _make_user(f'crossuser{i}.com')
            users.append(user)
        db.session.flush()  # get user_ids

        expected_total = user_count * leads_per_user
        for user in users:
            for _ in range(leads_per_user):
                lead = Lead(
                    owner_user_id=user.user_id,
                    property_street=f'Test St {uuid.uuid4().hex[:8]}',
                    lead_status='awaiting_skip_trace',
                    lead_score=50,
                )
                db.session.add(lead)

        db.session.commit()

        try:
            result = AdminService().list_leads(None, 1, 200)

            # All seeded leads must appear in the result
            assert result['total_count'] >= expected_total, (
                f"Expected at least {expected_total} leads, got total_count={result['total_count']}"
            )

            # Every lead in the response must have owner_display_name
            for lead_dict in result['leads']:
                assert 'owner_display_name' in lead_dict, (
                    f"Lead {lead_dict.get('id')} is missing owner_display_name"
                )
                assert lead_dict['owner_display_name'] is not None, (
                    f"Lead {lead_dict.get('id')} has null owner_display_name"
                )

            # Verify all seeded owner_user_ids appear in the results (when leads_per_user > 0)
            if leads_per_user > 0:
                returned_owner_ids = {lead_dict['owner_user_id'] for lead_dict in result['leads']}
                seeded_owner_ids = {user.user_id for user in users}
                assert seeded_owner_ids.issubset(returned_owner_ids), (
                    f"Not all seeded owners appear in results. "
                    f"Missing: {seeded_owner_ids - returned_owner_ids}"
                )
        finally:
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 3: require_admin guards all admin routes
# ---------------------------------------------------------------------------

ADMIN_ROUTES = [
    ('GET', '/api/admin/users'),
    ('GET', '/api/admin/users/some-user-id/summary'),
    ('GET', '/api/admin/leads'),
]


@given(route=st.sampled_from(ADMIN_ROUTES))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_require_admin_guards_all_routes(route, client, app):
    """For any route registered under /api/admin, a request carrying a valid
    JWT with is_admin=False SHALL receive HTTP 403 with the correct body.

    **Validates: Requirements 2.1, 2.2, 2.4**

    NOTE: This test depends on task 4.2 (admin_bp blueprint registration).
    If the blueprint is not yet registered, routes return 404 and the test
    is skipped automatically.
    """
    with app.app_context():
        from app.services.auth_service import AuthService

        method, path = route

        # Build a non-admin user token
        mock_user = MagicMock()
        mock_user.user_id = 'non-admin-user-id'
        mock_user.email = 'nonadmin@example.com'
        mock_user.display_name = 'Non Admin'
        mock_user.is_admin = False

        token = AuthService().issue_token(mock_user)

        # Make the request with the non-admin token
        headers = {'Authorization': f'Bearer {token}'}
        if method == 'GET':
            response = client.get(path, headers=headers)
        else:
            response = client.post(path, headers=headers)

        # If the blueprint isn't registered, the route returns 404 — that is a
        # registration regression and must fail the test immediately.
        assert response.status_code != 404, (
            f"Route {method} {path} returned 404 — admin_bp is not registered. "
            "Ensure admin_bp is imported and registered in app/__init__.py."
        )

        assert response.status_code == 403, (
            f"Expected 403 for {method} {path} with non-admin token, "
            f"got {response.status_code}"
        )
        data = response.get_json()
        assert data is not None
        assert data.get('error') == 'Forbidden'
        assert data.get('message') == 'Admin access required.'


# ---------------------------------------------------------------------------
# Property 5: User list ordering invariant
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Property 8: Lead filter correctness
# ---------------------------------------------------------------------------

@given(owner_user_id=st.uuids())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_lead_filter_correctness(owner_user_id, app):
    """For any owner_user_id filter value, every lead returned by
    AdminService.list_leads(owner_user_id, ...) SHALL have owner_user_id equal
    to the filter value, and no lead with a different owner_user_id SHALL appear.

    When the filter value matches no leads (e.g. a random UUID with no seeded
    leads), the result is an empty list — which is still correct.

    **Validates: Requirements 5.2**
    """
    with app.app_context():
        from app.services.admin_service import AdminService
        from app.models.lead import Property as Lead

        owner_user_id_str = str(owner_user_id)

        # Seed two "other" users whose leads must NOT appear in filtered results
        other_user_a = _make_user('filter_other_a.com')
        other_user_b = _make_user('filter_other_b.com')
        db.session.flush()

        # Seed a few leads for the other users
        for i in range(3):
            db.session.add(Lead(
                owner_user_id=other_user_a.user_id,
                property_street=f'Other A St {uuid.uuid4().hex[:8]}',
                lead_status='awaiting_skip_trace',
                lead_score=50,
            ))
            db.session.add(Lead(
                owner_user_id=other_user_b.user_id,
                property_street=f'Other B St {uuid.uuid4().hex[:8]}',
                lead_status='awaiting_skip_trace',
                lead_score=50,
            ))

        # Conditionally seed leads for the target owner_user_id.
        # The target UUID may or may not correspond to a real user — we only
        # seed leads for it when we can create a matching user record.
        # If the UUID happens to collide with an existing user (extremely rare
        # with random UUIDs), we skip seeding to avoid a unique-constraint error.
        target_lead_count = 0
        existing = db.session.execute(
            text('SELECT 1 FROM users WHERE user_id = :uid'),
            {'uid': owner_user_id_str},
        ).fetchone()
        if existing is None:
            target_user = _make_user('filter_target.com')
            # Override the auto-generated user_id with the hypothesis-generated one
            target_user.user_id = owner_user_id_str
            db.session.flush()
            for i in range(2):
                db.session.add(Lead(
                    owner_user_id=owner_user_id_str,
                    property_street=f'Target St {uuid.uuid4().hex[:8]}',
                    lead_status='awaiting_skip_trace',
                    lead_score=75,
                ))
            target_lead_count = 2

        db.session.commit()

        try:
            result = AdminService().list_leads(owner_user_id_str, 1, 200)
            leads = result['leads']

            # Core property: every returned lead must belong to the requested owner.
            # No lead with a different owner_user_id may appear in the results.
            for lead in leads:
                assert lead['owner_user_id'] == owner_user_id_str, (
                    f"Filter violation: expected owner_user_id={owner_user_id_str!r}, "
                    f"got {lead['owner_user_id']!r}"
                )

            # If we seeded leads for the target user, at least those must appear.
            # (There may be more from prior Hypothesis examples sharing the same DB.)
            assert len(leads) >= target_lead_count, (
                f"Expected at least {target_lead_count} leads for owner {owner_user_id_str}, "
                f"got {len(leads)}"
            )
        finally:
            db.session.rollback()


@given(user_count=st.integers(min_value=2, max_value=20))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_list_ordering(user_count, app):
    """For any set of users with distinct created_at timestamps, the array
    returned by list_users() SHALL be sorted ascending by created_at.

    **Validates: Requirements 3.4**
    """
    with app.app_context():
        from app import db
        from app.services.admin_service import AdminService
        from app.models.user import User

        # Clean up any existing users
        db.session.query(User).delete()
        db.session.commit()

        # Create users with distinct created_at timestamps (spaced 1 second apart)
        base_time = datetime(2020, 1, 1, 0, 0, 0)
        # Shuffle the order of insertion to ensure ordering is by created_at, not insertion order
        import random
        indices = list(range(user_count))
        random.shuffle(indices)
        for i in indices:
            uid = str(uuid.uuid4())
            user = User(
                user_id=uid,
                email=f'order{i}{uid[:8]}@example.com',
                email_lower=f'order{i}{uid[:8]}@example.com',
                password_hash='hashed',
                display_name=f'User {i}',
                is_active=True,
                is_admin=False,
                created_at=base_time + timedelta(seconds=i),
            )
            db.session.add(user)
        db.session.commit()

        # Call the service
        users = AdminService().list_users()

        # Assert sorted ascending by created_at
        assert len(users) == user_count
        created_ats = [u['created_at'] for u in users]
        assert created_ats == sorted(created_ats), (
            f"User list is not sorted ascending by created_at: {created_ats}"
        )


# ---------------------------------------------------------------------------
# Property 9: Pagination envelope correctness
# ---------------------------------------------------------------------------

PAGINATION_SEED_COUNT = 50  # fixed number of leads seeded for pagination tests


@given(page=st.integers(1, 10), page_size=st.integers(1, 200))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_pagination_envelope_correctness(page, page_size, app):
    """For any valid page and page_size combination, the response from
    AdminService.list_leads() SHALL include a total_count equal to the actual
    number of matching leads in the database, and the leads array SHALL contain
    exactly min(page_size, max(0, total - offset)) items.

    **Validates: Requirements 5.3**
    """
    with app.app_context():
        from app.services.admin_service import AdminService
        from app.models.lead import Property as Lead
        from app.models.user import User

        # Clean up any data left by previous Hypothesis iterations so the
        # total_count is always exactly PAGINATION_SEED_COUNT.
        db.session.query(Lead).delete()
        db.session.query(User).delete()
        db.session.commit()

        # Seed a single owner user and exactly PAGINATION_SEED_COUNT leads
        owner = _make_user('pagination_test.com')
        db.session.flush()

        for i in range(PAGINATION_SEED_COUNT):
            lead = Lead(
                owner_user_id=owner.user_id,
                property_street=f'Pagination St {uuid.uuid4().hex}',
                lead_status='awaiting_skip_trace',
                lead_score=0,
            )
            db.session.add(lead)
        db.session.commit()

        try:
            result = AdminService().list_leads(None, page, page_size)

            total = result['total_count']
            leads = result['leads']

            # total_count must equal the actual number of leads in the DB
            assert total == PAGINATION_SEED_COUNT, (
                f"Expected total_count={PAGINATION_SEED_COUNT}, got {total}"
            )

            # leads array length must equal min(page_size, max(0, total - offset))
            offset = (page - 1) * page_size
            expected_len = min(page_size, max(0, total - offset))
            assert len(leads) == expected_len, (
                f"page={page}, page_size={page_size}, offset={offset}, "
                f"total={total}: expected {expected_len} leads, got {len(leads)}"
            )

            # page and page_size are echoed back correctly
            assert result['page'] == page
            assert result['page_size'] == page_size
        finally:
            db.session.rollback()

