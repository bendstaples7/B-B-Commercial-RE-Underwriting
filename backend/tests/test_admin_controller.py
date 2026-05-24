"""Unit tests for admin_controller.py — admin-only endpoints under /api/admin.

Tests cover:
  - require_admin returns 403 with correct body for non-admin user
  - require_admin returns 401 when no token is present
  - GET /api/admin/users returns all users ordered by created_at asc
  - GET /api/admin/users response never contains password_hash
  - GET /api/admin/users/<user_id>/summary returns 404 for unknown user_id
  - GET /api/admin/leads with page_size=201 returns 400
  - GET /api/admin/leads?owner_user_id=<id> returns only leads for that user

Requirements: 2.2, 2.3, 3.1, 3.2, 3.3, 4.5, 5.2, 5.3
"""
import json
import uuid
from datetime import datetime, timedelta

import pytest

from app import db
from app.models.user import User
from app.models import Lead
from app.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    email: str,
    display_name: str,
    is_admin: bool = False,
    created_at: datetime | None = None,
) -> User:
    """Create and persist a User record. Returns the committed User."""
    user = User(
        user_id=str(uuid.uuid4()),
        email=email,
        email_lower=email.lower(),
        password_hash="$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash",
        display_name=display_name,
        is_active=True,
        is_admin=is_admin,
        created_at=created_at or datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _make_lead(owner_user_id: str, property_street: str = "100 Test St") -> Lead:
    """Create and persist a Lead record owned by the given user."""
    lead = Lead(
        property_street=property_street,
        property_city="Chicago",
        property_state="IL",
        property_zip="60601",
        owner_first_name="John",
        owner_last_name="Doe",
        property_type="single_family",
        mailing_city="Chicago",
        mailing_state="IL",
        mailing_zip="60601",
        lead_score=50.0,
        owner_user_id=owner_user_id,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def _admin_token(app, user: User) -> str:
    """Issue a JWT for the given user using AuthService."""
    with app.app_context():
        return AuthService().issue_token(user)


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test: require_admin returns 403 for non-admin user
# ---------------------------------------------------------------------------

class TestRequireAdminForbidden:
    """require_admin returns 403 with the correct body for a non-admin user."""

    def test_non_admin_gets_403_on_users_endpoint(self, client, app):
        """A valid JWT with is_admin=False receives HTTP 403."""
        with app.app_context():
            user = _make_user("nonadmin@test.com", "Non Admin", is_admin=False)
            token = AuthService().issue_token(user)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        assert resp.status_code == 403

    def test_non_admin_403_body_is_correct(self, client, app):
        """The 403 response body matches the spec: error + message fields."""
        with app.app_context():
            user = _make_user("nonadmin2@test.com", "Non Admin 2", is_admin=False)
            token = AuthService().issue_token(user)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        data = json.loads(resp.data)
        assert data["error"] == "Forbidden"
        assert data["message"] == "Admin access required."

    def test_non_admin_gets_403_on_leads_endpoint(self, client, app):
        """Non-admin user is rejected on /api/admin/leads too."""
        with app.app_context():
            user = _make_user("nonadmin3@test.com", "Non Admin 3", is_admin=False)
            token = AuthService().issue_token(user)

        resp = client.get("/api/admin/leads", headers=_auth_headers(token))
        assert resp.status_code == 403

    def test_non_admin_gets_403_on_summary_endpoint(self, client, app):
        """Non-admin user is rejected on /api/admin/users/<id>/summary too."""
        with app.app_context():
            user = _make_user("nonadmin4@test.com", "Non Admin 4", is_admin=False)
            token = AuthService().issue_token(user)

        resp = client.get(
            f"/api/admin/users/{user.user_id}/summary",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: require_admin returns 401 when no token is present
# ---------------------------------------------------------------------------

class TestRequireAdminUnauthorized:
    """require_admin (via require_auth) returns 401 when no token is present."""

    def test_no_token_users_returns_401(self, client, app):
        """GET /api/admin/users with no auth header returns 401."""
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401

    def test_no_token_leads_returns_401(self, client, app):
        """GET /api/admin/leads with no auth header returns 401."""
        resp = client.get("/api/admin/leads")
        assert resp.status_code == 401

    def test_no_token_summary_returns_401(self, client, app):
        """GET /api/admin/users/<id>/summary with no auth header returns 401."""
        resp = client.get("/api/admin/users/some-user-id/summary")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: GET /api/admin/users returns all users ordered by created_at asc
# ---------------------------------------------------------------------------

class TestListUsersOrdering:
    """GET /api/admin/users returns all users ordered by created_at ascending."""

    def test_users_returned_in_created_at_asc_order(self, client, app):
        """Users are returned sorted by created_at ascending."""
        base = datetime(2024, 1, 1, 12, 0, 0)
        with app.app_context():
            admin = _make_user(
                "admin@test.com", "Admin User", is_admin=True,
                created_at=base,
            )
            _make_user("first@test.com", "First User", created_at=base + timedelta(hours=1))
            _make_user("second@test.com", "Second User", created_at=base + timedelta(hours=2))
            _make_user("third@test.com", "Third User", created_at=base + timedelta(hours=3))
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)
        assert len(data) == 4

        # Verify ascending order by created_at
        timestamps = [u["created_at"] for u in data]
        assert timestamps == sorted(timestamps), (
            f"Users not in ascending created_at order: {timestamps}"
        )

    def test_all_users_are_returned(self, client, app):
        """All users in the database appear in the response."""
        with app.app_context():
            admin = _make_user("admin2@test.com", "Admin 2", is_admin=True)
            _make_user("user_a@test.com", "User A")
            _make_user("user_b@test.com", "User B")
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        data = json.loads(resp.data)
        emails = {u["email"] for u in data}
        assert "admin2@test.com" in emails
        assert "user_a@test.com" in emails
        assert "user_b@test.com" in emails


# ---------------------------------------------------------------------------
# Test: GET /api/admin/users response never contains password_hash
# ---------------------------------------------------------------------------

class TestListUsersNoPasswordHash:
    """GET /api/admin/users response never contains password_hash."""

    def test_password_hash_absent_from_user_list(self, client, app):
        """No user object in the response contains a password_hash field."""
        with app.app_context():
            admin = _make_user("admin3@test.com", "Admin 3", is_admin=True)
            _make_user("regular@test.com", "Regular User")
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = json.loads(resp.data)
        for user_obj in data:
            assert "password_hash" not in user_obj, (
                f"password_hash found in user response for {user_obj.get('email')}"
            )

    def test_expected_fields_are_present(self, client, app):
        """Each user object contains the required fields."""
        with app.app_context():
            admin = _make_user("admin4@test.com", "Admin 4", is_admin=True)
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/users", headers=_auth_headers(token))
        data = json.loads(resp.data)
        required_fields = {"user_id", "email", "display_name", "is_active", "is_admin", "created_at"}
        for user_obj in data:
            for field in required_fields:
                assert field in user_obj, f"Field '{field}' missing from user response"


# ---------------------------------------------------------------------------
# Test: GET /api/admin/users/<user_id>/summary returns 404 for unknown user_id
# ---------------------------------------------------------------------------

class TestUserSummaryNotFound:
    """GET /api/admin/users/<user_id>/summary returns 404 for unknown user_id."""

    def test_unknown_user_id_returns_404(self, client, app):
        """A user_id that does not exist in the database returns HTTP 404."""
        with app.app_context():
            admin = _make_user("admin5@test.com", "Admin 5", is_admin=True)
            token = AuthService().issue_token(admin)

        nonexistent_id = str(uuid.uuid4())
        resp = client.get(
            f"/api/admin/users/{nonexistent_id}/summary",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    def test_known_user_id_returns_200(self, client, app):
        """A valid user_id returns HTTP 200 with summary fields."""
        with app.app_context():
            admin = _make_user("admin6@test.com", "Admin 6", is_admin=True)
            target = _make_user("target@test.com", "Target User")
            token = AuthService().issue_token(admin)
            target_id = target.user_id

        resp = client.get(
            f"/api/admin/users/{target_id}/summary",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["user_id"] == target_id
        assert "lead_count" in data
        assert "marketing_list_count" in data
        assert "import_job_count" in data


# ---------------------------------------------------------------------------
# Test: GET /api/admin/leads with page_size=201 returns 400
# ---------------------------------------------------------------------------

class TestLeadsPageSizeValidation:
    """GET /api/admin/leads with page_size > 200 returns 400."""

    def test_page_size_201_returns_400(self, client, app):
        """page_size=201 exceeds the maximum of 200 and returns HTTP 400."""
        with app.app_context():
            admin = _make_user("admin7@test.com", "Admin 7", is_admin=True)
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/leads?page_size=201", headers=_auth_headers(token))
        assert resp.status_code == 400

    def test_page_size_200_returns_200(self, client, app):
        """page_size=200 is the maximum allowed value and returns HTTP 200."""
        with app.app_context():
            admin = _make_user("admin8@test.com", "Admin 8", is_admin=True)
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/leads?page_size=200", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_page_size_400_error_body(self, client, app):
        """The 400 response body contains an error message about the limit."""
        with app.app_context():
            admin = _make_user("admin9@test.com", "Admin 9", is_admin=True)
            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/leads?page_size=500", headers=_auth_headers(token))
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data
        # The message should mention the limit
        message = data.get("message", "").lower()
        assert "200" in message or "page_size" in message


# ---------------------------------------------------------------------------
# Test: GET /api/admin/leads?owner_user_id=<id> returns only leads for that user
# ---------------------------------------------------------------------------

class TestLeadsOwnerFilter:
    """GET /api/admin/leads?owner_user_id=<id> returns only leads for that user."""

    def test_owner_filter_returns_only_matching_leads(self, client, app):
        """Leads from other users are excluded when owner_user_id filter is applied."""
        with app.app_context():
            admin = _make_user("admin10@test.com", "Admin 10", is_admin=True)
            user_a = _make_user("user_a2@test.com", "User A2")
            user_b = _make_user("user_b2@test.com", "User B2")

            _make_lead(user_a.user_id, "100 A Street")
            _make_lead(user_a.user_id, "101 A Street")
            _make_lead(user_b.user_id, "200 B Street")

            token = AuthService().issue_token(admin)
            user_a_id = user_a.user_id

        resp = client.get(
            f"/api/admin/leads?owner_user_id={user_a_id}",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        leads = data["leads"]

        # All returned leads must belong to user_a
        assert len(leads) == 2
        for lead in leads:
            assert lead["owner_user_id"] == user_a_id, (
                f"Lead {lead['id']} has owner_user_id={lead['owner_user_id']}, "
                f"expected {user_a_id}"
            )

    def test_owner_filter_excludes_other_users_leads(self, client, app):
        """No leads from other users appear in the filtered response."""
        with app.app_context():
            admin = _make_user("admin11@test.com", "Admin 11", is_admin=True)
            user_c = _make_user("user_c@test.com", "User C")
            user_d = _make_user("user_d@test.com", "User D")

            _make_lead(user_c.user_id, "300 C Street")
            _make_lead(user_d.user_id, "400 D Street")
            _make_lead(user_d.user_id, "401 D Street")

            token = AuthService().issue_token(admin)
            user_c_id = user_c.user_id

        resp = client.get(
            f"/api/admin/leads?owner_user_id={user_c_id}",
            headers=_auth_headers(token),
        )
        data = json.loads(resp.data)
        leads = data["leads"]

        # Only user_c's lead should appear
        assert len(leads) == 1
        assert leads[0]["owner_user_id"] == user_c_id

    def test_no_filter_returns_all_leads(self, client, app):
        """Without owner_user_id filter, leads from all users are returned."""
        with app.app_context():
            admin = _make_user("admin12@test.com", "Admin 12", is_admin=True)
            user_e = _make_user("user_e@test.com", "User E")
            user_f = _make_user("user_f@test.com", "User F")

            _make_lead(user_e.user_id, "500 E Street")
            _make_lead(user_f.user_id, "600 F Street")

            token = AuthService().issue_token(admin)

        resp = client.get("/api/admin/leads", headers=_auth_headers(token))
        data = json.loads(resp.data)
        assert data["total_count"] == 2
        owner_ids = {lead["owner_user_id"] for lead in data["leads"]}
        assert len(owner_ids) == 2
