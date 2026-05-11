"""Pytest configuration and fixtures."""
import pytest
import os
from unittest.mock import patch, MagicMock
from app import create_app, db
from tests.e2e_setup import seed_test_data
from tests.mock_apis import MockAPIFactory
import celery_worker

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
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'

    app = create_app('testing')
    app.config['TESTING'] = True

    # Patch PropertyDataService.fetch_property_facts so tests never make
    # real HTTP calls to the Cook County Assessor API.
    # Also patch run_comparable_search_task.delay so tests never attempt to
    # connect to a Redis broker — the Celery task is a no-op in tests.
    with patch(
        'app.services.property_data_service.PropertyDataService.fetch_property_facts',
        return_value=_MOCK_PROPERTY_FACTS,
    ), patch.object(
        celery_worker.run_comparable_search_task,
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

@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

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
