"""Error handlers and response formatters for Flask application."""
from flask import jsonify
from werkzeug.exceptions import HTTPException
import logging
from app.exceptions import RealEstateAnalysisException

logger = logging.getLogger(__name__)


def format_error_response(error, status_code=500, **kwargs):
    """
    Format error response with consistent JSON structure.
    
    Args:
        error: Exception or error message
        status_code: HTTP status code
        **kwargs: Additional fields to include in response
        
    Returns:
        tuple: (response_dict, status_code)
    """
    response = {
        'success': False,
        'error': {
            'message': str(error),
            'status_code': status_code
        }
    }
    
    # Add any additional fields
    if kwargs:
        response['error'].update(kwargs)
    
    return response, status_code


def handle_real_estate_exception(error: RealEstateAnalysisException):
    """
    Handle custom RealEstateAnalysisException errors.
    
    Args:
        error: RealEstateAnalysisException instance
        
    Returns:
        Flask JSON response
    """
    logger.error(
        f"{error.__class__.__name__}: {error.message}",
        extra={'payload': error.payload}
    )
    
    response = {
        'success': False,
        'error': {
            'message': error.message,
            'status_code': error.status_code,
            **error.payload
        }
    }
    
    return jsonify(response), error.status_code


def handle_http_exception(error: HTTPException):
    """
    Handle standard HTTP exceptions.
    
    Args:
        error: HTTPException instance
        
    Returns:
        Flask JSON response
    """
    logger.warning(f"HTTP {error.code}: {error.description}")
    
    response = {
        'success': False,
        'error': {
            'message': error.description,
            'status_code': error.code,
            'error_type': 'http_error'
        }
    }
    
    return jsonify(response), error.code


def handle_validation_error(error):
    """
    Handle marshmallow validation errors.
    
    Args:
        error: ValidationError instance
        
    Returns:
        Flask JSON response
    """
    logger.warning(f"Validation error: {error.messages}")
    
    response = {
        'success': False,
        'error': {
            'message': 'Request validation failed',
            'status_code': 400,
            'error_type': 'validation_error',
            'validation_errors': error.messages
        }
    }
    
    return jsonify(response), 400


def handle_generic_exception(error: Exception):
    """
    Handle unexpected generic exceptions.
    
    Args:
        error: Exception instance
        
    Returns:
        Flask JSON response
    """
    logger.exception(f"Unhandled exception: {str(error)}")
    
    response = {
        'success': False,
        'error': {
            'message': 'An unexpected error occurred',
            'status_code': 500,
            'error_type': 'internal_server_error'
        }
    }
    
    return jsonify(response), 500


def register_error_handlers(app):
    """
    Register all error handlers with Flask application.
    
    Args:
        app: Flask application instance
    """
    # Handle custom exceptions
    app.register_error_handler(RealEstateAnalysisException, handle_real_estate_exception)
    
    # Handle HTTP exceptions
    app.register_error_handler(HTTPException, handle_http_exception)
    
    # Handle validation errors (marshmallow)
    try:
        from marshmallow import ValidationError
        app.register_error_handler(ValidationError, handle_validation_error)
    except ImportError:
        pass
    
    # Handle generic exceptions (catch-all)
    app.register_error_handler(Exception, handle_generic_exception)
    
    logger.info("Error handlers registered successfully")
