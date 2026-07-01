"""Shared error handler for Open Letter and mail queue API blueprints."""
from __future__ import annotations

import logging
from functools import wraps

from flask import jsonify
from marshmallow import ValidationError
from werkzeug.exceptions import BadRequest, HTTPException

from app.exceptions import MailQueueError, RealEstateAnalysisException

logger = logging.getLogger(__name__)


def handle_mail_api_errors(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({'error': 'Validation error', 'details': e.messages}), 400
        except BadRequest as e:
            return jsonify({'error': 'Invalid request', 'message': e.description}), 400
        except HTTPException as e:
            return jsonify({'error': 'Invalid request', 'message': e.description}), e.code
        except MailQueueError as e:
            return jsonify({'error': 'Mail queue error', 'message': e.message}), e.status_code
        except RealEstateAnalysisException as e:
            return jsonify({'error': 'Application error', 'message': e.message, **e.payload}), e.status_code
        except ValueError as e:
            return jsonify({'error': 'Invalid request', 'message': str(e)}), 400
        except Exception as e:
            logger.error('Mail API error: %s', e, exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500
    return decorated
