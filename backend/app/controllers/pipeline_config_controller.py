import logging
from functools import wraps

from flask import Blueprint, jsonify, request, g
from marshmallow import ValidationError

from app import db
from app.exceptions import RealEstateAnalysisException
from app.schemas import PipelineStageConfigSchema
from app.services.pipeline_config_service import PipelineConfigService

logger = logging.getLogger(__name__)

pipeline_config_bp = Blueprint('pipeline_config', __name__)

# Schema instances
_pipeline_stage_config_schema = PipelineStageConfigSchema(many=True) # For listing multiple stages
_pipeline_stage_update_schema = PipelineStageConfigSchema()

# Service instance
_pipeline_config_service = PipelineConfigService()

# ---------------------------------------------------------------------------
# Shared error handling decorator (copy from multifamily_deal_controller for consistency)
# ---------------------------------------------------------------------------

def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error: %s", e.messages)
            return jsonify({
                'error': 'Validation error',
                'details': e.messages,
            }), 400
        except RealEstateAnalysisException as e:
            logger.warning("Application error [%s]: %s", e.status_code, e.message)
            return jsonify({
                'error': e.message,
                **e.payload,
            }), e.status_code
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code

            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pipeline_config_bp.route('/pipeline-stages', methods=['GET'])
@handle_errors
def get_pipeline_stages():
    """Returns an ordered list of pipeline stages with stage_name, order, weight."""
    stages = _pipeline_config_service.get_all_stages_ordered()
    return jsonify(_pipeline_stage_config_schema.dump(stages)), 200


@pipeline_config_bp.route('/pipeline-stages/weights', methods=['PUT'])
@handle_errors
def update_pipeline_stage_weights():
    """Accepts a list of {stage_name: weight} pairs to update stage weights (admin-only)."""
    # Admin access check using is_admin set by auth middleware
    if not getattr(g, 'is_admin', False):
        raise RealEstateAnalysisException("Admin access required to update stage weights", status_code=403)

    payload = request.get_json()
    if not isinstance(payload, list):
        return jsonify({'error': 'Payload must be a list of stage update objects.'}), 400

    # Validate each item in the payload using the schema for single stage update
    validated_updates = []
    for item in payload:
        try:
            validated_updates.append(_pipeline_stage_update_schema.load(item))  # no partial=True — all required fields must be present
        except ValidationError as e:
            return jsonify({'error': 'Validation error in stage update payload', 'details': e.messages}), 400

    updated_stages = _pipeline_config_service.update_stage_weights(validated_updates)
    # Service already commits; no need for a redundant commit here

    return jsonify(_pipeline_stage_config_schema.dump(updated_stages)), 200
