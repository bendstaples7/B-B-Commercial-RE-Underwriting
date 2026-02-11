"""API routes."""
from flask import jsonify, request
from marshmallow import ValidationError
from functools import wraps
from app.controllers import api_bp
from app.controllers.workflow_controller import WorkflowController
from app.models.analysis_session import WorkflowStep
from app.schemas import (
    StartAnalysisSchema,
    PropertyFactsSchema,
    UpdateComparablesSchema,
    AdvanceStepSchema,
    ExportGoogleSheetsSchema
)
from app.services.report_generator import ReportGenerator
from app import limiter
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize workflow controller
workflow_controller = WorkflowController()
report_generator = ReportGenerator()


def handle_errors(f):
    """Decorator for consistent error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning(f"Validation error: {e.messages}")
            return jsonify({
                'error': 'Validation error',
                'details': e.messages
            }), 400
        except ValueError as e:
            logger.warning(f"Value error: {str(e)}")
            return jsonify({
                'error': 'Invalid request',
                'message': str(e)
            }), 400
        except KeyError as e:
            logger.warning(f"Key error: {str(e)}")
            return jsonify({
                'error': 'Missing required field',
                'field': str(e)
            }), 400
        except Exception as e:
            # Check if it's an HTTP exception (like UnsupportedMediaType)
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning(f"HTTP error {e.code}: {e.description}")
                return jsonify({
                    'error': e.name if hasattr(e, 'name') else 'HTTP error',
                    'message': e.description
                }), e.code
            
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred'
            }), 500
    return decorated_function


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


@api_bp.route('/analysis/start', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def start_analysis():
    """
    Start new analysis with address.
    
    Request body:
        {
            "address": "123 Main St, Chicago, IL 60601",
            "user_id": "user123"
        }
    
    Response:
        {
            "session_id": "uuid",
            "user_id": "user123",
            "current_step": "PROPERTY_FACTS",
            "created_at": "2024-01-01T00:00:00",
            "status": "initialized"
        }
    """
    # Validate request data
    schema = StartAnalysisSchema()
    data = schema.load(request.get_json())
    
    # Start analysis
    result = workflow_controller.start_analysis(
        address=data['address'],
        user_id=data['user_id']
    )
    
    logger.info(f"Started analysis session {result['session_id']} for user {data['user_id']}")
    
    return jsonify(result), 201


@api_bp.route('/analysis/<session_id>', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_session_state(session_id):
    """
    Get session state.
    
    Response:
        {
            "session_id": "uuid",
            "user_id": "user123",
            "current_step": "PROPERTY_FACTS",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "subject_property": {...},
            "comparables": [...],
            "comparable_count": 10,
            "ranked_comparables": [...],
            "valuation_result": {...},
            "scenarios": [...]
        }
    """
    state = workflow_controller.get_session_state(session_id)
    
    return jsonify(state), 200


@api_bp.route('/analysis/<session_id>/step/<int:step_number>', methods=['POST'])
@limiter.limit("20 per minute")
@handle_errors
def advance_to_step(session_id, step_number):
    """
    Advance to next step.
    
    Request body:
        {
            "approval_data": {...}  // Optional
        }
    
    Response:
        {
            "session_id": "uuid",
            "current_step": "COMPARABLE_SEARCH",
            "previous_step": "PROPERTY_FACTS",
            "result": {...},
            "updated_at": "2024-01-01T00:00:00"
        }
    """
    # Validate request data
    schema = AdvanceStepSchema()
    data = schema.load(request.get_json() or {})
    
    # Convert step number to WorkflowStep enum
    try:
        target_step = WorkflowStep(step_number)
    except ValueError:
        return jsonify({
            'error': 'Invalid step number',
            'message': f'Step number must be between 1 and 6'
        }), 400
    
    # Advance to step
    result = workflow_controller.advance_to_step(
        session_id=session_id,
        target_step=target_step,
        approval_data=data.get('approval_data')
    )
    
    logger.info(f"Advanced session {session_id} to step {target_step.name}")
    
    return jsonify(result), 200


@api_bp.route('/analysis/<session_id>/step/<int:step_number>', methods=['PUT'])
@limiter.limit("20 per minute")
@handle_errors
def update_step_data(session_id, step_number):
    """
    Update step data.
    
    Request body depends on step:
    - Step 1 (Property Facts): PropertyFactsSchema
    - Step 3 (Comparable Review): UpdateComparablesSchema
    
    Response:
        {
            "session_id": "uuid",
            "step": "PROPERTY_FACTS",
            "updated_data": {...},
            "recalculations": [...],
            "updated_at": "2024-01-01T00:00:00"
        }
    """
    # Convert step number to WorkflowStep enum
    try:
        step = WorkflowStep(step_number)
    except ValueError:
        return jsonify({
            'error': 'Invalid step number',
            'message': f'Step number must be between 1 and 6'
        }), 400
    
    # Get request data
    data = request.get_json()
    
    # Validate based on step
    if step == WorkflowStep.PROPERTY_FACTS:
        schema = PropertyFactsSchema()
        validated_data = schema.load(data)
    elif step == WorkflowStep.COMPARABLE_REVIEW:
        schema = UpdateComparablesSchema()
        validated_data = schema.load(data)
    else:
        validated_data = data
    
    # Update step data
    result = workflow_controller.update_step_data(
        session_id=session_id,
        step=step,
        data=validated_data
    )
    
    logger.info(f"Updated step {step.name} data for session {session_id}")
    
    return jsonify(result), 200


@api_bp.route('/analysis/<session_id>/back/<int:step_number>', methods=['POST'])
@limiter.limit("20 per minute")
@handle_errors
def go_back_to_step(session_id, step_number):
    """
    Go back to previous step.
    
    Response:
        {
            "session_id": "uuid",
            "user_id": "user123",
            "current_step": "PROPERTY_FACTS",
            "previous_step": "COMPARABLE_SEARCH",
            "navigation": "backward",
            ...
        }
    """
    # Convert step number to WorkflowStep enum
    try:
        target_step = WorkflowStep(step_number)
    except ValueError:
        return jsonify({
            'error': 'Invalid step number',
            'message': f'Step number must be between 1 and 6'
        }), 400
    
    # Go back to step
    result = workflow_controller.go_back_to_step(
        session_id=session_id,
        target_step=target_step
    )
    
    logger.info(f"Navigated session {session_id} back to step {target_step.name}")
    
    return jsonify(result), 200


@api_bp.route('/analysis/<session_id>/report', methods=['GET'])
@limiter.limit("10 per minute")
@handle_errors
def generate_report(session_id):
    """
    Generate report.
    
    Response:
        {
            "report": {
                "section_a": {...},
                "section_b": {...},
                "section_c": {...},
                "section_d": {...},
                "section_e": {...},
                "section_f": {...}
            }
        }
    """
    # Get session
    from app.models import AnalysisSession
    session = AnalysisSession.query.filter_by(session_id=session_id).first()
    
    if not session:
        return jsonify({
            'error': 'Session not found',
            'message': f'Session {session_id} does not exist'
        }), 404
    
    # Generate report
    report = report_generator.generate_report(session)
    
    logger.info(f"Generated report for session {session_id}")
    
    return jsonify({'report': report}), 200


@api_bp.route('/analysis/<session_id>/export/excel', methods=['GET'])
@limiter.limit("5 per minute")
@handle_errors
def export_to_excel(session_id):
    """
    Export to Excel.
    
    Response:
        Binary Excel file
    """
    from flask import send_file
    from io import BytesIO
    from app.models import AnalysisSession
    
    # Get session
    session = AnalysisSession.query.filter_by(session_id=session_id).first()
    
    if not session:
        return jsonify({
            'error': 'Session not found',
            'message': f'Session {session_id} does not exist'
        }), 404
    
    # Generate report first
    report = report_generator.generate_report(session)
    
    # Export to Excel
    excel_bytes = report_generator.export_to_excel(report)
    
    logger.info(f"Exported Excel report for session {session_id}")
    
    # Return as downloadable file
    return send_file(
        BytesIO(excel_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'real_estate_analysis_{session_id}.xlsx'
    )


@api_bp.route('/analysis/<session_id>/export/sheets', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def export_to_google_sheets(session_id):
    """
    Export to Google Sheets.
    
    Request body:
        {
            "credentials": {...}  // Google OAuth credentials
        }
    
    Response:
        {
            "url": "https://docs.google.com/spreadsheets/d/...",
            "spreadsheet_id": "..."
        }
    """
    from app.models import AnalysisSession
    
    # Validate request data
    schema = ExportGoogleSheetsSchema()
    data = schema.load(request.get_json())
    
    # Get session
    session = AnalysisSession.query.filter_by(session_id=session_id).first()
    
    if not session:
        return jsonify({
            'error': 'Session not found',
            'message': f'Session {session_id} does not exist'
        }), 404
    
    # Generate report first
    report = report_generator.generate_report(session)
    
    # Export to Google Sheets
    url = report_generator.export_to_google_sheets(report, data['credentials'])
    
    logger.info(f"Exported Google Sheets report for session {session_id}")
    
    return jsonify({
        'url': url,
        'message': 'Report exported successfully to Google Sheets'
    }), 200
