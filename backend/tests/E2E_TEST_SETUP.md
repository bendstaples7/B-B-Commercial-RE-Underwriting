# End-to-End Test Environment Setup

## Overview

This document describes the end-to-end (E2E) test environment configuration for the Real Estate Analysis Platform. The E2E test environment includes test database setup, mock external APIs, and frontend test configuration.

## Backend Test Environment

### Test Database Configuration

The test environment uses SQLite in-memory database for fast, isolated testing:

```python
# Configuration in conftest.py
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
```

### Database Seeding

Test data is automatically seeded using the `e2e_setup.py` module:

**Seeded Data Includes:**
- 1 subject property (4-unit multi-family in Chicago)
- 12 comparable sales with varying characteristics
- 1 analysis session with workflow state

**Usage:**
```python
@pytest.fixture
def seeded_app(app):
    """Create application with seeded test data."""
    with app.app_context():
        test_data = seed_test_data(app)
        yield app, test_data
```

### Mock External APIs

All external API integrations are mocked for testing:

**Available Mock APIs:**
1. **MockMLSAPI** - Property and sales data
2. **MockTaxAssessorAPI** - Property characteristics and tax info
3. **MockChicagoCityDataAPI** - Building data and square footage
4. **MockMunicipalDataAPI** - Zoning and permits
5. **MockGoogleMapsAPI** - Geocoding
6. **MockRentalDataAPI** - Market rent information

**Usage:**
```python
def test_with_mocks(mock_apis):
    # All APIs available and working
    mls = mock_apis['mls']
    data = mls.get_property_details("123 Main St")
    assert data['address'] == "123 Main St"

def test_with_failures(mock_apis_with_failures):
    # MLS API configured to fail, testing fallback logic
    mls = mock_apis_with_failures['mls']
    # Will raise exception, forcing fallback
```

### Test Fixtures

**Available Fixtures:**
- `app` - Flask application with test configuration
- `client` - Flask test client for API requests
- `seeded_app` - Application with pre-populated test data
- `mock_apis` - All mock external APIs (working)
- `mock_apis_with_failures` - Mock APIs with configured failures

### Running Backend Tests

```bash
# Run all tests
cd backend
pytest

# Run specific test file
pytest tests/test_api_routes.py

# Run with coverage
pytest --cov=app --cov-report=html

# Run E2E tests only (when created)
pytest tests/test_e2e.py -v
```

## Frontend Test Environment

### Test Configuration

Frontend tests use Vitest with React Testing Library:

**Configuration in `vite.config.ts`:**
```typescript
test: {
  globals: true,
  environment: 'jsdom',
  setupFiles: './src/test/setup.ts',
}
```

### Mock API Client

The `mockApi.ts` module provides a complete mock API client for frontend testing:

**Available Mock Data:**
- `mockPropertyFacts` - Sample property data
- `mockComparables` - 12 comparable sales
- `mockAnalysisSession` - Complete session state
- `mockValuationResult` - Valuation calculations
- `mockWholesaleScenario` - Wholesale analysis
- `mockFixFlipScenario` - Fix & flip analysis
- `mockBuyHoldScenario` - Buy & hold analysis

**Usage:**
```typescript
import { mockApiClient, mockPropertyFacts } from '@/test/mockApi'

// In tests
const session = await mockApiClient.startAnalysis("123 Main St")
expect(session.subject_property).toBeDefined()
```

### Test Utilities

The `testUtils.tsx` module provides custom render functions with providers:

**Usage:**
```typescript
import { render, screen } from '@/test/testUtils'

test('renders component', () => {
  render(<MyComponent />)
  expect(screen.getByText('Hello')).toBeInTheDocument()
})
```

**Available Utilities:**
- `render()` - Custom render with QueryClient and ThemeProvider
- `createTestQueryClient()` - Create isolated query client
- `waitForAsync()` - Wait for async operations
- `mockApiResponse()` - Create mock API responses
- `mockApiError()` - Create mock API errors

### Test Setup

The `setup.ts` file configures the test environment:

**Mocked Browser APIs:**
- `window.matchMedia` - For responsive design tests
- `IntersectionObserver` - For lazy loading tests
- `ResizeObserver` - For responsive component tests
- `window.scrollTo` - For scroll behavior tests

### Running Frontend Tests

```bash
# Run all tests
cd frontend
npm test

# Run in watch mode
npm run test:watch

# Run with UI
npm run test -- --ui

# Run specific test file
npm test -- PropertyFactsForm.test.tsx
```

## Integration Testing Strategy

### Test Levels

1. **Unit Tests** - Individual functions and components
2. **Integration Tests** - Multiple components/services working together
3. **E2E Tests** - Complete workflow from API to UI

### E2E Test Scenarios

**Recommended E2E test scenarios:**

1. **Happy Path Workflow**
   - Start analysis with address
   - Review property facts
   - Review comparables
   - View weighted scoring
   - View valuation models
   - Generate report

2. **Data Modification Workflow**
   - Start analysis
   - Modify property facts
   - Verify recalculation cascade
   - Navigate backward
   - Verify state preservation

3. **Error Handling Workflow**
   - Simulate API failures
   - Verify fallback logic
   - Test manual data entry
   - Verify error messages

4. **Scenario Analysis Workflow**
   - Complete valuation
   - Add wholesale scenario
   - Add fix & flip scenario
   - Add buy & hold scenario
   - Compare scenarios

5. **Export Workflow**
   - Generate complete report
   - Export to Excel
   - Export to Google Sheets

## Environment Variables

### Backend Test Environment

```bash
# .env.test (create if needed)
DATABASE_URL=sqlite:///:memory:
REDIS_URL=redis://localhost:6379/1
SECRET_KEY=test-secret-key
TESTING=true
```

### Frontend Test Environment

```bash
# .env.test (create if needed)
VITE_API_URL=http://localhost:5000/api
VITE_ENABLE_MOCKS=true
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      - name: Run tests
        run: |
          cd backend
          pytest --cov=app

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Node
        uses: actions/setup-node@v2
        with:
          node-version: '18'
      - name: Install dependencies
        run: |
          cd frontend
          npm ci
      - name: Run tests
        run: |
          cd frontend
          npm test
```

## Troubleshooting

### Common Issues

**Issue: Database connection errors**
- Solution: Ensure DATABASE_URL is set to SQLite in-memory for tests

**Issue: Mock API not working**
- Solution: Verify mock_apis fixture is used in test function

**Issue: Frontend tests timeout**
- Solution: Check that async operations use proper await/waitFor

**Issue: Test data conflicts**
- Solution: Each test should use isolated fixtures or cleanup properly

### Debug Mode

**Backend:**
```bash
pytest -v -s  # Verbose with print statements
pytest --pdb  # Drop into debugger on failure
```

**Frontend:**
```bash
npm test -- --reporter=verbose
npm test -- --no-coverage  # Faster without coverage
```

## Best Practices

1. **Isolation** - Each test should be independent
2. **Cleanup** - Always cleanup test data after tests
3. **Mocking** - Mock external dependencies consistently
4. **Assertions** - Use specific, meaningful assertions
5. **Coverage** - Aim for >80% code coverage
6. **Speed** - Keep tests fast (<5 seconds per test)
7. **Readability** - Write clear, self-documenting tests

## Next Steps

After setting up the E2E test environment:

1. Create E2E test files (test_e2e.py, e2e.test.tsx)
2. Implement test scenarios listed above
3. Run full test suite
4. Configure CI/CD pipeline
5. Monitor test coverage and add missing tests
