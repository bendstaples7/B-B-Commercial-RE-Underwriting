"""Unit tests for HubSpotWebhookService.verify_signature."""
import base64
import hashlib
import hmac
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.hubspot_config import HubSpotConfig
from app.services.hubspot_webhook_service import HubSpotWebhookService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(secret: str, method: str, uri: str, body: bytes, ts: str) -> str:
    """Compute the expected HubSpot v3 HMAC-SHA256 signature."""
    body_str = body.decode('utf-8')
    message = f"{method}{uri}{body_str}{ts}".encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode('utf-8')


def _encrypt_secret(raw_secret: str) -> str:
    """Fernet-encrypt *raw_secret* using the test HUBSPOT_ENCRYPTION_KEY."""
    from cryptography.fernet import Fernet
    key = os.environ['HUBSPOT_ENCRYPTION_KEY']
    f = Fernet(key.encode())
    return f.encrypt(raw_secret.encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def fernet_key():
    """Generate a stable Fernet key for the test module."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


@pytest.fixture
def app_with_secret(fernet_key):
    """Flask app with an in-memory SQLite DB and a HubSpotConfig row that has
    an encrypted client secret."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

    application = create_app('testing')
    application.config['TESTING'] = True

    with application.app_context():
        db.create_all()

        # We need a minimal encrypted_token too (HubSpotConfig requires it)
        from cryptography.fernet import Fernet
        f = Fernet(fernet_key.encode())
        dummy_token = f.encrypt(b'dummy-token').decode()
        encrypted_secret = _encrypt_secret('my-test-secret')

        config = HubSpotConfig(
            encrypted_token=dummy_token,
            encrypted_client_secret=encrypted_secret,
        )
        db.session.add(config)
        db.session.commit()

        yield application

        db.session.remove()
        db.drop_all()

    for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
        os.environ.pop(key, None)


@pytest.fixture
def app_no_secret(fernet_key):
    """Flask app with a HubSpotConfig that has NO client secret configured."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

    application = create_app('testing')
    application.config['TESTING'] = True

    with application.app_context():
        db.create_all()

        from cryptography.fernet import Fernet
        f = Fernet(fernet_key.encode())
        dummy_token = f.encrypt(b'dummy-token').decode()

        config = HubSpotConfig(
            encrypted_token=dummy_token,
            encrypted_client_secret=None,  # no secret
        )
        db.session.add(config)
        db.session.commit()

        yield application

        db.session.remove()
        db.drop_all()

    for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVerifySignatureValid:
    """verify_signature returns True for a correctly signed, fresh request."""

    def test_valid_signature_returns_true(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', body, ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=ts,
            )
            assert result is True


class TestVerifySignatureInvalid:
    """verify_signature returns False when the signature does not match."""

    def test_wrong_signature_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))

            result = svc.verify_signature(
                raw_body=body,
                signature_header='deadbeefdeadbeef',
                timestamp_header=ts,
            )
            assert result is False

    def test_tampered_body_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            original_body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            tampered_body = b'[{"subscriptionType":"deal.creation","objectId":999}]'
            ts = str(int(time.time()))
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', original_body, ts)

            result = svc.verify_signature(
                raw_body=tampered_body,
                signature_header=sig,
                timestamp_header=ts,
            )
            assert result is False


class TestVerifySignatureMissingHeader:
    """verify_signature returns False when the signature header is absent or empty."""

    def test_none_signature_header_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))

            result = svc.verify_signature(
                raw_body=body,
                signature_header=None,
                timestamp_header=ts,
            )
            assert result is False

    def test_empty_signature_header_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))

            result = svc.verify_signature(
                raw_body=body,
                signature_header='',
                timestamp_header=ts,
            )
            assert result is False

    def test_none_timestamp_header_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', body, ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=None,
            )
            assert result is False


class TestVerifySignatureStaleTimestamp:
    """verify_signature returns False when the timestamp is more than 5 minutes old."""

    def test_stale_timestamp_returns_false(self, app_with_secret):
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            # 6 minutes ago
            stale_ts = str(int(time.time()) - 360)
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', body, stale_ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=stale_ts,
            )
            assert result is False

    def test_future_timestamp_beyond_window_returns_false(self, app_with_secret):
        """A timestamp more than 5 minutes in the future is also rejected."""
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            future_ts = str(int(time.time()) + 360)
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', body, future_ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=future_ts,
            )
            assert result is False

    def test_fresh_timestamp_within_window_returns_true(self, app_with_secret):
        """A timestamp 4 minutes old (within the 5-minute window) is accepted."""
        with app_with_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            fresh_ts = str(int(time.time()) - 240)  # 4 minutes ago
            sig = _make_signature('my-test-secret', 'POST', '/api/hubspot/webhook', body, fresh_ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=fresh_ts,
            )
            assert result is True


class TestVerifySignatureNoSecret:
    """verify_signature returns False when no client secret is configured."""

    def test_no_client_secret_returns_false(self, app_no_secret):
        with app_no_secret.app_context():
            svc = HubSpotWebhookService()
            body = b'[{"subscriptionType":"deal.creation","objectId":123}]'
            ts = str(int(time.time()))
            # Even a "correct" signature should fail because there's no secret
            sig = _make_signature('any-secret', 'POST', '/api/hubspot/webhook', body, ts)

            result = svc.verify_signature(
                raw_body=body,
                signature_header=sig,
                timestamp_header=ts,
            )
            assert result is False
