"""Pytest configuration and fixtures."""
import pytest
import os
from app import create_app, db
from tests.e2e_setup import seed_test_data
from tests.mock_apis import MockAPIFactory

@pytest.fixture
def app():
    """Create application for testing."""
    # Set environment variable before creating app
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    
    app = create_app('testing')
    app.config['TESTING'] = True
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    
    # Clean up environment variable
    if 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']

@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

@pytest.fixture
def seeded_app(app):
    """Create application with seeded test data."""
    with app.app_context():
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
