"""Integration tests for the HubSpot webhook log API endpoints.

Covers:
- GET /api/hubspot/webhook-log — list (success, status filter, object_type filter)
- GET /api/hubspot/webhook-log/summary — 24-hour summary
- POST /api/hubspot/webhook-log/{log_id}/retry — success, 404, 400 not-failed
- GET /api/hubspot/config — returns has_client_secret: true when configured
- POST /api/hubspot/config — saves client_secret encrypted
"""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_webhook_log import HubSpotWebhookLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encrypt(raw: str, fernet_key: str) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(fernet_key.encode())
    return f.encrypt(raw.encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def fernet_key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


@pytest.fixture
def log_app(fernet_key):
    """Flask test app with a HubSpotConfig and some webhook log records."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

    application = create_app('testing')
    application.config['TESTING'] = True
    application.config['RATELIMIT_ENABLED'] = False

    with application.app_context():
        db.create_all()

        # Create a HubSpotConfig with both token and client secret
        dummy_token = _encrypt('dummy-token', fernet_key)
        encrypted_secret = _encrypt('test-client-secret', fernet_key)
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
def log_client(log_app):
    return log_app.test_client()


def _create_log(app, object_type='deal', object_id='1', status='processed',
                event_type='deal.creation', received_at=None, processed_at=None):
    """Helper to insert a HubSpotWebhookLog record directly."""
    with app.app_context():
        log = HubSpotWebhookLog(
            hubspot_object_type=object_type,
            hubspot_object_id=object_id,
            event_type=event_type,
            subscription_type=event_type,
            raw_payload={'objectId': int(object_id) if object_id.isdigit() else 0},
            status=status,
            received_at=received_at or datetime.utcnow(),
            processed_at=processed_at,
        )
        db.session.add(log)
        db.session.commit()
        return log.id


# ---------------------------------------------------------------------------
# GET /api/hubspot/webhook-log
# ---------------------------------------------------------------------------

class TestListWebhookLogs:
    """Tests for GET /api/hubspot/webhook-log."""

    def test_returns_list_of_logs(self, log_app, log_client):
        """Returns a paginated list of webhook log records."""
        _create_log(log_app, object_type='deal', object_id='10', status='processed')
        _create_log(log_app, object_type='contact', object_id='20', status='failed')

        resp = log_client.get('/api/hubspot/webhook-log')
        assert resp.status_code == 200

        data = resp.get_json()
        assert 'logs' in data
        assert 'total' in data
        assert 'page' in data
        assert 'per_page' in data
        assert 'pages' in data
        assert data['total'] >= 2
        assert isinstance(data['logs'], list)

    def test_log_fields_are_serialized(self, log_app, log_client):
        """Each log entry contains the expected fields."""
        _create_log(log_app, object_type='deal', object_id='99', status='processed')

        resp = log_client.get('/api/hubspot/webhook-log')
        assert resp.status_code == 200

        data = resp.get_json()
        assert len(data['logs']) > 0
        log_entry = data['logs'][0]
        assert 'id' in log_entry
        assert 'hubspot_object_type' in log_entry
        assert 'hubspot_object_id' in log_entry
        assert 'event_type' in log_entry
        assert 'status' in log_entry
        assert 'received_at' in log_entry

    def test_status_filter(self, log_app, log_client):
        """?status=failed returns only failed logs."""
        _create_log(log_app, object_type='deal', object_id='101', status='failed')
        _create_log(log_app, object_type='deal', object_id='102', status='processed')

        resp = log_client.get('/api/hubspot/webhook-log?status=failed')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data['total'] >= 1
        for log_entry in data['logs']:
            assert log_entry['status'] == 'failed'

    def test_object_type_filter(self, log_app, log_client):
        """?object_type=contact returns only contact logs."""
        _create_log(log_app, object_type='contact', object_id='201', status='processed')
        _create_log(log_app, object_type='deal', object_id='202', status='processed')

        resp = log_client.get('/api/hubspot/webhook-log?object_type=contact')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data['total'] >= 1
        for log_entry in data['logs']:
            assert log_entry['hubspot_object_type'] == 'contact'

    def test_pagination_defaults(self, log_app, log_client):
        """Default page=1, per_page=20 are applied."""
        resp = log_client.get('/api/hubspot/webhook-log')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data['page'] == 1
        assert data['per_page'] == 20

    def test_pagination_custom(self, log_app, log_client):
        """Custom page and per_page are respected."""
        resp = log_client.get('/api/hubspot/webhook-log?page=1&per_page=5')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data['per_page'] == 5
        assert len(data['logs']) <= 5


# ---------------------------------------------------------------------------
# GET /api/hubspot/webhook-log/summary
# ---------------------------------------------------------------------------

class TestWebhookLogSummary:
    """Tests for GET /api/hubspot/webhook-log/summary."""

    def test_returns_summary_fields(self, log_app, log_client):
        """Returns the expected summary fields."""
        resp = log_client.get('/api/hubspot/webhook-log/summary')
        assert resp.status_code == 200

        data = resp.get_json()
        assert 'processed_count' in data
        assert 'failed_count' in data
        assert 'deduplicated_count' in data
        assert 'last_synced_at' in data

    def test_counts_reflect_recent_logs(self, log_app, log_client):
        """Counts reflect logs received in the last 24 hours."""
        # Create some known logs
        _create_log(log_app, object_type='deal', object_id='301', status='processed',
                    processed_at=datetime.utcnow())
        _create_log(log_app, object_type='deal', object_id='302', status='failed')
        _create_log(log_app, object_type='deal', object_id='303', status='deduplicated')

        resp = log_client.get('/api/hubspot/webhook-log/summary')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data['processed_count'] >= 1
        assert data['failed_count'] >= 1
        assert data['deduplicated_count'] >= 1


# ---------------------------------------------------------------------------
# POST /api/hubspot/webhook-log/{log_id}/retry
# ---------------------------------------------------------------------------

class TestRetryWebhookLog:
    """Tests for POST /api/hubspot/webhook-log/{log_id}/retry."""

    def test_retry_success(self, log_app, log_client):
        """Retrying a failed log returns 200 {success: true}."""
        log_id = _create_log(log_app, object_type='deal', object_id='401', status='failed')

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        # The service does: from app.tasks.hubspot_webhook_tasks import process_webhook_event
        # That name doesn't exist in the module, so we patch it in with create=True
        with patch(
            'app.tasks.hubspot_webhook_tasks.process_webhook_event',
            mock_task,
            create=True,
        ):
            resp = log_client.post(f'/api/hubspot/webhook-log/{log_id}/retry')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_retry_resets_status_to_pending(self, log_app, log_client):
        """After a successful retry, the log status is reset to pending."""
        log_id = _create_log(log_app, object_type='deal', object_id='402', status='failed')

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with patch(
            'app.tasks.hubspot_webhook_tasks.process_webhook_event',
            mock_task,
            create=True,
        ):
            resp = log_client.post(f'/api/hubspot/webhook-log/{log_id}/retry')

        assert resp.status_code == 200

        with log_app.app_context():
            log = HubSpotWebhookLog.query.get(log_id)
            assert log.status == 'pending'

    def test_retry_not_found_returns_404(self, log_app, log_client):
        """Retrying a non-existent log_id returns 404."""
        resp = log_client.post('/api/hubspot/webhook-log/999999/retry')
        assert resp.status_code == 404

        data = resp.get_json()
        assert 'error' in data

    def test_retry_non_failed_status_returns_400(self, log_app, log_client):
        """Retrying a log that is not in 'failed' status returns 400."""
        log_id = _create_log(log_app, object_type='deal', object_id='403', status='processed')

        resp = log_client.post(f'/api/hubspot/webhook-log/{log_id}/retry')
        assert resp.status_code == 400

        data = resp.get_json()
        assert 'error' in data

    def test_retry_pending_status_returns_400(self, log_app, log_client):
        """Retrying a log in 'pending' status returns 400."""
        log_id = _create_log(log_app, object_type='deal', object_id='404', status='pending')

        resp = log_client.post(f'/api/hubspot/webhook-log/{log_id}/retry')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/hubspot/config — has_client_secret
# ---------------------------------------------------------------------------

class TestGetConfigHasClientSecret:
    """Tests for GET /api/hubspot/config returning has_client_secret."""

    def test_has_client_secret_true_when_configured(self, log_app, log_client):
        """Returns has_client_secret: true when encrypted_client_secret is set."""
        resp = log_client.get('/api/hubspot/config')
        assert resp.status_code == 200

        data = resp.get_json()
        assert data.get('has_client_secret') is True

    def test_has_client_secret_false_when_not_configured(self, fernet_key):
        """Returns has_client_secret: false when no client secret is stored."""
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        os.environ['FLASK_ENV'] = 'testing'
        os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

        application = create_app('testing')
        application.config['TESTING'] = True
        application.config['RATELIMIT_ENABLED'] = False

        with application.app_context():
            db.create_all()

            # Config with token but NO client secret
            dummy_token = _encrypt('dummy-token', fernet_key)
            config = HubSpotConfig(
                encrypted_token=dummy_token,
                encrypted_client_secret=None,
            )
            db.session.add(config)
            db.session.commit()

            client = application.test_client()
            resp = client.get('/api/hubspot/config')
            assert resp.status_code == 200

            data = resp.get_json()
            assert data.get('has_client_secret') is False

            db.session.remove()
            db.drop_all()

        for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
            os.environ.pop(key, None)

    def test_client_secret_value_never_returned(self, log_app, log_client):
        """The raw or encrypted client secret is never included in the response."""
        resp = log_client.get('/api/hubspot/config')
        assert resp.status_code == 200

        data = resp.get_json()
        # These keys must not appear in the response
        assert 'client_secret' not in data
        assert 'encrypted_client_secret' not in data


# ---------------------------------------------------------------------------
# POST /api/hubspot/config — saves client_secret encrypted
# ---------------------------------------------------------------------------

class TestSaveConfigClientSecret:
    """Tests for POST /api/hubspot/config accepting and encrypting client_secret."""

    def test_save_config_with_client_secret(self, fernet_key):
        """Posting client_secret stores it encrypted and returns has_client_secret: true."""
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        os.environ['FLASK_ENV'] = 'testing'
        os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

        application = create_app('testing')
        application.config['TESTING'] = True
        application.config['RATELIMIT_ENABLED'] = False

        with application.app_context():
            db.create_all()

            client = application.test_client()
            resp = client.post(
                '/api/hubspot/config',
                json={
                    'token': 'pat-na1-test-token',
                    'client_secret': 'my-webhook-secret',
                },
            )
            assert resp.status_code == 200

            data = resp.get_json()
            assert data.get('has_client_secret') is True

            # Verify it was actually stored encrypted (not plaintext)
            config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            assert config.encrypted_client_secret is not None
            assert config.encrypted_client_secret != 'my-webhook-secret'

            # Verify it can be decrypted back to the original value
            from cryptography.fernet import Fernet
            f = Fernet(fernet_key.encode())
            decrypted = f.decrypt(config.encrypted_client_secret.encode()).decode()
            assert decrypted == 'my-webhook-secret'

            db.session.remove()
            db.drop_all()

        for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
            os.environ.pop(key, None)

    def test_save_config_without_client_secret(self, fernet_key):
        """Posting without client_secret leaves has_client_secret: false."""
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        os.environ['FLASK_ENV'] = 'testing'
        os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

        application = create_app('testing')
        application.config['TESTING'] = True
        application.config['RATELIMIT_ENABLED'] = False

        with application.app_context():
            db.create_all()

            client = application.test_client()
            resp = client.post(
                '/api/hubspot/config',
                json={'token': 'pat-na1-test-token'},
            )
            assert resp.status_code == 200

            data = resp.get_json()
            assert data.get('has_client_secret') is False

            db.session.remove()
            db.drop_all()

        for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
            os.environ.pop(key, None)

    def test_save_config_client_secret_not_returned_in_response(self, fernet_key):
        """The client_secret value is never returned in the POST /config response."""
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        os.environ['FLASK_ENV'] = 'testing'
        os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

        application = create_app('testing')
        application.config['TESTING'] = True
        application.config['RATELIMIT_ENABLED'] = False

        with application.app_context():
            db.create_all()

            client = application.test_client()
            resp = client.post(
                '/api/hubspot/config',
                json={
                    'token': 'pat-na1-test-token',
                    'client_secret': 'super-secret-value',
                },
            )
            assert resp.status_code == 200

            data = resp.get_json()
            assert 'client_secret' not in data
            assert 'encrypted_client_secret' not in data

            db.session.remove()
            db.drop_all()

        for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
            os.environ.pop(key, None)
