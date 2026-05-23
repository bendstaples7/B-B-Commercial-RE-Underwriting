"""Unit tests for HubSpot client secret encryption/decryption flow.

Covers:
1. Saving a client secret stores it encrypted (not plaintext)
2. GET /api/hubspot/config returns has_client_secret: true but no secret value
3. encrypt_client_secret / decrypt_client_secret static methods round-trip correctly
"""
import os

import pytest

from app import create_app, db
from app.models.hubspot_config import HubSpotConfig
from app.services.hubspot_client_service import HubSpotClientService
from app.exceptions import ExternalServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fernet_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def _encrypt_token(raw: str, key: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).encrypt(raw.encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def fernet_key():
    return _make_fernet_key()


@pytest.fixture
def app_ctx(fernet_key):
    """Flask app with in-memory SQLite and HUBSPOT_ENCRYPTION_KEY set."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['HUBSPOT_ENCRYPTION_KEY'] = fernet_key

    application = create_app('testing')
    application.config['TESTING'] = True

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()

    for key in ('DATABASE_URL', 'FLASK_ENV', 'HUBSPOT_ENCRYPTION_KEY'):
        os.environ.pop(key, None)


@pytest.fixture
def client(app_ctx):
    return app_ctx.test_client()


@pytest.fixture
def config_with_secret(app_ctx, fernet_key):
    """Seed a HubSpotConfig row that has an encrypted client secret."""
    with app_ctx.app_context():
        dummy_token = _encrypt_token('dummy-api-token', fernet_key)
        encrypted_secret = HubSpotClientService.encrypt_client_secret('my-webhook-secret')
        config = HubSpotConfig(
            encrypted_token=dummy_token,
            encrypted_client_secret=encrypted_secret,
            portal_id='12345',
            account_name='Test Portal',
        )
        db.session.add(config)
        db.session.commit()
        yield config
        db.session.delete(config)
        db.session.commit()


@pytest.fixture
def config_without_secret(app_ctx, fernet_key):
    """Seed a HubSpotConfig row with NO client secret."""
    with app_ctx.app_context():
        dummy_token = _encrypt_token('dummy-api-token', fernet_key)
        config = HubSpotConfig(
            encrypted_token=dummy_token,
            encrypted_client_secret=None,
            portal_id='99999',
            account_name='No Secret Portal',
        )
        db.session.add(config)
        db.session.commit()
        yield config
        db.session.delete(config)
        db.session.commit()


# ---------------------------------------------------------------------------
# 1. encrypt_client_secret / decrypt_client_secret round-trip
# ---------------------------------------------------------------------------

class TestEncryptDecryptClientSecret:
    """Static methods on HubSpotClientService encrypt and decrypt correctly."""

    def test_encrypt_returns_non_plaintext(self, app_ctx):
        """Encrypted value must not equal the raw secret."""
        with app_ctx.app_context():
            raw = 'super-secret-value'
            encrypted = HubSpotClientService.encrypt_client_secret(raw)
            assert encrypted != raw

    def test_decrypt_recovers_original(self, app_ctx):
        """Decrypting an encrypted secret returns the original plaintext."""
        with app_ctx.app_context():
            raw = 'super-secret-value'
            encrypted = HubSpotClientService.encrypt_client_secret(raw)
            decrypted = HubSpotClientService.decrypt_client_secret(encrypted)
            assert decrypted == raw

    def test_encrypt_produces_different_ciphertext_each_time(self, app_ctx):
        """Fernet uses a random IV so two encryptions of the same value differ."""
        with app_ctx.app_context():
            raw = 'same-secret'
            enc1 = HubSpotClientService.encrypt_client_secret(raw)
            enc2 = HubSpotClientService.encrypt_client_secret(raw)
            # Both decrypt to the same value but the ciphertexts differ
            assert enc1 != enc2
            assert HubSpotClientService.decrypt_client_secret(enc1) == raw
            assert HubSpotClientService.decrypt_client_secret(enc2) == raw

    def test_encrypt_without_key_raises(self, app_ctx):
        """encrypt_client_secret raises ExternalServiceError when key is missing."""
        with app_ctx.app_context():
            saved = os.environ.pop('HUBSPOT_ENCRYPTION_KEY', None)
            try:
                with pytest.raises(ExternalServiceError):
                    HubSpotClientService.encrypt_client_secret('some-secret')
            finally:
                if saved:
                    os.environ['HUBSPOT_ENCRYPTION_KEY'] = saved

    def test_decrypt_without_key_raises(self, app_ctx):
        """decrypt_client_secret raises ExternalServiceError when key is missing."""
        with app_ctx.app_context():
            encrypted = HubSpotClientService.encrypt_client_secret('some-secret')
            saved = os.environ.pop('HUBSPOT_ENCRYPTION_KEY', None)
            try:
                with pytest.raises(ExternalServiceError):
                    HubSpotClientService.decrypt_client_secret(encrypted)
            finally:
                if saved:
                    os.environ['HUBSPOT_ENCRYPTION_KEY'] = saved

    def test_decrypt_invalid_token_raises(self, app_ctx):
        """decrypt_client_secret raises ExternalServiceError for garbage input."""
        with app_ctx.app_context():
            with pytest.raises(ExternalServiceError):
                HubSpotClientService.decrypt_client_secret('not-valid-fernet-data')


# ---------------------------------------------------------------------------
# 2. POST /api/hubspot/config stores secret encrypted, not plaintext
# ---------------------------------------------------------------------------

class TestSaveConfigEncryptsSecret:
    """POST /api/hubspot/config must store the client secret encrypted."""

    def test_save_config_stores_encrypted_secret(self, client, app_ctx, fernet_key):
        """After saving, the DB row must not contain the plaintext secret."""
        raw_secret = 'plaintext-webhook-secret'
        resp = client.post('/api/hubspot/config', json={
            'token': 'hapi-test-token',
            'portal_id': '55555',
            'client_secret': raw_secret,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_client_secret'] is True

        # Verify the DB row does NOT store the plaintext
        with app_ctx.app_context():
            config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            assert config is not None
            assert config.encrypted_client_secret is not None
            assert config.encrypted_client_secret != raw_secret

    def test_save_config_encrypted_secret_is_decryptable(self, client, app_ctx, fernet_key):
        """The stored encrypted secret must decrypt back to the original value."""
        raw_secret = 'decryptable-secret-xyz'
        client.post('/api/hubspot/config', json={
            'token': 'hapi-test-token-2',
            'portal_id': '66666',
            'client_secret': raw_secret,
        })

        with app_ctx.app_context():
            config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            decrypted = HubSpotClientService.decrypt_client_secret(
                config.encrypted_client_secret
            )
            assert decrypted == raw_secret

    def test_save_config_without_secret_leaves_has_client_secret_false(self, client):
        """Saving config without a client_secret yields has_client_secret: false."""
        resp = client.post('/api/hubspot/config', json={
            'token': 'hapi-no-secret-token',
            'portal_id': '77777',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_client_secret'] is False


# ---------------------------------------------------------------------------
# 3. GET /api/hubspot/config never returns the secret value
# ---------------------------------------------------------------------------

class TestGetConfigNeverReturnsSecret:
    """GET /api/hubspot/config must return has_client_secret but not the secret."""

    def test_get_config_has_client_secret_true_when_set(
        self, client, config_with_secret
    ):
        """has_client_secret is True when a secret is stored."""
        resp = client.get('/api/hubspot/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('has_client_secret') is True

    def test_get_config_does_not_return_secret_value(
        self, client, config_with_secret
    ):
        """The response must not contain the plaintext or encrypted secret."""
        resp = client.get('/api/hubspot/config')
        data = resp.get_json()
        # No key named 'client_secret' or 'encrypted_client_secret' in response
        assert 'client_secret' not in data
        assert 'encrypted_client_secret' not in data

    def test_get_config_has_client_secret_false_when_not_set(
        self, client, config_without_secret
    ):
        """has_client_secret is False when no secret is stored."""
        resp = client.get('/api/hubspot/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('has_client_secret') is False

    def test_get_config_no_config_returns_configured_false(self, client, app_ctx):
        """When no config exists at all, returns {configured: false}."""
        with app_ctx.app_context():
            # Clear all configs
            HubSpotConfig.query.delete()
            db.session.commit()

        resp = client.get('/api/hubspot/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('configured') is False
        assert 'client_secret' not in data
        assert 'encrypted_client_secret' not in data
