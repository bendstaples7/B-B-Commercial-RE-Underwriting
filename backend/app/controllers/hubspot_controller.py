"""HubSpot CRM Migration API endpoints.

Provides configuration management, import orchestration, SSE progress
streaming, backup export, and review-queue management for the HubSpot CRM
migration feature.  All routes are protected by the ``@handle_errors``
decorator for consistent JSON error responses.

URL prefix: /api/hubspot  (registered in app/__init__.py)
"""
import glob
import json
import logging
import os
import time
from functools import wraps

from flask import Blueprint, Response, jsonify, request, stream_with_context
from marshmallow import ValidationError

from app.api_utils import get_current_user_id
from app.exceptions import (
    ImportRunNotFoundError,
    MatchNotFoundError,
    RealEstateAnalysisException,
    ResourceNotFoundError,
)
from app.schemas import (
    HubSpotConfigSchema,
    HubSpotImportRunSchema,
    HubSpotMatchSchema,
    WebhookLogSchema,
    WebhookLogSummarySchema,
)
from app.services.hubspot_import_service import HubSpotImportService
from app.services import HubSpotWebhookService

logger = logging.getLogger(__name__)

hubspot_bp = Blueprint('hubspot', __name__)

_import_service = HubSpotImportService()
_config_schema = HubSpotConfigSchema()
_run_schema = HubSpotImportRunSchema()
_match_schema = HubSpotMatchSchema()
_webhook_log_schema = WebhookLogSchema()
_webhook_log_summary_schema = WebhookLogSummarySchema()

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100

# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------


def handle_errors(f):
    """Decorator for consistent JSON error handling on all HubSpot routes."""
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
        except (ImportRunNotFoundError, MatchNotFoundError, ResourceNotFoundError) as e:
            logger.warning("Resource not found: %s", e.message)
            return jsonify({
                'error': 'Not found',
                'message': e.message,
                **e.payload,
            }), e.status_code
        except RealEstateAnalysisException as e:
            logger.warning("Application error (%d): %s", e.status_code, e.message)
            return jsonify({
                'error': 'Application error',
                'message': e.message,
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
# Helpers
# ---------------------------------------------------------------------------

def _parse_pagination(args):
    """Extract and validate pagination parameters from query string."""
    try:
        page = int(args.get('page', DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        per_page = int(args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE

    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------

@hubspot_bp.route('/config', methods=['GET'])
@handle_errors
def get_config():
    """Return the current HubSpot configuration with the token masked.

    Returns 200 with ``{portal_id, account_name, configured_at, has_client_secret}``
    when a config exists, or 200 with ``{configured: false}`` when none has been
    saved yet.  The raw or encrypted client secret is NEVER returned.
    """
    config = _import_service.get_config()
    if config is None:
        return jsonify({'configured': False}), 200

    data = _config_schema.dump(config)
    data['has_client_secret'] = config.encrypted_client_secret is not None
    return jsonify(data), 200


@hubspot_bp.route('/config', methods=['POST'])
@handle_errors
def save_config():
    """Save or update the HubSpot API token, portal ID, and optional client secret.

    Request body
    ------------
    token : str (optional) — raw HubSpot private-app token (required unless updating client_secret only)
    portal_id : str (optional) — HubSpot portal ID
    client_secret : str (optional) — HubSpot client secret for webhook signature
        verification.  Fernet-encrypted before storage; never returned in responses.

    When only ``client_secret`` is provided (no ``token``), the existing config
    is loaded and only the client secret is updated.
    """
    from app.models.hubspot_config import HubSpotConfig
    from app import db
    from app.services.hubspot_client_service import HubSpotClientService

    data = request.json or {}
    token = data.get('token')
    portal_id = data.get('portal_id')
    client_secret = data.get('client_secret')

    if token:
        # Full config save with token
        config = _import_service.save_config(token=token, portal_id=portal_id)
    elif client_secret:
        # Client-secret-only update — load existing config
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            return jsonify({'error': 'Validation error', 'message': 'No HubSpot configuration found. Save a token first.'}), 400
    else:
        return jsonify({'error': 'Validation error', 'message': 'token or client_secret is required'}), 400

    if client_secret:
        config.encrypted_client_secret = HubSpotClientService.encrypt_token(client_secret)
        db.session.commit()

    result = _config_schema.dump(config)
    result['has_client_secret'] = config.encrypted_client_secret is not None
    return jsonify(result), 200


@hubspot_bp.route('/config/test', methods=['POST'])
@handle_errors
def test_config():
    """Test the stored HubSpot connection.

    Calls ``/account-info/v3/details`` using the stored encrypted token and
    returns the result.

    Returns
    -------
    ``{success: true, account_name, portal_id}`` on success.
    ``{success: false, error}`` on failure.
    """
    from app.models.hubspot_config import HubSpotConfig
    from app import db
    from app.services.hubspot_client_service import HubSpotClientService

    config = db.session.query(HubSpotConfig).order_by(HubSpotConfig.id.desc()).first()
    if config is None:
        return jsonify({'success': False, 'error': 'No HubSpot configuration found'}), 200

    client = HubSpotClientService(config)
    result = client.test_connection()
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Import routes
# ---------------------------------------------------------------------------

@hubspot_bp.route('/import/trigger', methods=['POST'])
@handle_errors
def trigger_import():
    """Start a HubSpot import run.

    Request body
    ------------
    object_types : list[str] (optional) — subset of
        ['deals', 'contacts', 'companies', 'engagements'].
        Defaults to all four when omitted.

    Returns 202 Accepted with ``{run_ids: [...], status: "running"}``.
    """
    data = request.json or {}
    object_types = data.get('object_types')  # None → service uses defaults

    runs = _import_service.start_import(object_types=object_types)
    run_ids = [r.id for r in runs]

    return jsonify({'run_ids': run_ids, 'status': 'running'}), 202


@hubspot_bp.route('/pipeline/run', methods=['POST'])
@handle_errors
def run_pipeline_now():
    """Manually trigger the post-import pipeline (matching → enrich → rescore).

    Use this when imports have completed but the pipeline did not run
    (e.g. Redis was unavailable when the import was triggered).

    Returns 202 Accepted immediately. Uses Celery when available; falls back
    to a detached subprocess when Celery is down.
    """
    from flask import current_app  # noqa: PLC0415
    from app.services.hubspot_pipeline_runner import dispatch_post_import_pipeline  # noqa: PLC0415

    app = current_app._get_current_object()
    mode = dispatch_post_import_pipeline(app, run_ids=None)
    logger.info("Manually triggered post-import pipeline via /pipeline/run (mode=%s)", mode)
    message = (
        'Post-import pipeline queued via Celery'
        if mode == 'celery'
        else 'Post-import pipeline started in detached subprocess (Celery unavailable)'
    )
    return jsonify({'status': 'queued', 'mode': mode, 'message': message}), 202


@hubspot_bp.route('/import/runs', methods=['GET'])
@handle_errors
def list_import_runs():
    """List all import runs, newest first (paginated).

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 20, max 100)
    """
    page, per_page = _parse_pagination(request.args)
    runs, total = _import_service.list_runs(page=page, per_page=per_page)

    return jsonify({
        'runs': [_run_schema.dump(r) for r in runs],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
    }), 200


@hubspot_bp.route('/import/runs/<int:run_id>', methods=['GET'])
@handle_errors
def get_import_run(run_id):
    """Get a single import run by ID.

    Parameters
    ----------
    run_id : int
    """
    run = _import_service.get_run_status(run_id)
    return jsonify(_run_schema.dump(run)), 200


@hubspot_bp.route('/import/<int:run_id>/progress', methods=['GET'])
@handle_errors
def import_progress_stream(run_id):
    """SSE stream of import progress for a single run.

    Polls the run status every 2 seconds and yields Server-Sent Events until
    the run reaches a terminal state (success, partial, or failed).

    Each event has the form::

        data: {"status": "...", "total_fetched": N, "created_count": N,
               "updated_count": N, "error_count": N}\\n\\n

    The stream closes automatically when the run is no longer ``running``.
    """
    def generate():
        from app.models.hubspot_import_run import HubSpotImportRun
        from app import db

        while True:
            # Re-query inside the generator so we always get fresh data.
            run = db.session.get(HubSpotImportRun, run_id)
            if run is None:
                payload = json.dumps({'error': f'Run {run_id} not found'})
                yield f"data: {payload}\n\n"
                break

            event_data = json.dumps({
                'status': run.status,
                'total_fetched': run.total_fetched,
                'created_count': run.created_count,
                'updated_count': run.updated_count,
                'error_count': run.error_count,
            })
            yield f"data: {event_data}\n\n"

            if run.status != 'running':
                break

            time.sleep(2)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


# ---------------------------------------------------------------------------
# Export / backup routes
# ---------------------------------------------------------------------------

@hubspot_bp.route('/pipeline/status', methods=['GET'])
@handle_errors
def get_pipeline_status():
    """Return the current status of the post-import pipeline.

    Checks whether the ``hubspot.post_import_pipeline`` task is active in
    Celery, and returns counts of matches, interactions, tasks, and signals
    so the UI can show live progress.

    Returns::

        {
          "pipeline_running": bool,
          "matches": {"total": int, "high": int, "medium": int, "unmatched": int},
          "interactions": int,
          "tasks": int,
          "signals": int
        }
    """
    from app.models import HubSpotMatch, Interaction, Task
    from app.models.hubspot_signal import HubSpotSignal
    from sqlalchemy import func

    # Check if pipeline task is active in Celery
    pipeline_running = False
    try:
        from celery import current_app as celery_app
        inspect = celery_app.control.inspect(timeout=1.0)
        active = inspect.active() or {}
        for worker_tasks in active.values():
            for t in worker_tasks:
                if t.get('name') == 'hubspot.post_import_pipeline':
                    pipeline_running = True
                    break
    except Exception:
        pass  # If Celery inspect fails, just report not running

    # Match counts by confidence
    match_rows = (
        HubSpotMatch.query
        .with_entities(HubSpotMatch.confidence, func.count())
        .group_by(HubSpotMatch.confidence)
        .all()
    )
    match_counts = {row[0]: row[1] for row in match_rows}

    return jsonify({
        'pipeline_running': pipeline_running,
        'matches': {
            'total': HubSpotMatch.query.count(),
            'high': match_counts.get('HIGH', 0),
            'medium': match_counts.get('MEDIUM', 0),
            'unmatched': match_counts.get('UNMATCHED', 0),
        },
        'interactions': Interaction.query.filter_by(source='hubspot_import').count(),
        'tasks': Task.query.filter_by(source='hubspot_import').count(),
        'signals': HubSpotSignal.query.count(),
    }), 200


@hubspot_bp.route('/export/backup', methods=['POST'])
@handle_errors
def trigger_backup_export():
    """Dispatch the ``generate_backup_export`` Celery task.

    Returns ``{task_id}`` so the client can poll task status if needed.
    """
    from celery import current_app as celery_app

    result = celery_app.send_task('hubspot.generate_backup_export')
    return jsonify({'task_id': result.id}), 202


@hubspot_bp.route('/export/backup/download', methods=['GET'])
@handle_errors
def download_backup_export():
    """Download the most recent HubSpot backup export file.

    Searches ``/tmp`` for files matching ``hubspot_backup_*.json`` and
    returns the most recently modified one as a JSON file download.

    Returns 404 if no backup file exists yet.
    """
    pattern = '/tmp/hubspot_backup_*.json'
    matches = glob.glob(pattern)

    if not matches:
        return jsonify({'error': 'No backup file found. Run a backup export first.'}), 404

    # Pick the most recently modified file
    latest_file = max(matches, key=os.path.getmtime)
    filename = os.path.basename(latest_file)

    try:
        with open(latest_file, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except OSError as exc:
        logger.error("Failed to read backup file %s: %s", latest_file, exc)
        return jsonify({'error': 'Failed to read backup file'}), 500

    return Response(
        content,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# Review queue routes
# ---------------------------------------------------------------------------

@hubspot_bp.route('/review-queue', methods=['GET'])
@handle_errors
def list_review_queue():
    """List HubSpot match records pending human review.

    Returns matches with confidence MEDIUM, LOW, or UNMATCHED and
    status=pending.  Supports optional filtering by record type and
    confidence level.

    Query parameters
    ----------------
    type : str (optional) — filter by hubspot_record_type (deal/contact/company)
    confidence : str (optional) — filter by confidence (MEDIUM/LOW/UNMATCHED)
    page : int (default 1)
    per_page : int (default 20, max 100)
    """
    from app.models.hubspot_match import HubSpotMatch
    from app.models import HubSpotDeal, HubSpotContact, HubSpotCompany
    from app import db

    page, per_page = _parse_pagination(request.args)
    record_type = request.args.get('type')
    confidence_filter = request.args.get('confidence')

    query = db.session.query(HubSpotMatch).filter(
        HubSpotMatch.confidence.in_(['MEDIUM', 'LOW', 'UNMATCHED']),
        HubSpotMatch.status == 'pending',
    )

    if record_type:
        query = query.filter(HubSpotMatch.hubspot_record_type == record_type)
    if confidence_filter:
        query = query.filter(HubSpotMatch.confidence == confidence_filter)

    total = query.count()
    items = (
        query
        .order_by(HubSpotMatch.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Pending count across all filters (for badge display)
    pending_count = db.session.query(HubSpotMatch).filter(
        HubSpotMatch.confidence.in_(['MEDIUM', 'LOW', 'UNMATCHED']),
        HubSpotMatch.status == 'pending',
    ).count()

    def _get_display_name(match):
        """Extract a human-readable display name from the raw HubSpot record."""
        props = {}
        try:
            if match.hubspot_record_type == 'deal':
                rec = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
                if rec:
                    props = rec.raw_payload.get('properties', {})
                    return props.get('dealname') or props.get('address') or None
            elif match.hubspot_record_type == 'contact':
                rec = HubSpotContact.query.filter_by(hubspot_id=match.hubspot_id).first()
                if rec:
                    props = rec.raw_payload.get('properties', {})
                    first = props.get('firstname') or ''
                    last = props.get('lastname') or ''
                    name = f"{first} {last}".strip()
                    return name or props.get('email') or None
            elif match.hubspot_record_type == 'company':
                rec = HubSpotCompany.query.filter_by(hubspot_id=match.hubspot_id).first()
                if rec:
                    props = rec.raw_payload.get('properties', {})
                    return props.get('name') or None
        except Exception:
            pass
        return None

    def _get_internal_display_name(match):
        """Extract the name of the proposed internal record."""
        try:
            if match.internal_record_type == 'organization' and match.internal_record_id:
                from app.models import Organization
                org = Organization.query.get(match.internal_record_id)
                if org:
                    return org.name
            elif match.internal_record_type == 'lead' and match.internal_record_id:
                from app.models import Lead
                lead = Lead.query.get(match.internal_record_id)
                if lead:
                    parts = [lead.property_street, lead.property_city, lead.property_state]
                    return ', '.join(p for p in parts if p) or None
        except Exception:
            pass
        return None

    def _serialize_match(m):
        data = _match_schema.dump(m)
        data['display_name'] = _get_display_name(m)
        data['internal_display_name'] = _get_internal_display_name(m)
        return data

    return jsonify({
        'matches': [_serialize_match(m) for m in items],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'pending_count': pending_count,
    }), 200


@hubspot_bp.route('/review-queue/<int:match_id>/confirm', methods=['POST'])
@handle_errors
def confirm_match(match_id):
    """Confirm a HubSpot match, optionally overriding the internal record.

    Sets ``status=confirmed`` on the ``HubSpotMatch`` record.  If
    ``internal_record_id`` is provided in the request body, it is applied
    to the match before confirming.

    Request body
    ------------
    internal_record_id : int (optional) — override the matched internal record
    """
    from app.models.hubspot_match import HubSpotMatch
    from app import db

    match = db.session.get(HubSpotMatch, match_id)
    if match is None:
        raise MatchNotFoundError(
            f"HubSpotMatch id={match_id} not found.",
            payload={'match_id': match_id},
        )

    data = request.json or {}
    internal_record_id = data.get('internal_record_id')
    if internal_record_id is not None:
        match.internal_record_id = internal_record_id

    match.status = 'confirmed'
    db.session.commit()

    return jsonify({'success': True, 'match': _match_schema.dump(match)}), 200


@hubspot_bp.route('/review-queue/<int:match_id>/reject', methods=['POST'])
@handle_errors
def reject_match(match_id):
    """Reject a HubSpot match and optionally re-link to a different record.

    Sets ``status=rejected`` on the ``HubSpotMatch`` record.

    Request body
    ------------
    internal_record_id : int (optional) — the correct internal record to link
    """
    from app.models.hubspot_match import HubSpotMatch
    from app import db

    match = db.session.get(HubSpotMatch, match_id)
    if match is None:
        raise MatchNotFoundError(
            f"HubSpotMatch id={match_id} not found.",
            payload={'match_id': match_id},
        )

    data = request.json or {}
    internal_record_id = data.get('internal_record_id')
    if internal_record_id is not None:
        match.internal_record_id = internal_record_id

    match.status = 'rejected'
    db.session.commit()

    return jsonify({'success': True, 'match': _match_schema.dump(match)}), 200


@hubspot_bp.route('/review-queue/<int:match_id>/new-record', methods=['POST'])
@handle_errors
def mark_match_as_new_record(match_id):
    """Mark a HubSpot match as confirmed with no existing internal record.

    Sets ``status=confirmed`` and clears ``internal_record_id`` to indicate
    that this HubSpot record should create a new internal record rather than
    linking to an existing one.
    """
    from app.models.hubspot_match import HubSpotMatch
    from app import db

    match = db.session.get(HubSpotMatch, match_id)
    if match is None:
        raise MatchNotFoundError(
            f"HubSpotMatch id={match_id} not found.",
            payload={'match_id': match_id},
        )

    match.status = 'confirmed'
    match.internal_record_id = None
    db.session.commit()

    return jsonify({'success': True, 'match': _match_schema.dump(match)}), 200


# ---------------------------------------------------------------------------
# Webhook log routes
# ---------------------------------------------------------------------------

@hubspot_bp.route('/webhook-log', methods=['GET'])
@handle_errors
def list_webhook_logs():
    """List recent HubSpot webhook log entries (paginated).

    Query parameters
    ----------------
    page : int (default 1)
    per_page : int (default 20, max 100)
    status : str (optional) — filter by status
        (pending/processing/processed/failed/deduplicated/loop_suppressed)
    object_type : str (optional) — filter by hubspot_object_type

    Returns
    -------
    ``{logs: [...], total, page, per_page, pages}``
    """
    from app.models import HubSpotWebhookLog
    from app import db

    page, per_page = _parse_pagination(request.args)
    status_filter = request.args.get('status')
    object_type_filter = request.args.get('object_type')

    query = db.session.query(HubSpotWebhookLog)

    if status_filter:
        query = query.filter(HubSpotWebhookLog.status == status_filter)
    if object_type_filter:
        query = query.filter(HubSpotWebhookLog.hubspot_object_type == object_type_filter)

    total = query.count()
    logs = (
        query
        .order_by(HubSpotWebhookLog.received_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return jsonify({
        'logs': [_webhook_log_schema.dump(log) for log in logs],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
    }), 200


@hubspot_bp.route('/webhook-log/summary', methods=['GET'])
@handle_errors
def get_webhook_log_summary():
    """Return a 24-hour summary of webhook log statuses.

    Returns
    -------
    ``{processed_count, failed_count, deduplicated_count, last_synced_at}``
    """
    summary = HubSpotWebhookService().get_log_summary()
    return jsonify(_webhook_log_summary_schema.dump(summary)), 200


@hubspot_bp.route('/webhook-log/<int:log_id>/retry', methods=['POST'])
@handle_errors
def retry_webhook_log(log_id):
    """Manually retry a failed webhook log entry.

    Re-dispatches the Celery task for the given log entry.  The log must
    be in ``failed`` status; otherwise a 400 is returned.

    Parameters
    ----------
    log_id : int — primary key of the ``HubSpotWebhookLog`` to retry

    Returns
    -------
    ``{success: true}`` on success.
    404 if the log is not found.
    400 if the log is not in ``failed`` status.
    """
    try:
        HubSpotWebhookService().retry_failed_event(log_id)
    except ValueError as exc:
        msg = str(exc)
        if 'not found' in msg.lower():
            return jsonify({'error': 'Not found', 'message': msg}), 404
        # "expected 'failed'" or similar status mismatch
        return jsonify({'error': 'Invalid request', 'message': msg}), 400

    return jsonify({'success': True}), 200
