# Error Handling Infrastructure

This document describes the error handling and logging infrastructure for the Real Estate Analysis Platform.

## Overview

The error handling infrastructure provides:
- Custom exception classes for different error categories
- Consistent JSON error response formatting
- Automatic error logging with multiple log files
- API failover logic with automatic retry
- Rate limit handling with exponential backoff
- Comprehensive logging for API calls, errors, and user actions

## Custom Exception Classes

All custom exceptions inherit from `RealEstateAnalysisException` and are defined in `app/exceptions.py`:

### Base Exception
- `RealEstateAnalysisException`: Base class for all application-specific errors

### Data-Related Exceptions
- `DataRetrievalException`: Property data retrieval failures (503)
- `APIFailoverException`: All API sources failed (503)
- `MissingCriticalDataException`: Critical required data missing (422)

### Validation Exceptions
- `ValidationException`: Data validation failures (400)
- `InsufficientComparablesException`: Not enough comparable sales found (422)

### Workflow Exceptions
- `WorkflowException`: Workflow operation failures (400)
- `SessionNotFoundException`: Analysis session not found (404)

### API Exceptions
- `RateLimitException`: Rate limit exceeded (429)
- `ExportException`: Report export failures (500)

### Authentication/Authorization
- `AuthenticationException`: Authentication failures (401)
- `AuthorizationException`: Authorization failures (403)

## Usage Examples

### Raising Custom Exceptions

```python
from app.exceptions import ValidationException, SessionNotFoundException

# Validation error
if year_built < 1800:
    raise ValidationException(
        "Year built must be after 1800",
        field="year_built",
        value=year_built
    )

# Session not found
session = get_session(session_id)
if not session:
    raise SessionNotFoundException(session_id)
```

### API Failover

```python
from app.api_utils import APIFailoverHandler

handler = APIFailoverHandler()

# Define sources with fallback sequence
sources = [
    ('MLS', fetch_from_mls, address),
    ('TaxAssessor', fetch_from_tax_assessor, address),
    ('Chicago', fetch_from_chicago, address)
]

try:
    data = handler.try_sources(sources, field='square_footage')
except APIFailoverException as e:
    # All sources failed
    logger.error(f"Failed to retrieve data: {e.message}")
    # Prompt for manual entry
```

### Rate Limit Handling

```python
from app.api_utils import RateLimitHandler

handler = RateLimitHandler(max_retries=3, base_delay=1.0)

try:
    result = handler.handle_rate_limit(api_call_function, arg1, arg2)
except RateLimitException:
    # Max retries exceeded
    logger.error("Rate limit exceeded after retries")
```

### Using Decorators

```python
from app.api_utils import log_api_call, with_rate_limit_handling

@log_api_call(source='MLS')
@with_rate_limit_handling(max_retries=3, base_delay=1.0)
def fetch_property_data(address):
    # API call automatically logged and rate-limited
    return mls_api.get_property(address)
```

## Error Response Format

All errors return consistent JSON structure:

```json
{
  "success": false,
  "error": {
    "message": "Error description",
    "status_code": 400,
    "error_type": "validation_error",
    "field": "year_built",
    "invalid_value": "1500"
  }
}
```

## Logging

### Log Files

The system creates multiple log files in `backend/logs/`:

- `app.log`: General application logs (all levels)
- `errors.log`: Error-level logs only
- `api_calls.log`: External API call tracking
- `user_actions.log`: User actions and workflow events

### Log Levels

Set via `LOG_LEVEL` environment variable:
- `DEBUG`: Detailed debugging information
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

### Logging API Calls

```python
from app.logging_config import api_call_logger

# Log successful API call
api_call_logger.log_api_call(
    source='MLS',
    endpoint='get_property',
    status='success',
    response_time=0.5
)

# Log failed API call
api_call_logger.log_api_call(
    source='MLS',
    endpoint='get_property',
    status='failure',
    response_time=2.0,
    error='Connection timeout'
)

# Log failover event
api_call_logger.log_failover(
    primary_source='MLS',
    fallback_source='TaxAssessor',
    field='square_footage',
    success=True
)
```

### Logging User Actions

```python
from app.logging_config import user_action_logger

# Log user action
user_action_logger.log_action(
    user_id='user_123',
    action='start_analysis',
    session_id='session_456',
    details={'address': '123 Main St'}
)

# Log workflow event
user_action_logger.log_workflow_event(
    session_id='session_456',
    event='step_advance',
    from_step='step_1',
    to_step='step_2'
)
```

## Error Handler Registration

Error handlers are automatically registered in `app/__init__.py`:

```python
from app.error_handlers import register_error_handlers
from app.logging_config import setup_logging

def create_app():
    app = Flask(__name__)
    
    # Configure logging
    setup_logging(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    return app
```

## Testing

Run error handling tests:

```bash
# Unit tests
pytest backend/tests/test_error_handling.py -v

# Integration tests
pytest backend/tests/test_error_handlers_integration.py -v
```

## Best Practices

1. **Use specific exceptions**: Choose the most appropriate exception class for the error
2. **Include context**: Provide field names, values, and other relevant information
3. **Log before raising**: Log errors with context before raising exceptions
4. **Handle gracefully**: Catch exceptions at appropriate levels and provide user-friendly messages
5. **Monitor logs**: Regularly review error logs to identify patterns and issues
6. **Test error paths**: Write tests for error scenarios, not just happy paths

## Configuration

Environment variables for error handling:

- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `RATE_LIMIT_MAX_RETRIES`: Maximum retry attempts for rate limits (default: 3)
- `RATE_LIMIT_BASE_DELAY`: Base delay for exponential backoff in seconds (default: 1.0)

## Monitoring

Monitor these log files for issues:

1. `errors.log`: Check for recurring errors
2. `api_calls.log`: Monitor API failures and response times
3. `user_actions.log`: Track user behavior and workflow issues

Set up log rotation and archival for production environments.
