"""Pytest configuration and fixtures."""
import pytest
import os
from unittest.mock import patch
from app import create_app, db
from tests.e2e_setup import seed_test_data
from tests.mock_apis import MockAPIFactory

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
    # Set environment variable before creating app
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

    app = create_app('testing')
    app.config['TESTING'] = True

    # Patch PropertyDataService.fetch_property_facts so tests never make
    # real HTTP calls to the Cook County Assessor API.
    with patch(
        'app.services.property_data_service.PropertyDataService.fetch_property_facts',
        return_value=_MOCK_PROPERTY_FACTS,
    ):
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
