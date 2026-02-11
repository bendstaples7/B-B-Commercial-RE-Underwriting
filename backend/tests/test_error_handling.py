"""Unit tests for error handling infrastructure."""
import pytest
from app.exceptions import (
    RealEstateAnalysisException,
    DataRetrievalException,
    APIFailoverException,
    ValidationException,
    WorkflowException,
    SessionNotFoundException,
    InsufficientComparablesException,
    RateLimitException,
    ExportException,
    MissingCriticalDataException,
    AuthenticationException,
    AuthorizationException
)
from app.error_handlers import format_error_response
from app.api_utils import APIFailoverHandler, RateLimitHandler


class TestCustomExceptions:
    """Test custom exception classes."""
    
    def test_base_exception(self):
        """Test base RealEstateAnalysisException."""
        error = RealEstateAnalysisException("Test error", status_code=500)
        assert error.message == "Test error"
        assert error.status_code == 500
        assert error.payload == {}
    
    def test_data_retrieval_exception(self):
        """Test DataRetrievalException with source and field."""
        error = DataRetrievalException("Failed to fetch", source="MLS", field="square_footage")
        assert error.message == "Failed to fetch"
        assert error.status_code == 503
        assert error.payload['error_type'] == 'data_retrieval_error'
        assert error.payload['source'] == 'MLS'
        assert error.payload['field'] == 'square_footage'
    
    def test_api_failover_exception(self):
        """Test APIFailoverException with attempted sources."""
        sources = ['MLS', 'TaxAssessor', 'Chicago']
        error = APIFailoverException("All sources failed", attempted_sources=sources)
        assert error.status_code == 503
        assert error.payload['attempted_sources'] == sources
    
    def test_validation_exception(self):
        """Test ValidationException with field and value."""
        error = ValidationException("Invalid year", field="year_built", value=1500)
        assert error.status_code == 400
        assert error.payload['field'] == 'year_built'
        assert error.payload['invalid_value'] == '1500'
    
    def test_workflow_exception(self):
        """Test WorkflowException with step information."""
        error = WorkflowException(
            "Cannot advance",
            current_step="step_1",
            required_step="step_2"
        )
        assert error.status_code == 400
        assert error.payload['current_step'] == 'step_1'
        assert error.payload['required_step'] == 'step_2'
    
    def test_session_not_found_exception(self):
        """Test SessionNotFoundException."""
        error = SessionNotFoundException("session_123")
        assert error.status_code == 404
        assert "session_123" in error.message
        assert error.payload['session_id'] == 'session_123'
    
    def test_insufficient_comparables_exception(self):
        """Test InsufficientComparablesException."""
        error = InsufficientComparablesException(found_count=5, required_count=10)
        assert error.status_code == 422
        assert error.payload['found_count'] == 5
        assert error.payload['required_count'] == 10
    
    def test_rate_limit_exception(self):
        """Test RateLimitException."""
        error = RateLimitException(retry_after=60)
        assert error.status_code == 429
        assert error.payload['retry_after'] == 60
    
    def test_export_exception(self):
        """Test ExportException."""
        error = ExportException("Export failed", export_format="excel")
        assert error.status_code == 500
        assert error.payload['export_format'] == 'excel'
    
    def test_missing_critical_data_exception(self):
        """Test MissingCriticalDataException."""
        missing = ['square_footage', 'bedrooms']
        error = MissingCriticalDataException(missing_fields=missing)
        assert error.status_code == 422
        assert error.payload['missing_fields'] == missing
    
    def test_authentication_exception(self):
        """Test AuthenticationException."""
        error = AuthenticationException()
        assert error.status_code == 401
        assert error.payload['error_type'] == 'authentication_error'
    
    def test_authorization_exception(self):
        """Test AuthorizationException."""
        error = AuthorizationException()
        assert error.status_code == 403
        assert error.payload['error_type'] == 'authorization_error'


class TestErrorResponseFormatter:
    """Test error response formatting."""
    
    def test_format_error_response_basic(self):
        """Test basic error response formatting."""
        response, status_code = format_error_response("Test error", 400)
        
        assert status_code == 400
        assert response['success'] is False
        assert response['error']['message'] == "Test error"
        assert response['error']['status_code'] == 400
    
    def test_format_error_response_with_kwargs(self):
        """Test error response with additional fields."""
        response, status_code = format_error_response(
            "Test error",
            400,
            field="test_field",
            details="Additional info"
        )
        
        assert response['error']['field'] == "test_field"
        assert response['error']['details'] == "Additional info"


class TestAPIFailoverHandler:
    """Test API failover handler."""
    
    def test_try_sources_first_succeeds(self):
        """Test failover when first source succeeds."""
        def source1():
            return "data_from_source1"
        
        def source2():
            return "data_from_source2"
        
        handler = APIFailoverHandler()
        sources = [
            ('Source1', source1),
            ('Source2', source2)
        ]
        
        result = handler.try_sources(sources, field='test_field')
        assert result == "data_from_source1"
        assert handler.attempted_sources == ['Source1']
    
    def test_try_sources_failover_to_second(self):
        """Test failover when first source fails."""
        def source1():
            raise Exception("Source1 failed")
        
        def source2():
            return "data_from_source2"
        
        handler = APIFailoverHandler()
        sources = [
            ('Source1', source1),
            ('Source2', source2)
        ]
        
        result = handler.try_sources(sources, field='test_field')
        assert result == "data_from_source2"
        assert handler.attempted_sources == ['Source1', 'Source2']
    
    def test_try_sources_all_fail(self):
        """Test failover when all sources fail."""
        def source1():
            raise Exception("Source1 failed")
        
        def source2():
            raise Exception("Source2 failed")
        
        handler = APIFailoverHandler()
        sources = [
            ('Source1', source1),
            ('Source2', source2)
        ]
        
        with pytest.raises(APIFailoverException) as exc_info:
            handler.try_sources(sources, field='test_field')
        
        assert exc_info.value.payload['attempted_sources'] == ['Source1', 'Source2']
    
    def test_try_sources_with_args(self):
        """Test failover with function arguments."""
        def source1(arg1, arg2):
            return f"{arg1}_{arg2}"
        
        handler = APIFailoverHandler()
        sources = [
            ('Source1', source1, 'value1', 'value2')
        ]
        
        result = handler.try_sources(sources)
        assert result == "value1_value2"


class TestRateLimitHandler:
    """Test rate limit handler."""
    
    def test_handle_rate_limit_success(self):
        """Test rate limit handler with successful call."""
        def api_call():
            return "success"
        
        handler = RateLimitHandler(max_retries=3, base_delay=0.1)
        result = handler.handle_rate_limit(api_call)
        assert result == "success"
    
    def test_handle_rate_limit_retry_success(self):
        """Test rate limit handler with retry success."""
        call_count = [0]
        
        def api_call():
            call_count[0] += 1
            if call_count[0] < 2:
                raise RateLimitException(retry_after=0.1)
            return "success"
        
        handler = RateLimitHandler(max_retries=3, base_delay=0.1)
        result = handler.handle_rate_limit(api_call)
        assert result == "success"
        assert call_count[0] == 2
    
    def test_handle_rate_limit_max_retries_exceeded(self):
        """Test rate limit handler when max retries exceeded."""
        def api_call():
            raise RateLimitException(retry_after=0.1)
        
        handler = RateLimitHandler(max_retries=2, base_delay=0.1)
        
        with pytest.raises(RateLimitException):
            handler.handle_rate_limit(api_call)
    
    def test_handle_rate_limit_non_rate_limit_exception(self):
        """Test rate limit handler with non-rate-limit exception."""
        def api_call():
            raise ValueError("Different error")
        
        handler = RateLimitHandler(max_retries=3, base_delay=0.1)
        
        with pytest.raises(ValueError):
            handler.handle_rate_limit(api_call)
