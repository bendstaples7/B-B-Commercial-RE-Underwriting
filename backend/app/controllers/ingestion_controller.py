"""Ingestion API endpoints for DuPage lead database ingestion.

Provides POST endpoints for each ingestion source type and a GET endpoint
for polling ImportJob status.

Blueprint prefix: /api/ingestion

Requirements: 9.1, 9.2, 9.6, 1.7
"""
import logging
from functools import wraps

from flask import Blueprint, g, jsonify, request
from marshmallow import ValidationError

from app import db, limiter

logger = logging.getLogger(__name__)

ingestion_bp = Blueprint('ingestion', __name__)


# ---------------------------------------------------------------------------
# Error handling decorator (consistent with project-wide pattern)
# ---------------------------------------------------------------------------

def handle_errors(f):
    """Decorator for consistent JSON error handling on ingestion endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning("Validation error in ingestion endpoint: %s", e.messages)
            return jsonify({
                'error': {
                    'message': 'Request validation failed',
                    'fields': e.messages,
                }
            }), 400
        except ValueError as e:
            logger.warning("Value error in ingestion endpoint: %s", str(e))
            return jsonify({
                'error': {
                    'message': str(e),
                }
            }), 400
        except RuntimeError as e:
            # ImportJob creation failures and similar abort-level errors
            logger.error("Runtime error in ingestion endpoint: %s", str(e))
            return jsonify({
                'error': {
                    'message': str(e),
                }
            }), 500
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'description'):
                logger.warning("HTTP error %s: %s", e.code, e.description)
                return jsonify({
                    'error': {
                        'message': e.description,
                    }
                }), e.code
            logger.error("Unexpected error in ingestion endpoint: %s", str(e), exc_info=True)
            return jsonify({
                'error': {
                    'message': 'An unexpected error occurred',
                }
            }), 500
    return decorated_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_service():
    """Construct a LeadIngestionService with DeduplicationEngine and GISConnectorRegistry.

    Importing inside the function avoids circular imports and ensures the
    GISConnectorRegistry is populated (the DuPageGISConnector registers itself
    at module-import time in dupage_gis_connector.py).
    """
    from app.services.deduplication_engine import DeduplicationEngine
    from app.services.gis.base import GISConnectorRegistry
    # Import the DuPage connector so it self-registers into GISConnectorRegistry
    import app.services.gis.dupage_gis_connector  # noqa: F401
    from app.services.lead_ingestion_service import LeadIngestionService

    dedup = DeduplicationEngine()
    service = LeadIngestionService(
        dedup_engine=dedup,
        gis_registry=GISConnectorRegistry,
    )
    return service


def _validate_ingestion_body(data: dict) -> dict:
    """Validate request body against IngestionRequestSchema.

    Returns the deserialized (loaded) data on success.
    Raises ValidationError on failure (caught by @handle_errors).
    """
    from app.schemas import IngestionRequestSchema
    schema = IngestionRequestSchema()
    return schema.load(data)


def _serialize_import_job(job) -> dict:
    """Serialize an ImportJob using ImportJobResponseSchema."""
    from app.schemas import ImportJobResponseSchema
    schema = ImportJobResponseSchema()
    return schema.dump(job)


def _get_caller_user_id() -> str:
    """Resolve the authenticated caller from g.user_id (set by before_request).

    Falls back to 'anonymous' when no X-User-Id header was provided.
    The set_user_identity() before_request hook in app/__init__.py populates g.user_id.
    """
    return getattr(g, 'user_id', 'anonymous')


# ---------------------------------------------------------------------------
# POST ingestion endpoints
# ---------------------------------------------------------------------------

@ingestion_bp.route('/foreclosure', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def ingest_foreclosure():
    """Ingest foreclosure/sheriff sale records.

    Request body (JSON)
    -------------------
    owner_user_id : str (required, max 36)
        Platform user ID that will own the created leads.
    records : list[dict] (required, min 1)
        List of raw foreclosure record dicts.

    Returns
    -------
    200 with serialized ImportJob.
    400 on validation failure.
    """
    data = request.get_json(silent=True) or {}
    validated = _validate_ingestion_body(data)

    owner_user_id = validated['owner_user_id']
    records = validated['records']

    service = _build_service()
    job = service.ingest_foreclosure(records, owner_user_id)

    return jsonify(_serialize_import_job(job)), 200


@ingestion_bp.route('/long-owned', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def ingest_long_owned():
    """Ingest long-owned homeowner records.

    Request body (JSON)
    -------------------
    owner_user_id : str (required, max 36)
    records : list[dict] (required, min 1)

    Returns
    -------
    200 with serialized ImportJob.
    400 on validation failure.
    """
    data = request.get_json(silent=True) or {}
    validated = _validate_ingestion_body(data)

    owner_user_id = validated['owner_user_id']
    records = validated['records']

    service = _build_service()
    job = service.ingest_long_owned(records, owner_user_id)

    return jsonify(_serialize_import_job(job)), 200


@ingestion_bp.route('/absentee-owner', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def ingest_absentee_owner():
    """Ingest absentee owner records.

    Request body (JSON)
    -------------------
    owner_user_id : str (required, max 36)
    records : list[dict] (required, min 1)

    Returns
    -------
    200 with serialized ImportJob.
    400 on validation failure.
    """
    data = request.get_json(silent=True) or {}
    validated = _validate_ingestion_body(data)

    owner_user_id = validated['owner_user_id']
    records = validated['records']

    service = _build_service()
    job = service.ingest_absentee_owner(records, owner_user_id)

    return jsonify(_serialize_import_job(job)), 200


@ingestion_bp.route('/tax-distress', methods=['POST'])
@limiter.limit("10 per minute")
@handle_errors
def ingest_tax_distress():
    """Ingest tax distress records.

    Request body (JSON)
    -------------------
    owner_user_id : str (required, max 36)
    records : list[dict] (required, min 1)

    Returns
    -------
    200 with serialized ImportJob.
    400 on validation failure.
    """
    data = request.get_json(silent=True) or {}
    validated = _validate_ingestion_body(data)

    owner_user_id = validated['owner_user_id']
    records = validated['records']

    service = _build_service()
    job = service.ingest_tax_distress(records, owner_user_id)

    return jsonify(_serialize_import_job(job)), 200


# ---------------------------------------------------------------------------
# POST /csv — CSV upload endpoint (Requirements 6.1, 6.3, 6.8, 6.9)
# ---------------------------------------------------------------------------

@ingestion_bp.route('/csv', methods=['POST'])
@limiter.limit("5 per minute")
@handle_errors
def upload_csv():
    """CSV upload endpoint — sync for ≤500 rows, async for >500 rows.

    Query params: owner_user_id (required, max 36)
    Form data: file (multipart/form-data)

    Returns
    -------
    200 with {rows_processed, leads_created, leads_updated, rows_skipped} for ≤500 rows.
    202 with {import_job_id} for >500 rows.
    400 on validation failure, missing file, or file > 10 MB.
    """
    from app.schemas import CSVUploadQuerySchema

    # Validate owner_user_id query param (Req 6.8)
    schema = CSVUploadQuerySchema()
    query_data = schema.load(request.args.to_dict())
    owner_user_id = query_data['owner_user_id']

    # Check file presence
    if 'file' not in request.files:
        return jsonify({'error': {'message': 'No file provided'}}), 400

    file = request.files['file']

    # Reject files > 10 MB before any parsing (Req 6.3)
    file.seek(0, 2)  # seek to end
    size = file.tell()
    file.seek(0)     # seek back to beginning
    if size > 10 * 1024 * 1024:
        return jsonify({'error': {'message': 'File size exceeds 10 MB limit'}}), 400

    # Decode file content
    import csv as csv_mod
    import io
    import tempfile
    import os

    try:
        content = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify({'error': {'message': 'File encoding error — must be UTF-8'}}), 400

    # Stream first 501 rows to determine sync vs async path (Req 6.8, 6.9)
    reader = csv_mod.DictReader(io.StringIO(content))
    rows = []
    for i, row in enumerate(reader):
        rows.append(row)
        if i >= 500:
            break

    row_count = len(rows)

    if row_count <= 500:
        # Sync path: write temp file, call process_csv inline (Req 6.8)
        fd, tmp_path = tempfile.mkstemp(suffix='.csv')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(content)

            service = _build_service()
            job = service._create_import_job(owner_user_id, 'manual_distress')
            db.session.commit()
            job = service.process_csv(job.id, tmp_path, owner_user_id)

            return jsonify({
                'rows_processed': job.rows_processed,
                'leads_created': job.rows_imported,
                'leads_updated': 0,
                'rows_skipped': job.rows_skipped,
            }), 200
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    else:
        # Async path: write temp file, enqueue Celery task, return 202 (Req 6.9)
        fd, tmp_path = tempfile.mkstemp(suffix='.csv')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(content)

            service = _build_service()
            job = service._create_import_job(owner_user_id, 'manual_distress')
            db.session.commit()

            try:
                from celery_worker import process_csv_ingestion
                process_csv_ingestion.delay(job.id, tmp_path, owner_user_id)
            except ImportError:
                logger.warning(
                    "celery_worker.process_csv_ingestion not yet available; "
                    "async CSV job %s created but not enqueued",
                    job.id,
                )

            return jsonify({'import_job_id': job.id}), 202
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# GET job status endpoint (Requirement 9.6)
# ---------------------------------------------------------------------------

@ingestion_bp.route('/jobs/<int:job_id>', methods=['GET'])
@limiter.limit("60 per minute")
@handle_errors
def get_import_job(job_id: int):
    """Return ImportJob status for polling.

    Returns at minimum: id, status, source_type, rows_processed,
    rows_imported, rows_skipped, error_log, created_at, completed_at.

    Returns
    -------
    200 with serialized ImportJob.
    404 if job not found.
    """
    from app.models.import_job import ImportJob

    job = db.session.get(ImportJob, job_id)
    if not job:
        return jsonify({
            'error': {
                'message': f'Import job {job_id} not found',
            }
        }), 404

    return jsonify(_serialize_import_job(job)), 200
