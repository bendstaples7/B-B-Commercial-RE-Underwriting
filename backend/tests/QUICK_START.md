# E2E Test Environment - Quick Start Guide

## Overview

The end-to-end test environment is now fully configured and ready to use. This guide provides quick commands to get started.

## Backend Testing

### Run All E2E Sample Tests
```bash
cd backend
pytest tests/test_e2e_sample.py -v
```

### Run Specific Test
```bash
pytest tests/test_e2e_sample.py::test_database_seeding -v
pytest tests/test_e2e_sample.py::test_mock_mls_api -v
```

### Run All Tests
```bash
pytest -v
```

### Run with Coverage
```bash
pytest --cov=app --cov-report=html
```

## Frontend Testing

### Run All Tests
```bash
cd frontend
npm test
```

### Run Specific Test File
```bash
npm test -- e2e.sample.test.tsx
```

### Run in Watch Mode
```bash
npm run test:watch
```

## Available Test Fixtures

### Backend Fixtures

1. **app** - Flask application with test configuration
   ```python
   def test_example(app):
       with app.app_context():
           # Your test code
   ```

2. **client** - Flask test client for API requests
   ```python
   def test_api(client):
       response = client.get('/api/endpoint')
       assert response.status_code == 200
   ```

3. **seeded_app** - Application with pre-populated test data
   ```python
   def test_with_data(seeded_app):
       app, test_data = seeded_app
       with app.app_context():
           # Access seeded data
   ```

4. **mock_apis** - All mock external APIs (working)
   ```python
   def test_apis(mock_apis):
       mls = mock_apis['mls']
       data = mls.get_property_details("123 Main St")
   ```

5. **mock_apis_with_failures** - Mock APIs with configured failures
   ```python
   def test_fallback(mock_apis_with_failures):
       # MLS will fail, testing fallback logic
   ```

## Available Mock APIs

- **MockMLSAPI** - Property and sales data
- **MockTaxAssessorAPI** - Property characteristics
- **MockChicagoCityDataAPI** - Building data
- **MockMunicipalDataAPI** - Zoning and permits
- **MockGoogleMapsAPI** - Geocoding
- **MockRentalDataAPI** - Market rent information

## Frontend Test Utilities

### Custom Render with Providers
```typescript
import { render, screen } from '@/test/testUtils'

test('renders component', () => {
  render(<MyComponent />)
  expect(screen.getByText('Hello')).toBeInTheDocument()
})
```

### Mock API Client
```typescript
import { mockApiClient } from '@/test/mockApi'

test('fetches data', async () => {
  const session = await mockApiClient.startAnalysis('123 Main St')
  expect(session.subject_property).toBeDefined()
})
```

## Test Data

### Seeded Database Contains:
- 1 subject property (4-unit multi-family in Chicago)
- 12 comparable sales
- 1 analysis session (session_id: "test-session-001")

### Mock Data Available:
- mockPropertyFacts
- mockComparables (12 items)
- mockAnalysisSession
- mockValuationResult
- mockWholesaleScenario
- mockFixFlipScenario
- mockBuyHoldScenario

## Common Test Patterns

### Testing API Endpoints
```python
def test_endpoint(client):
    response = client.post('/api/analysis/start', json={
        'address': '123 Main St',
        'user_id': 'test-user'
    })
    assert response.status_code == 201
    data = response.get_json()
    assert 'session_id' in data
```

### Testing with Seeded Data
```python
def test_with_data(seeded_app):
    app, test_data = seeded_app
    with app.app_context():
        from app.models import PropertyFacts
        property = PropertyFacts.query.first()
        assert property.address == "123 Main St, Chicago, IL 60601"
```

### Testing Mock APIs
```python
def test_mock_api(mock_apis):
    mls = mock_apis['mls']
    comparables = mls.search_comparable_sales(
        latitude=41.8781,
        longitude=-87.6298,
        radius_miles=0.5,
        property_type='multi_family'
    )
    assert len(comparables) > 0
```

### Testing API Failures
```python
def test_fallback(mock_apis_with_failures):
    mls = mock_apis_with_failures['mls']
    with pytest.raises(Exception):
        mls.get_property_details("123 Test St")
```

## Next Steps

1. Review `E2E_TEST_SETUP.md` for detailed documentation
2. Create additional E2E test files as needed
3. Run tests regularly during development
4. Add new test scenarios for new features

## Troubleshooting

### Backend Tests Fail
- Ensure you're in the backend directory
- Check that all dependencies are installed: `pip install -r requirements.txt`
- Verify DATABASE_URL is set to SQLite in-memory for tests

### Frontend Tests Fail
- Ensure you're in the frontend directory
- Check that all dependencies are installed: `npm install`
- Verify vitest is installed: `npm list vitest`

### Mock APIs Not Working
- Import MockAPIFactory from tests.mock_apis
- Use the provided fixtures (mock_apis, mock_apis_with_failures)
- Reset mocks between tests using MockAPIFactory.reset_all_mocks()

## Test Results

All 8 backend E2E sample tests are passing:
✓ test_database_seeding
✓ test_mock_mls_api
✓ test_mock_api_failure_scenario
✓ test_api_start_analysis_endpoint
✓ test_mock_google_maps_api
✓ test_mock_rental_data_api
✓ test_mock_api_factory_reset
✓ test_mock_api_factory_configure_failures
