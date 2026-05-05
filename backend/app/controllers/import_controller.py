"""Import API endpoints for Google Sheets integration.

Provides endpoints for OAuth2 authentication, sheet discovery, field mapping,
import job management, and import re-runs.
"""
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app import db, limiter
from app.models import ImportJob, FieldMapping, OAuthToken
from app.services.google_sheets_importer import GoogleSheetsImporter

logger = logging.getLogger(__name__)

import_bp = Blueprint('imports', __name__)

importer = GoogleSheetsImporter()


# ---------------------------------------------------------------------------
# Error handling decorator (consistent with lead_controller pattern)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent error handling."""
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
        except ValueError as e:
            logger.warning("Value error: %s", str(e))
            return jsonify({
                'error': 'Invalid request',
                'message': str(e),
            }), 400
        except Exception as e:
            # Surface Google API errors with their actual message
            if hasattr(e, 'reason'):
                logger.warning("Google API error: %s", e.reason)
                return jsonify({
                    'error': 'Google API error',
                    'message': str(e.reason),
                }), 400

            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': getattr(e, 'name', 'HTTP error'),
                    'message': e.description,
                }), e.code

            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return jsonify({
                'error': 'Internal server error',
                'message': str(e) if str(e) else 'An unexpected error occurred',
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_import_job(job):
    """Serialize an ImportJob to a dictionary."""
    return {
        'id': job.id,
        'user_id': job.user_id,
        'spreadsheet_id': job.spreadsheet_id,
        'sheet_name': job.sheet_name,
        'field_mapping_id': job.field_mapping_id,
        'status': job.status,
        'total_rows': job.total_rows,
        'rows_processed': job.rows_processed,
        'rows_imported': job.rows_imported,
        'rows_skipped': job.rows_skipped,
        'error_log': job.error_log,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'created_at': job.created_at.isoformat() if job.created_at else None,
    }


def _serialize_field_mapping(mapping):
    """Serialize a FieldMapping to a dictionary."""
    return {
        'id': mapping.id,
        'user_id': mapping.user_id,
        'spreadsheet_id': mapping.spreadsheet_id,
        'sheet_name': mapping.sheet_name,
        'mapping': mapping.mapping,
        'created_at': mapping.created_at.isoformat() if mapping.created_at else None,
        'updated_at': mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


def _enqueue_import_task(job_id: int, lead_category: str = 'residential') -> None:
    """Attempt to enqueue an import job via Celery.

    Falls back to synchronous processing when the Celery broker is
    unavailable so the API remains functional in development environments
    without a running worker.
    """
    try:
        from celery_worker import import_task  # noqa: WPS433
        import_task.apply_async(args=[job_id, lead_category], ignore_result=True)
        logger.info("Enqueued import task for job %d (category=%s)", job_id, lead_category)
    except Exception as enqueue_err:
        logger.warning(
            "Could not enqueue Celery task for job %d, running synchronously: %s",
            job_id, enqueue_err,
        )
        importer.process_import(job_id, lead_category=lead_category)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@import_bp.route('/auth', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def authenticate():
    """Authenticate with Google OAuth2.

    Supports two flows:

    1. **Initiate** – send ``client_id`` and ``client_secret`` (and
       optionally ``user_id``).  The endpoint returns an ``auth_url``
       that the frontend should open in a new window / redirect to.
    2. **Complete** – send ``auth_code`` (and optionally ``client_id``,
       ``client_secret``, ``redirect_uri``, ``user_id``).  The endpoint
       exchanges the code for tokens and stores them.

    Returns
    -------
    200 on success with user_id (and optionally auth_url).
    401 on authentication failure.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    # Unwrap if the frontend wrapped in a ``credentials`` key
    credentials = data.get('credentials', data)

    # If there is already an auth_code or refresh_token, go straight to
    # the token-exchange / validation path.
    if 'auth_code' in credentials or 'refresh_token' in credentials:
        result = importer.authenticate(credentials)
        if not result.success:
            logger.warning("OAuth2 authentication failed: %s", result.error)
            return jsonify({
                'error': 'Authentication failed',
                'message': result.error,
            }), 401
        return jsonify({
            'message': 'Authentication successful',
            'user_id': result.user_id,
        }), 200

    # Otherwise, generate an authorization URL so the user can consent.
    import os as _os
    from google_auth_oauthlib.flow import Flow as _Flow

    client_id = credentials.get('client_id', _os.getenv('GOOGLE_CLIENT_ID', ''))
    client_secret = credentials.get('client_secret', _os.getenv('GOOGLE_CLIENT_SECRET', ''))
    redirect_uri = credentials.get('redirect_uri', 'http://localhost:3000/import/callback')

    if not client_id or not client_secret:
        return jsonify({
            'error': 'Validation error',
            'message': 'client_id and client_secret are required',
        }), 400

    flow = _Flow.from_client_config(
        {
            'web': {
                'client_id': client_id,
                'client_secret': client_secret,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
        redirect_uri=redirect_uri,
    )

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )

    return jsonify({
        'message': 'Authorization required',
        'auth_url': auth_url,
        'redirect_uri': redirect_uri,
        'user_id': credentials.get('user_id', 'default'),
    }), 200


@import_bp.route('/sheets', methods=['GET'])
@limiter.limit("20 per minute")
@handle_errors
def list_sheets():
    """List available sheets from a Google Spreadsheet.

    Query parameters
    ----------------
    spreadsheet_id : str (required)
    user_id : str (default "default")

    Returns
    -------
    200 with list of sheets.
    """
    spreadsheet_id = request.args.get('spreadsheet_id')
    if not spreadsheet_id:
        return jsonify({
            'error': 'Validation error',
            'message': 'spreadsheet_id query parameter is required',
        }), 400

    user_id = request.args.get('user_id', 'default')
    token = OAuthToken.query.filter_by(user_id=user_id).first()
    if not token:
        return jsonify({
            'error': 'Authentication required',
            'message': f'No OAuth token found for user {user_id}. Please authenticate first.',
        }), 401

    sheets = importer.list_sheets(spreadsheet_id, token)

    return jsonify({
        'spreadsheet_id': spreadsheet_id,
        'sheets': [
            {
                'sheet_id': s.sheet_id,
                'title': s.title,
                'row_count': s.row_count,
                'column_count': s.column_count,
            }
            for s in sheets
        ],
    }), 200


@import_bp.route('/headers', methods=['GET'])
@limiter.limit("20 per minute")
@handle_errors
def read_headers():
    """Read headers from a selected sheet.

    Query parameters
    ----------------
    spreadsheet_id : str (required)
    sheet_name : str (required)
    user_id : str (default "default")

    Returns
    -------
    200 with headers list and auto-mapped field suggestions.
    """
    spreadsheet_id = request.args.get('spreadsheet_id')
    sheet_name = request.args.get('sheet_name')

    if not spreadsheet_id:
        return jsonify({
            'error': 'Validation error',
            'message': 'spreadsheet_id query parameter is required',
        }), 400
    if not sheet_name:
        return jsonify({
            'error': 'Validation error',
            'message': 'sheet_name query parameter is required',
        }), 400

    user_id = request.args.get('user_id', 'default')
    token = OAuthToken.query.filter_by(user_id=user_id).first()
    if not token:
        return jsonify({
            'error': 'Authentication required',
            'message': f'No OAuth token found for user {user_id}. Please authenticate first.',
        }), 401

    headers = importer.read_headers(spreadsheet_id, sheet_name, token)
    auto_mapping = importer.auto_map_fields(headers)

    return jsonify({
        'spreadsheet_id': spreadsheet_id,
        'sheet_name': sheet_name,
        'headers': headers,
        'auto_mapping': auto_mapping,
    }), 200


@import_bp.route('/mapping', methods=['POST'])
@limiter.limit("20 per minute")
@handle_errors
def save_mapping():
    """Save or update a field mapping for a spreadsheet/sheet combination.

    Request body
    ------------
    user_id : str (required)
    spreadsheet_id : str (required)
    sheet_name : str (required)
    mapping : dict (required)
        ``{sheet_column_header: db_field_name}``

    Returns
    -------
    200 on update, 201 on create.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    user_id = data.get('user_id')
    spreadsheet_id = data.get('spreadsheet_id')
    sheet_name = data.get('sheet_name')
    mapping = data.get('mapping')

    # Validate required fields
    missing = []
    if not user_id:
        missing.append('user_id')
    if not spreadsheet_id:
        missing.append('spreadsheet_id')
    if not sheet_name:
        missing.append('sheet_name')
    if mapping is None:
        missing.append('mapping')
    if missing:
        return jsonify({
            'error': 'Validation error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    if not isinstance(mapping, dict):
        return jsonify({
            'error': 'Validation error',
            'message': 'mapping must be a JSON object',
        }), 400

    # Validate that required DB fields are covered
    is_valid, missing_fields = GoogleSheetsImporter.validate_mapping(mapping)
    if not is_valid:
        return jsonify({
            'error': 'Validation error',
            'message': f'Required fields not mapped: {", ".join(missing_fields)}',
        }), 400

    # Upsert the field mapping
    existing = FieldMapping.query.filter_by(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
    ).first()

    if existing:
        existing.mapping = mapping
        existing.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(
            "Updated field mapping %d for user %s, sheet %s",
            existing.id, user_id, sheet_name,
        )
        return jsonify(_serialize_field_mapping(existing)), 200
    else:
        new_mapping = FieldMapping(
            user_id=user_id,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            mapping=mapping,
        )
        db.session.add(new_mapping)
        db.session.commit()
        logger.info(
            "Created field mapping %d for user %s, sheet %s",
            new_mapping.id, user_id, sheet_name,
        )
        return jsonify(_serialize_field_mapping(new_mapping)), 201


@import_bp.route('/start', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def start_import():
    """Create an ImportJob and enqueue the Celery import task.

    Request body
    ------------
    user_id : str (required)
    spreadsheet_id : str (required)
    sheet_name : str (required)
    field_mapping_id : int (optional — if omitted, looks up saved mapping)

    Returns
    -------
    201 with the new ImportJob details.
    409 if an import is already in progress for the same spreadsheet.
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'error': 'Validation error',
            'message': 'Request body is required',
        }), 400

    user_id = data.get('user_id')
    spreadsheet_id = data.get('spreadsheet_id')
    sheet_name = data.get('sheet_name')

    missing = []
    if not user_id:
        missing.append('user_id')
    if not spreadsheet_id:
        missing.append('spreadsheet_id')
    if not sheet_name:
        missing.append('sheet_name')
    if missing:
        return jsonify({
            'error': 'Validation error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    # Check for an active import on the same spreadsheet
    active_job = ImportJob.query.filter(
        ImportJob.spreadsheet_id == spreadsheet_id,
        ImportJob.status.in_(['pending', 'in_progress']),
    ).first()
    if active_job:
        return jsonify({
            'error': 'Conflict',
            'message': (
                f'An import is already in progress for spreadsheet {spreadsheet_id} '
                f'(job {active_job.id}, status: {active_job.status}). '
                'Please wait for it to complete before starting a new one.'
            ),
        }), 409

    # Resolve field mapping
    field_mapping_id = data.get('field_mapping_id')
    if field_mapping_id:
        fm = db.session.get(FieldMapping, field_mapping_id)
        if not fm:
            return jsonify({
                'error': 'Not found',
                'message': f'FieldMapping {field_mapping_id} does not exist',
            }), 404
    else:
        fm = FieldMapping.query.filter_by(
            user_id=user_id,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
        ).first()
        if not fm:
            return jsonify({
                'error': 'Validation error',
                'message': (
                    'No field mapping found. Please save a field mapping first '
                    'via POST /api/leads/import/mapping.'
                ),
            }), 400
        field_mapping_id = fm.id

    # Verify OAuth token exists
    token = OAuthToken.query.filter_by(user_id=user_id).first()
    if not token:
        return jsonify({
            'error': 'Authentication required',
            'message': f'No OAuth token found for user {user_id}. Please authenticate first.',
        }), 401

    # Create the ImportJob
    job = ImportJob(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
        field_mapping_id=field_mapping_id,
        status='pending',
    )
    db.session.add(job)
    db.session.commit()

    # Enqueue the Celery task.
    # We attempt to send to Celery; if the broker is unavailable we fall
    # back to synchronous processing so the API remains functional in
    # development environments without a running Celery worker.
    lead_category = data.get('lead_category', 'residential')
    _enqueue_import_task(job.id, lead_category=lead_category)

    # Re-read the job to get the latest state
    db.session.refresh(job)

    return jsonify(_serialize_import_job(job)), 201


@import_bp.route('/jobs', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def list_import_jobs():
    """List import jobs with optional filtering.

    Query parameters
    ----------------
    user_id : str (optional — filter by user)
    status : str (optional — filter by status)
    page : int (default 1)
    per_page : int (default 20, max 100)

    Returns
    -------
    200 with paginated list of import jobs.
    """
    args = request.args
    page = max(1, int(args.get('page', 1)))
    per_page = max(1, min(int(args.get('per_page', 20)), 100))

    query = ImportJob.query

    user_id = args.get('user_id')
    if user_id:
        query = query.filter(ImportJob.user_id == user_id)

    status = args.get('status')
    if status:
        query = query.filter(ImportJob.status == status)

    query = query.order_by(ImportJob.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'jobs': [_serialize_import_job(job) for job in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }), 200


@import_bp.route('/jobs/<int:job_id>', methods=['GET'])
@limiter.limit("30 per minute")
@handle_errors
def get_import_job(job_id):
    """Get import job status and progress.

    Returns
    -------
    200 with full import job details including error log.
    404 if job not found.
    """
    job = db.session.get(ImportJob, job_id)
    if not job:
        return jsonify({
            'error': 'Import job not found',
            'message': f'Import job {job_id} does not exist',
        }), 404

    return jsonify(_serialize_import_job(job)), 200


@import_bp.route('/jobs/<int:job_id>/rerun', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def rerun_import(job_id):
    """Re-run a previous import using the same spreadsheet and field mapping.

    Creates a new ImportJob with the same configuration as the original
    and enqueues it for processing.

    Returns
    -------
    201 with the new ImportJob details.
    404 if original job not found.
    409 if an import is already in progress for the same spreadsheet.
    """
    original_job = db.session.get(ImportJob, job_id)
    if not original_job:
        return jsonify({
            'error': 'Import job not found',
            'message': f'Import job {job_id} does not exist',
        }), 404

    # Check for an active import on the same spreadsheet
    active_job = ImportJob.query.filter(
        ImportJob.spreadsheet_id == original_job.spreadsheet_id,
        ImportJob.status.in_(['pending', 'in_progress']),
    ).first()
    if active_job:
        return jsonify({
            'error': 'Conflict',
            'message': (
                f'An import is already in progress for spreadsheet '
                f'{original_job.spreadsheet_id} (job {active_job.id}, '
                f'status: {active_job.status}). '
                'Please wait for it to complete before re-running.'
            ),
        }), 409

    # Verify OAuth token still exists
    token = OAuthToken.query.filter_by(user_id=original_job.user_id).first()
    if not token:
        return jsonify({
            'error': 'Authentication required',
            'message': (
                f'No OAuth token found for user {original_job.user_id}. '
                'Please re-authenticate before re-running the import.'
            ),
        }), 401

    # Create a new ImportJob with the same configuration
    new_job = ImportJob(
        user_id=original_job.user_id,
        spreadsheet_id=original_job.spreadsheet_id,
        sheet_name=original_job.sheet_name,
        field_mapping_id=original_job.field_mapping_id,
        status='pending',
    )
    db.session.add(new_job)
    db.session.commit()

    # Enqueue the Celery task
    rerun_data = request.get_json(silent=True) or {}
    lead_category = rerun_data.get('lead_category', 'residential')
    _enqueue_import_task(new_job.id, lead_category=lead_category)

    db.session.refresh(new_job)

    return jsonify({
        'original_job_id': job_id,
        **_serialize_import_job(new_job),
    }), 201
