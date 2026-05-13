"""Commercial OM PDF Intake API endpoints.

Provides endpoints for uploading OM PDFs, polling job status, reviewing
extracted data, confirming intake to create a Deal, and retrying failed jobs.

Requirements: 1.1, 1.2, 1.3, 1.7, 1.8, 5.1, 7.9, 8.1, 8.2, 8.3, 8.4, 8.5, 9.3
"""
import logging

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import limiter
from app.exceptions import ConflictError, RealEstateAnalysisException, ResourceNotFoundError
from app.schemas import (
    OMIntakeConfirmRequestSchema,
    OMIntakeJobListSchema,
    OMIntakeJobStatusSchema,
    OMIntakeReviewSchema,
)
from app.services.om_intake.om_intake_service import OMIntakeService

logger = logging.getLogger(__name__)

om_intake_bp = Blueprint('om_intake', __name__)

# Schema instances
_job_status_schema = OMIntakeJobStatusSchema()
_job_list_schema = OMIntakeJobListSchema()
_review_schema = OMIntakeReviewSchema()
_confirm_request_schema = OMIntakeConfirmRequestSchema()


# ---------------------------------------------------------------------------
# Shared error handling decorator (mirrors multifamily_deal_controller pattern)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling across OM intake endpoints."""
    from functools import wraps

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


def get_user_id() -> str:
    """Extract user ID from request headers.

    Falls back to 'anonymous' for development/testing.
    """
    return request.headers.get('X-User-Id', 'anonymous')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_job_status(job) -> dict:
    """Serialize an OMIntakeJob to a status response dict."""
    return _job_status_schema.dump(job)


def _serialize_job_list_item(job) -> dict:
    """Serialize an OMIntakeJob to a list-item response dict, including summary fields."""
    data = _job_list_schema.dump(job)

    # Enrich with summary fields from extracted_om_data if available
    extracted = job.extracted_om_data or {}

    def _get_val(field_dict):
        if isinstance(field_dict, dict):
            return field_dict.get('value')
        return None

    # property_address: try property_address field first, then build from parts
    address_val = _get_val(extracted.get('property_address'))
    if address_val is None:
        city = _get_val(extracted.get('property_city'))
        state = _get_val(extracted.get('property_state'))
        if city and state:
            address_val = f"{city}, {state}"
    data['property_address'] = address_val

    asking_price_raw = _get_val(extracted.get('asking_price'))
    data['asking_price'] = asking_price_raw

    unit_count_raw = _get_val(extracted.get('unit_count'))
    try:
        data['unit_count'] = int(unit_count_raw) if unit_count_raw is not None else None
    except (TypeError, ValueError):
        data['unit_count'] = None

    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@om_intake_bp.route('/jobs', methods=['POST'])
@limiter.limit("20 per hour")
@handle_errors
def upload_om_pdf():
    """Upload an OM PDF and create a new intake job.

    Expects a multipart/form-data request with a 'file' field.

    Requirements: 1.1, 1.2, 1.3
    """
    if 'file' not in request.files:
        return jsonify({
            'error': 'No file provided',
            'message': "Request must include a 'file' field in multipart/form-data.",
        }), 422

    uploaded_file = request.files['file']
    if not uploaded_file.filename:
        return jsonify({
            'error': 'No file selected',
            'message': 'The file field is present but no file was selected.',
        }), 422

    file_bytes = uploaded_file.read()
    filename = uploaded_file.filename
    user_id = get_user_id()

    service = OMIntakeService()
    job = service.create_job(user_id, file_bytes, filename)

    return jsonify({
        'intake_job_id': job.id,
        'status': job.intake_status,
    }), 201


@om_intake_bp.route('/jobs', methods=['GET'])
@handle_errors
def list_jobs():
    """List the authenticated user's OM intake jobs, newest first.

    Query params:
        page (int, default 1): Page number (1-based).
        page_size (int, default 25): Records per page (clamped to [1, 100]).

    Requirements: 8.1
    """
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 25, type=int)
    user_id = get_user_id()

    service = OMIntakeService()
    jobs, total = service.list_jobs(user_id, page, page_size)

    return jsonify({
        'jobs': [_serialize_job_list_item(j) for j in jobs],
        'total': total,
        'page': page,
        'page_size': page_size,
    }), 200


@om_intake_bp.route('/jobs/<int:job_id>', methods=['GET'])
@limiter.limit("2000 per hour")
@handle_errors
def get_job_status(job_id):
    """Get the status and metadata for a single OM intake job.

    Returns 404 if the job does not exist or belongs to another user.
    Returns 410 if the job has expired (Req 8.3).

    Requirements: 1.7, 1.8, 8.3
    """
    user_id = get_user_id()
    service = OMIntakeService()

    try:
        job = service.get_job(user_id, job_id)
    except ResourceNotFoundError as e:
        if e.payload.get('reason') == 'expired':
            return jsonify({
                'error': e.message,
                **e.payload,
            }), 410
        raise

    return jsonify(_serialize_job_status(job)), 200


@om_intake_bp.route('/jobs/<int:job_id>/review', methods=['GET'])
@handle_errors
def get_job_review(job_id):
    """Get the full review data for a job in REVIEW or CONFIRMED status.

    If the job is not yet in REVIEW/CONFIRMED, returns the current status
    without extracted data so the frontend can continue polling.

    Requirements: 5.1, 8.2
    """
    user_id = get_user_id()
    service = OMIntakeService()

    try:
        job = service.get_job(user_id, job_id)
    except ResourceNotFoundError as e:
        if e.payload.get('reason') == 'expired':
            return jsonify({
                'error': e.message,
                **e.payload,
            }), 410
        raise

    if job.intake_status not in ('REVIEW', 'CONFIRMED'):
        # Job is still processing — return status only so the frontend can poll
        return jsonify({
            'id': job.id,
            'intake_status': job.intake_status,
            'original_filename': job.original_filename,
            'message': f'Review data is not yet available. Current status: {job.intake_status}',
        }), 200

    return jsonify(_review_schema.dump(job)), 200


@om_intake_bp.route('/jobs/<int:job_id>/confirm', methods=['POST'])
@handle_errors
def confirm_job(job_id):
    """Confirm an OM intake job and create a pre-populated Deal record.

    Accepts an optional JSON body with user-confirmed field overrides.

    Requirements: 7.9, 8.4
    """
    user_id = get_user_id()
    service = OMIntakeService()

    raw_body = request.get_json(silent=True) or {}
    confirmed_data = _confirm_request_schema.load(raw_body)

    try:
        job = service.get_job(user_id, job_id)
    except ResourceNotFoundError as e:
        if e.payload.get('reason') == 'expired':
            return jsonify({
                'error': e.message,
                **e.payload,
            }), 410
        raise

    deal = service.confirm_job(user_id, job_id, confirmed_data)

    return jsonify({
        'deal_id': deal.id,
        'status': 'CONFIRMED',
    }), 200


@om_intake_bp.route('/jobs/<int:job_id>/retry', methods=['POST'])
@handle_errors
def retry_job(job_id):
    """Retry a FAILED OM intake job by creating a new PENDING job from the same PDF.

    The original FAILED job is preserved.

    Requirements: 9.3, 8.5
    """
    user_id = get_user_id()
    service = OMIntakeService()

    try:
        new_job = service.retry_failed_job(user_id, job_id)
    except ResourceNotFoundError as e:
        if e.payload.get('reason') == 'expired':
            return jsonify({
                'error': e.message,
                **e.payload,
            }), 410
        raise

    return jsonify({
        'intake_job_id': new_job.id,
        'status': new_job.intake_status,
    }), 201
