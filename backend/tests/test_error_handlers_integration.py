"""Integration tests for Flask error handlers."""
import pytest
from app import create_app
from app.exceptions import (
    ValidationException,
    SessionNotFoundException,
    RateLimitException
)


@pytest.fixture
def app():
    """Create Flask app for testing."""
    app = create_app('testing')
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestErrorHandlersIntegration:
    """Test error handlers integration with Flask."""
    
    def test_custom_exception_handler(self, app, client):
        """Test custom exception is handled correctly."""
        @app.route('/test-validation-error')
        def test_validation_error():
            raise ValidationException("Invalid input", field="test_field", value=123)
        
        response = client.get('/test-validation-error')
        
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['message'] == "Invalid input"
        assert data['error']['error_type'] == 'validation_error'
        assert data['error']['field'] == 'test_field'
    
    def test_session_not_found_handler(self, app, client):
        """Test session not found exception handler."""
        @app.route('/test-session-not-found')
        def test_session_not_found():
            raise SessionNotFoundException("session_123")
        
        response = client.get('/test-session-not-found')
        
        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'session_123' in data['error']['message']
        assert data['error']['session_id'] == 'session_123'
    
    def test_rate_limit_handler(self, app, client):
        """Test rate limit exception handler."""
        @app.route('/test-rate-limit')
        def test_rate_limit():
            raise RateLimitException(retry_after=60)
        
        response = client.get('/test-rate-limit')
        
        assert response.status_code == 429
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['error_type'] == 'rate_limit_exceeded'
        assert data['error']['retry_after'] == 60
    
    def test_http_exception_handler(self, app, client):
        """Test standard HTTP exception handler."""
        # Test 404 Not Found
        response = client.get('/nonexistent-route')
        
        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['error_type'] == 'http_error'
    
    def test_generic_exception_handler(self, app, client):
        """Test generic exception handler."""
        @app.route('/test-generic-error')
        def test_generic_error():
            raise ValueError("Unexpected error")
        
        response = client.get('/test-generic-error')
        
        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['error_type'] == 'internal_server_error'
        assert data['error']['message'] == 'An unexpected error occurred'
