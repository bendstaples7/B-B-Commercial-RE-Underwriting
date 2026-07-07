"""Shared Flask controller decorators."""
import logging
from functools import wraps

from flask import jsonify
from marshmallow import ValidationError

logger = logging.getLogger(__name__)


def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({'error': 'Validation error', 'details': e.messages}), 400
        except ValueError as e:
            return jsonify({'error': 'Invalid request', 'message': str(e)}), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                return jsonify({'error': getattr(e, 'name', 'HTTP error'), 'message': e.description}), e.code
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({'error': 'Internal server error', 'message': 'An unexpected error occurred'}), 500
    return decorated_function
