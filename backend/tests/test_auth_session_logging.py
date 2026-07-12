"""Tests for PII-safe auth session logging (login issue + require_auth reject)."""
from datetime import datetime, timedelta

import jwt
import pytest

from app import db
from app.services.auth_service import AuthService


EXPECTED_LIFETIME = 30 * 24 * 3600  # 2592000


def _log_messages(caplog, logger_name: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger_name
    ]


class TestEmailDomainForLog:
    def test_extracts_domain_lowercased(self):
        assert AuthService.email_domain_for_log("Ben@Gmail.COM") == "gmail.com"

    def test_missing_at_is_unknown(self):
        assert AuthService.email_domain_for_log("not-an-email") == "unknown"

    def test_empty_is_unknown(self):
        assert AuthService.email_domain_for_log("") == "unknown"


class TestAuthLoginLogging:
    def test_successful_login_logs_lifetime(self, client, app, caplog):
        with app.app_context():
            AuthService().create_user(
                email="alice@example.com",
                password="securepass1",
                display_name="Alice",
            )

        with caplog.at_level("INFO", logger="app.controllers.auth_controller"):
            resp = client.post(
                "/api/auth/login",
                json={"email": "alice@example.com", "password": "securepass1"},
            )

        assert resp.status_code == 200
        messages = _log_messages(caplog, "app.controllers.auth_controller")
        ok_lines = [m for m in messages if m.startswith("auth_login_ok ")]
        assert len(ok_lines) == 1
        line = ok_lines[0]
        assert f"lifetime_seconds={EXPECTED_LIFETIME}" in line
        assert "iat=" in line
        assert "exp=" in line
        assert "session_token" not in line
        body = resp.get_json()
        assert body["user_id"] in line

    def test_failed_login_logs_domain_only(self, client, app, caplog):
        email = "secret.user@gmail.com"
        with app.app_context():
            AuthService().create_user(
                email=email,
                password="securepass1",
                display_name="Secret",
            )

        with caplog.at_level("WARNING", logger="app.controllers.auth_controller"):
            resp = client.post(
                "/api/auth/login",
                json={"email": email, "password": "wrong-password"},
            )

        assert resp.status_code == 401
        messages = _log_messages(caplog, "app.controllers.auth_controller")
        fail_lines = [m for m in messages if m.startswith("auth_login_fail ")]
        assert len(fail_lines) == 1
        line = fail_lines[0]
        assert "domain=gmail.com" in line
        assert "secret.user" not in line
        assert email not in line


class TestRequireAuthRejectLogging:
    def test_expired_token_logs_token_expired(self, client, app, caplog):
        with app.app_context():
            user = AuthService().create_user(
                email="expired@example.com",
                password="securepass1",
                display_name="Expired",
            )
            now = datetime.utcnow()
            token = jwt.encode(
                {
                    "sub": user.user_id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_admin": False,
                    "iat": now - timedelta(hours=2),
                    "exp": now - timedelta(hours=1),
                },
                app.config["SECRET_KEY"],
                algorithm="HS256",
            )

        with caplog.at_level("WARNING", logger="app.api_utils"):
            resp = client.get(
                "/api/admin/users",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Token expired"
        messages = _log_messages(caplog, "app.api_utils")
        reject_lines = [m for m in messages if "auth_reject reason=token_expired" in m]
        assert len(reject_lines) == 1
        assert "path=" in reject_lines[0]
        assert token not in reject_lines[0]

    def test_missing_user_logs_user_not_found(self, client, app, caplog):
        with app.app_context():
            now = datetime.utcnow()
            token = jwt.encode(
                {
                    "sub": "missing-user-id",
                    "email": "missing@example.com",
                    "display_name": "Missing",
                    "is_admin": False,
                    "iat": now,
                    "exp": now + timedelta(hours=1),
                },
                app.config["SECRET_KEY"],
                algorithm="HS256",
            )

        with caplog.at_level("WARNING", logger="app.api_utils"):
            resp = client.get(
                "/api/admin/users",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Authentication required"
        messages = _log_messages(caplog, "app.api_utils")
        not_found_lines = [
            m for m in messages if "auth_reject reason=user_not_found" in m
        ]
        assert len(not_found_lines) == 1
        assert "missing-user-id" in not_found_lines[0]
        assert token not in not_found_lines[0]

    def test_inactive_user_logs_user_inactive(self, client, app, caplog):
        with app.app_context():
            user = AuthService().create_user(
                email="inactive@example.com",
                password="securepass1",
                display_name="Inactive",
            )
            user.is_active = False
            db.session.commit()
            now = datetime.utcnow()
            token = jwt.encode(
                {
                    "sub": user.user_id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_admin": False,
                    "iat": now,
                    "exp": now + timedelta(hours=1),
                },
                app.config["SECRET_KEY"],
                algorithm="HS256",
            )

        with caplog.at_level("WARNING", logger="app.api_utils"):
            resp = client.get(
                "/api/admin/users",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Authentication required"
        messages = _log_messages(caplog, "app.api_utils")
        inactive_lines = [
            m for m in messages if "auth_reject reason=user_inactive" in m
        ]
        assert len(inactive_lines) == 1
        assert user.user_id in inactive_lines[0]
        assert token not in inactive_lines[0]
