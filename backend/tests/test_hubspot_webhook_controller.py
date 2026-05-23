"""Integration tests for the HubSpot webhook receiver endpoint.

Tests cover:
1. POST with valid signed payload → 200
2. POST with invalid signature → 401, no WebhookLog created
3. POST with wrong content type → 400
"""
import base64
import hashlib
import hmac
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.hubspot_config import HubSpotConfig
from app.models import HubSpotWebhookLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(secret: str, method: str, uri: str, body: bytes, ts: str) -> str:
    """Compute the expected HubSpot v3 HMAC-SHA256 signature."""
    body_str = body.decode('utf-8')
    message = f"{method}{uri}{body_str}{ts}".encode('utf-8')
    digest = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode('utf-8')


def _encrypt_secret(raw_secret: str, fernet_key: str) -> str:
    """Fernet-encrypt *raw_secret* using the given key."""
    from cryptography.fernet import Fernet
    f = Fernet(fernet_key.encode())
    return f.encrypt(raw_secret.encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLIENT_SECRET = 'test-client-secret-abc123'
WEBHOOK_URI = '/api/hubspot/webhook'
WEBHOOK_FULL_URL = 'http://localhost/api/hubspot/webhook'


@pytest.fixture(scope='module')
def fernet_key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


@pytest.fixture
def webhook_app(fernet_key):
    """Flask test app with a HubSpotConfig that has an encrypted client secret."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

    application = create_app('testing')
    application.config['TESTING'] = True
    application.config['RATELIMIT_ENABLED'] = False  # disable rate limiting in tests

    with application.app_context():
        db.create_all()

        from cryptography.fernet import Fernet
        f = Fernet(fernet_key.encode())
        dummy_token = f.encrypt(b'dummy-token').decode()
        encrypted_secret = _encrypt_secret(CLIENT_SECRET, fernet_key)

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
def webhook_client(webhook_app):
    return webhook_app.test_client()


# ---------------------------------------------------------------------------
# Helper: build a signed POST request
# ---------------------------------------------------------------------------

def _post_webhook(client, body: bytes, sig: str, ts: str,
                  content_type: str = 'application/json'):
    """POST to /api/hubspot/webhook with the given headers."""
    return client.post(
        WEBHOOK_URI,
        data=body,
        content_type=content_type,
        headers={
            'X-HubSpot-Signature-v3': sig,
            'X-HubSpot-Request-Timestamp': ts,
        },
    )


# ---------------------------------------------------------------------------
# Test 1: Valid signed payload → 200
# ---------------------------------------------------------------------------

class TestValidSignedPayload:
    """POST with a correctly signed payload returns 200 and queues events."""

    def test_returns_200_with_accepted_status(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        # Patch Celery dispatch so we don't need a real broker.
        # The service does a lazy import inside handle_batch; patch the module
        # attribute that the import resolves to.
        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch('app.services.hubspot_webhook_service.process_webhook_event', mock_task, create=True):
            resp = _post_webhook(webhook_client, body, sig, ts)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'accepted'
        assert data['count'] == 1

    def test_creates_webhook_log_record(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'contact.creation', 'objectId': 99}
        ]).encode('utf-8')
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        with webhook_app.app_context():
            initial_count = HubSpotWebhookLog.query.count()

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch('app.services.hubspot_webhook_service.process_webhook_event', mock_task, create=True):
            resp = _post_webhook(webhook_client, body, sig, ts)

        assert resp.status_code == 200

        with webhook_app.app_context():
            final_count = HubSpotWebhookLog.query.count()
            assert final_count == initial_count + 1
            log = HubSpotWebhookLog.query.order_by(HubSpotWebhookLog.id.desc()).first()
            assert log.hubspot_object_type == 'contact'
            assert log.hubspot_object_id == '99'
            assert log.status == 'pending'

    def test_accepts_batch_of_multiple_events(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.propertyChange', 'objectId': 1},
            {'subscriptionType': 'deal.propertyChange', 'objectId': 2},
            {'subscriptionType': 'deal.propertyChange', 'objectId': 3},
        ]).encode('utf-8')
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch('app.services.hubspot_webhook_service.process_webhook_event', mock_task, create=True):
            resp = _post_webhook(webhook_client, body, sig, ts)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 3

    def test_wraps_single_object_payload_in_list(self, webhook_app, webhook_client):
        """A single event dict (not a list) should be wrapped and accepted."""
        body = json.dumps(
            {'subscriptionType': 'deal.creation', 'objectId': 77}
        ).encode('utf-8')
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch('app.services.hubspot_webhook_service.process_webhook_event', mock_task, create=True):
            resp = _post_webhook(webhook_client, body, sig, ts)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1


# ---------------------------------------------------------------------------
# Test 2: Invalid signature → 401, no WebhookLog created
# ---------------------------------------------------------------------------

class TestInvalidSignature:
    """POST with an invalid signature returns 401 and creates no log records."""

    def test_wrong_signature_returns_401(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        ts = str(int(time.time()))

        resp = _post_webhook(webhook_client, body, 'deadbeefdeadbeef', ts)

        assert resp.status_code == 401
        data = resp.get_json()
        assert data['error'] == 'Invalid signature'

    def test_invalid_signature_creates_no_webhook_log(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        ts = str(int(time.time()))

        with webhook_app.app_context():
            count_before = HubSpotWebhookLog.query.count()

        resp = _post_webhook(webhook_client, body, 'badsignature', ts)

        assert resp.status_code == 401

        with webhook_app.app_context():
            count_after = HubSpotWebhookLog.query.count()
            assert count_after == count_before  # no new records

    def test_missing_signature_header_returns_401(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        ts = str(int(time.time()))

        resp = webhook_client.post(
            WEBHOOK_URI,
            data=body,
            content_type='application/json',
            headers={'X-HubSpot-Request-Timestamp': ts},
            # No X-HubSpot-Signature-v3 header
        )

        assert resp.status_code == 401

    def test_stale_timestamp_returns_401(self, webhook_app, webhook_client):
        body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        stale_ts = str(int(time.time()) - 400)  # 6+ minutes ago
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, stale_ts)

        resp = _post_webhook(webhook_client, body, sig, stale_ts)

        assert resp.status_code == 401

    def test_tampered_body_returns_401(self, webhook_app, webhook_client):
        original_body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 42}
        ]).encode('utf-8')
        tampered_body = json.dumps([
            {'subscriptionType': 'deal.creation', 'objectId': 999}
        ]).encode('utf-8')
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, original_body, ts)

        resp = _post_webhook(webhook_client, tampered_body, sig, ts)

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 3: Wrong content type → 400
# ---------------------------------------------------------------------------

class TestWrongContentType:
    """POST with a non-JSON content type returns 400."""

    def test_text_plain_returns_400(self, webhook_app, webhook_client):
        body = b'some plain text'
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        resp = _post_webhook(webhook_client, body, sig, ts,
                             content_type='text/plain')

        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Content-Type' in data['error']

    def test_form_encoded_returns_400(self, webhook_app, webhook_client):
        body = b'key=value'
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        resp = _post_webhook(webhook_client, body, sig, ts,
                             content_type='application/x-www-form-urlencoded')

        assert resp.status_code == 400

    def test_wrong_content_type_creates_no_webhook_log(self, webhook_app, webhook_client):
        body = b'not json'
        ts = str(int(time.time()))
        sig = _make_signature(CLIENT_SECRET, 'POST', WEBHOOK_FULL_URL, body, ts)

        with webhook_app.app_context():
            count_before = HubSpotWebhookLog.query.count()

        resp = _post_webhook(webhook_client, body, sig, ts,
                             content_type='text/plain')

        assert resp.status_code == 400

        with webhook_app.app_context():
            count_after = HubSpotWebhookLog.query.count()
            assert count_after == count_before  # no new records
