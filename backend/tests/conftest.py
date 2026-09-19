"""Pytest configuration and fixtures."""
import pytest
import os

# Set test env vars before any app/celery imports (celery_worker requires them).
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('FLASK_ENV', 'testing')

from unittest.mock import patch, MagicMock
from hypothesis import settings, HealthCheck
from app import create_app, db
from tests.e2e_setup import seed_test_data
from tests.mock_apis import MockAPIFactory

# Force after app/dotenv import — local .env may set these false for prod-like
# local runs. Kill-switch tests monkeypatch them off per case.
os.environ['HUBSPOT_PULL_ENABLED'] = 'true'
os.environ['HUBSPOT_WRITE_BACK_ENABLED'] = 'true'

# ---------------------------------------------------------------------------
# Hypothesis global settings — suppress deadline for all tests.
# The default 200ms deadline causes flaky failures on slow CI runners where
# DB-touching tests regularly take 300-500ms. The deadline catches performance
# regressions, not correctness bugs, so suppressing it globally is the right
# tradeoff for this test suite.
# ---------------------------------------------------------------------------
settings.register_profile("default", deadline=None)
settings.load_profile("default")

# Mock property facts returned by PropertyDataService during tests.
# Uses uppercase enum values to match the updated Python enum definitions.
_MOCK_PROPERTY_FACTS = {
    'address': '123 Main St, Chicago, IL 60601',
    'property_type': 'MULTI_FAMILY',
    'units': 4,
    'bedrooms': 8,
    'bathrooms': 4.0,
    'square_footage': 3200,
    'lot_size': 5000,
    'year_built': 1920,
    'construction_type': 'BRICK',
    'basement': True,
    'parking_spaces': 2,
    'assessed_value': 360000.0,
    'annual_taxes': None,
    'zoning': None,
    'latitude': 41.8781,
    'longitude': -87.6298,
    'data_source': 'cook_county_assessor',
    'user_modified_fields': [],
    'pin': '14083010190000',
}


@pytest.fixture
def app():
    """Create application for testing."""
    # Set environment variables before creating app.
    # FLASK_ENV must be 'testing' so create_app skips the auto-migrate block
    # (which only runs when effective_env == 'development').  Without this,
    # celery_worker.py's load_dotenv() sets FLASK_ENV=development from .env,
    # causing Alembic to run against the empty in-memory SQLite DB and fail.
    # The parallel suite stays on SQLite. xdist workers cannot share one
    # Postgres database, and create_all() does not build the partial unique
    # indexes that production enforces. Those indexes are checked by the
    # always-on "Backend — Postgres merge gate" job (tests/test_merge_postgres_gate.py).
    # Do not point this fixture at Postgres and call that a substitute.
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'
    # celery_worker import (below) reloads backend/.env with override=True and
    # would reset HubSpot kill-switches to local/prod defaults (false).
    os.environ['HUBSPOT_PULL_ENABLED'] = 'true'
    os.environ['HUBSPOT_WRITE_BACK_ENABLED'] = 'true'

    app = create_app('testing')
    app.config['TESTING'] = True

    # Patch PropertyDataService.fetch_property_facts so tests never make
    # real HTTP calls to the Cook County Assessor API.
    # Also patch run_comparable_search_task.delay so tests never attempt to
    # connect to a Redis broker — the Celery task is a no-op in tests.
    import celery_worker as _celery_worker
    # Re-assert after celery_worker.load_project_env() override.
    os.environ['HUBSPOT_PULL_ENABLED'] = 'true'
    os.environ['HUBSPOT_WRITE_BACK_ENABLED'] = 'true'
    with patch(
        'app.services.property_data_service.PropertyDataService.fetch_property_facts',
        return_value=_MOCK_PROPERTY_FACTS,
    ), patch.object(
        _celery_worker.run_comparable_search_task,
        'delay',
        return_value=MagicMock(),
    ), patch.object(
        _celery_worker.run_quick_add_followup,
        'delay',
        return_value=MagicMock(),
    ):
        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()

    # Clean up environment variables
    if 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']
    if 'FLASK_ENV' in os.environ:
        del os.environ['FLASK_ENV']

# Pass this on a request (or use ``anon_client``) when the test must stay anonymous.
ANON_HEADERS = {'X-User-Id': ''}


def seed_user(user_id: str = 'test-user', *, is_admin: bool = False, email: str | None = None):
    """Insert or update a ``User`` row so ``X-User-Id`` admin checks resolve."""
    from app.models.user import User

    email = email or f'{user_id}@example.com'
    existing = User.query.filter_by(user_id=user_id).first()
    if existing is not None:
        existing.is_admin = is_admin
        existing.is_active = True
        db.session.commit()
        return existing
    user = User(
        user_id=user_id,
        email=email,
        email_lower=email.lower(),
        password_hash='x',
        display_name=user_id,
        is_active=True,
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client(app):
    """Create test client with a default test-user identity.

    Product /api routes are fail-closed without a user. Tests that prove the
    401 gate should use ``anon_client`` or ``ANON_HEADERS``.
    """
    return wrap_test_client_with_user(app.test_client())


@pytest.fixture
def anon_client(app):
    """Unwrapped test client — no injected identity."""
    return app.test_client()


def wrap_test_client_with_user(client, user_id: str = 'test-user'):
    """Attach a default X-User-Id unless the caller already set identity headers.

    Tests that need an anonymous request should pass ``ANON_HEADERS``
    (``X-User-Id: ''``) or an Authorization header so this wrapper does not
    inject a user.
    """
    original_open = client.open

    def open_with_identity(*args, **kwargs):
        headers = dict(kwargs.get('headers') or {})
        if 'Authorization' not in headers and 'X-User-Id' not in headers:
            headers['X-User-Id'] = user_id
            kwargs['headers'] = headers
        return original_open(*args, **kwargs)

    client.open = open_with_identity
    return client

@pytest.fixture
def seeded_app(app):
    """Create application with seeded test data."""
    # app fixture already has an active app context
    test_data = seed_test_data(app)
    yield app, test_data

@pytest.fixture
def mock_apis():
    """Create mock external API instances."""
    mocks = MockAPIFactory.create_all_mocks()
    yield mocks
    MockAPIFactory.reset_all_mocks(mocks)

@pytest.fixture
def mock_apis_with_failures(mock_apis):
    """Create mock APIs with configured failures for testing fallback logic."""
    # Configure MLS to fail, forcing fallback to other sources
    MockAPIFactory.configure_failure_scenario(mock_apis, ['mls'])
    yield mock_apis
    MockAPIFactory.reset_all_mocks(mock_apis)

@pytest.fixture
def db_session(app):
    """Provide a SQLAlchemy session for direct ORM access in tests.

    Bound to the in-memory SQLite test database created by the ``app``
    fixture.  All four cache models (ParcelUniverseCache, ParcelSalesCache,
    ImprovementCharacteristicsCache, SyncLog) are available because
    ``db.create_all()`` is called inside the ``app`` fixture and all models
    are registered via ``app/models/__init__.py``.

    The session is rolled back after each test to ensure full isolation —
    no data written in one test leaks into another.
    """
    with app.app_context():
        yield db.session
        db.session.rollback()
