"""API routes."""
from flask import jsonify, request
from marshmallow import ValidationError
from functools import wraps
from app.controllers import api_bp
from app.controllers.workflow_controller import WorkflowController
from app.models.analysis_session import WorkflowStep
from app.models.user import User
from app.models.lead import Lead
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
    """Decorator for consistent error handling.

    RealEstateAnalysisException subclasses (e.g. GeminiAPIError) are re-raised
    so Flask's registered error handler (handle_real_estate_exception) can
    return the correct status code and structured payload.  All other exceptions
    are caught here and returned as generic 500 responses.
    """
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
            from app.exceptions import RealEstateAnalysisException
            # Let domain exceptions propagate to Flask's registered error handler
            # so they return the correct status code and structured payload.
            if isinstance(e, RealEstateAnalysisException):
                raise

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
                'message': 'An unexpected error occurred',
            }), 500
    return decorated_function


def resolve_deploy_sha(app_dir=None):
    """Return the deployed git SHA for CI/CD verification.

    Resolution order:
      1. DEPLOY_SHA file (written by deploy.sh on the VPS)
      2. Parse APP_DIR/.git/HEAD (no subprocess; works under systemd)
      3. git rev-parse via absolute binary paths
    """
    import os
    import subprocess
    from pathlib import Path

    app_path = Path(app_dir or os.environ.get('DEPLOY_APP_DIR', '/home/deploy/app'))

    deploy_sha_file = app_path / 'DEPLOY_SHA'
    if deploy_sha_file.is_file():
        sha = deploy_sha_file.read_text(encoding='utf-8').strip()
        if sha:
            return sha

    git_head = app_path / '.git' / 'HEAD'
    if git_head.is_file():
        head = git_head.read_text(encoding='utf-8').strip()
        if head.startswith('ref: '):
            ref_path = app_path / '.git' / head[5:]
            if ref_path.is_file():
                sha = ref_path.read_text(encoding='utf-8').strip()
                if sha:
                    return sha
        elif len(head) >= 40:
            return head[:40]

    for git_bin in ('/usr/bin/git', '/usr/local/bin/git', 'git'):
        try:
            sha = subprocess.check_output(
                [git_bin, 'rev-parse', 'HEAD'],
                cwd=str(app_path),
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            if sha:
                return sha
        except Exception:
            continue

    return 'unknown'


@api_bp.route('/version', methods=['GET'])
def version():
    """Returns the currently deployed git SHA.

    Used by the CI/CD post-deploy smoke test to verify the correct
    version of the code is running after a deployment.
    """
    return jsonify({'sha': resolve_deploy_sha()}), 200


@api_bp.route('/health/runtime', methods=['GET'])
def health_runtime():
    """Lightweight process-identity probe for the frontend restart guard.

    Deliberately cheap (no DB / Alembic / Celery / queue checks) so tabs can
    poll it frequently. Returns identity only outside production.
    Spawn-restart is loopback-only so LAN clients cannot kill the process.
    """
    from flask import request
    from app.runtime_identity import get_runtime_identity, is_loopback_restart_caller

    allow_restart = is_loopback_restart_caller(request.remote_addr)
    payload = {'status': 'ok'}
    payload.update(get_runtime_identity(allow_restart=allow_restart))
    return jsonify(payload), 200


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint — verifies DB connectivity, migration state, and data integrity.

    Returns HTTP 200 with status='healthy' when all checks pass.
    Returns HTTP 503 with status='degraded' and a list of failing checks otherwise.

    Checks:
      1. DB connectivity — can we execute a simple query?
      2. Migration head — is alembic_version at the expected head revision?
      3. Unclassified leads — are there leads with recommended_action IS NULL?
         (indicates the Action Engine backfill hasn't run)
      4. Queue counts — do the 7 queue counts return without error?
      5. Lead visibility — can ben.d.staples.7@gmail.com see leads?
         (fails if the user or assigned leads are missing)
      6. Async stack — Redis reachable? Celery worker responding? (warn only)
      7. Open Letter / mail queue schema
      8. Enrichment catalog — required data_sources present after startup heal (FAIL if not)
         plus supporting-data invariant counts (WARN when no recent enrichment)
    """
    import os
    from app import db

    checks = {}
    degraded = False

    # ------------------------------------------------------------------
    # Check 1: DB connectivity
    # ------------------------------------------------------------------
    try:
        db.session.execute(db.text('SELECT 1'))
        checks['db_connectivity'] = 'ok'
    except Exception as e:
        checks['db_connectivity'] = f'FAIL: {e}'
        degraded = True

    # ------------------------------------------------------------------
    # Check 2: Migration head
    # ------------------------------------------------------------------
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        alembic_cfg = Config(
            os.path.join(os.path.dirname(__file__), '..', '..', 'alembic_migrations', 'alembic.ini')
        )
        alembic_cfg.set_main_option(
            'script_location',
            os.path.join(os.path.dirname(__file__), '..', '..', 'alembic_migrations'),
        )
        script = ScriptDirectory.from_config(alembic_cfg)
        expected_heads = {s.revision for s in script.get_revisions('heads')}

        with db.engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_heads = set(ctx.get_current_heads())

        if current_heads == expected_heads:
            checks['migration_head'] = f'ok ({", ".join(current_heads)})'
        else:
            checks['migration_head'] = (
                f'FAIL: DB at {current_heads}, expected {expected_heads}. '
                f'Run: flask db upgrade head'
            )
            degraded = True
    except Exception as e:
        checks['migration_head'] = f'FAIL: {e}'
        degraded = True

    # ------------------------------------------------------------------
    # Check 3: Unclassified leads
    # ------------------------------------------------------------------
    try:
        unclassified = db.session.execute(
            db.text('SELECT COUNT(*) FROM leads WHERE recommended_action IS NULL')
        ).scalar()
        if unclassified == 0:
            checks['action_engine'] = 'ok (all leads classified)'
        else:
            checks['action_engine'] = (
                f'WARN: {unclassified} leads have recommended_action=NULL. '
                f'Action Engine backfill may still be running.'
            )
            # Warn but don't degrade — backfill runs in background on startup
    except Exception as e:
        checks['action_engine'] = f'FAIL: {e}'
        degraded = True

    # ------------------------------------------------------------------
    # Check 4: Queue counts
    # ------------------------------------------------------------------
    try:
        from app.services.queue_service import QueueService
        counts = QueueService().get_counts()
        checks['queue_counts'] = f'ok ({counts})'
    except Exception as e:
        checks['queue_counts'] = f'FAIL: {e}'
        degraded = True

    # ------------------------------------------------------------------
    # Check 5: Lead visibility — optional env-gated user lead check
    # ------------------------------------------------------------------
    try:
        lead_user_email = os.environ.get('HEALTH_CHECK_LEAD_USER_EMAIL', '').strip()
        if not lead_user_email:
            checks['lead_visibility'] = 'skipped (set HEALTH_CHECK_LEAD_USER_EMAIL to enable)'
        else:
            user = User.query.filter_by(email_lower=lead_user_email.lower()).first()
            if user is None:
                checks['lead_visibility'] = (
                    f'WARN: user {lead_user_email} not found — '
                    f'migration w2x3y4z5a6b7 may not have run'
                )
            else:
                lead_count = Lead.query.filter(
                    Lead.owner_user_id == user.user_id
                ).count()
                if lead_count == 0:
                    checks['lead_visibility'] = (
                        f'FAIL: {lead_count} leads for {lead_user_email} '
                        f'(user_id={user.user_id}). Leads with owner_user_id IS NULL '
                        f'are invisible to non-admin users.'
                    )
                    degraded = True
                else:
                    checks['lead_visibility'] = (
                        f'ok ({lead_count} leads visible for {lead_user_email})'
                    )
    except Exception as e:
        checks['lead_visibility'] = f'FAIL: {e}'
        degraded = True

    # ------------------------------------------------------------------
    # Check 6: Async stack (Redis + Celery worker) — warn only
    # ------------------------------------------------------------------
    try:
        import redis as redis_lib

        redis_url = os.environ.get('REDIS_URL') or os.environ.get('CELERY_BROKER_URL', '')
        if redis_url:
            redis_lib.from_url(
                redis_url, socket_connect_timeout=1, socket_timeout=1,
            ).ping()
            checks['redis'] = 'ok'
        else:
            checks['redis'] = 'WARN: REDIS_URL not configured'
    except Exception as e:
        checks['redis'] = f'WARN: Redis unreachable ({e})'

    try:
        from celery import current_app as celery_app  # noqa: PLC0415

        inspect = celery_app.control.inspect(timeout=1.0)
        ping = inspect.ping() if inspect else None
        if ping:
            checks['celery_worker'] = f'ok ({len(ping)} worker(s))'
        else:
            checks['celery_worker'] = (
                'WARN: no Celery workers responding — HubSpot imports and '
                'scheduled sync will not run until Celery is started'
            )
    except Exception as e:
        checks['celery_worker'] = f'WARN: Celery check failed ({e})'

    # ------------------------------------------------------------------
    # Check 7: Open Letter / mail queue schema
    # ------------------------------------------------------------------
    try:
        db.session.execute(db.text('SELECT 1 FROM mail_queue_items LIMIT 0'))
        db.session.execute(db.text('SELECT 1 FROM open_letter_config LIMIT 0'))
        checks['open_letter_schema'] = 'ok'
    except Exception as e:
        checks['open_letter_schema'] = (
            f'FAIL: mail_queue_items or open_letter_config missing ({e}). '
            f'Run: flask db upgrade head'
        )
        degraded = True

    olc_token = os.environ.get('OPEN_LETTER_API_TOKEN', '').strip()
    encryption_key = os.environ.get('HUBSPOT_ENCRYPTION_KEY', '').strip()
    if olc_token and not encryption_key:
        checks['open_letter_encryption'] = (
            'FAIL: OPEN_LETTER_API_TOKEN is set but HUBSPOT_ENCRYPTION_KEY is missing'
        )
        degraded = True
    elif olc_token:
        checks['open_letter_encryption'] = 'ok'
    else:
        checks['open_letter_encryption'] = 'skipped (OPEN_LETTER_API_TOKEN not set)'

    # ------------------------------------------------------------------
    # Check 8: Enrichment catalog (Cook County / Chicago plugins)
    # ------------------------------------------------------------------
    try:
        from app.services.cook_county_enrichment_service import (
            check_enrichment_catalog_health,
        )
        # Startup owns catalog repair. Health probes must remain read-only.
        catalog = check_enrichment_catalog_health(heal=False)
        if catalog['ok']:
            checks['enrichment_catalog'] = (
                f"ok ({catalog['present_count']}/{catalog['required_count']} sources)"
            )
        else:
            checks['enrichment_catalog'] = (
                f"FAIL: missing data_sources after startup: {catalog['missing']}"
            )
            degraded = True
    except Exception as e:
        checks['enrichment_catalog'] = f'FAIL: {e}'
        degraded = True

    status = 'degraded' if degraded else 'healthy'
    http_status = 503 if degraded else 200
    from flask import current_app, request
    from app.runtime_identity import get_runtime_identity, is_loopback_restart_caller

    db_mode = current_app.config.get('DB_MODE', 'cloud')
    payload = {'status': status, 'checks': checks, 'db_mode': db_mode}
    allow_restart = is_loopback_restart_caller(request.remote_addr)
    payload.update(get_runtime_identity(allow_restart=allow_restart))
    return jsonify(payload), http_status


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

    # Read user identity from g (set by before_request hook)
    from app.api_utils import get_current_user_id
    user_id = get_current_user_id()

    # Start analysis
    result = workflow_controller.start_analysis(
        address=data['address'],
        user_id=user_id,
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
    )

    logger.info(f"Started analysis session {result['session_id']} for user {user_id}")
    
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
    
    # Step 2 (COMPARABLE_SEARCH) is always handled asynchronously via Celery.
    # The route enqueues the task and returns HTTP 202 immediately so the
    # frontend is never blocked by the ~2-minute comparable search duration.
    if target_step == WorkflowStep.COMPARABLE_SEARCH:
        from app.models import AnalysisSession
        from app import db
        from datetime import datetime

        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        # Enforce sequential step ordering
        if session.current_step.value + 1 != WorkflowStep.COMPARABLE_SEARCH.value:
            return jsonify({
                'error': 'Invalid request',
                'message': f'Cannot advance to COMPARABLE_SEARCH from {session.current_step.name}. Must advance sequentially.'
            }), 400

        # Validate step 1 is complete before accepting
        workflow_controller._validate_step_completion(session, WorkflowStep.PROPERTY_FACTS)

        # Short-circuit duplicate submissions — use an atomic UPDATE so that
        # concurrent requests cannot both pass the loading=False check.
        # UPDATE returns the number of rows modified; 0 means loading was
        # already True (another request got there first).
        from sqlalchemy import update as _sa_update
        rows_updated = db.session.execute(
            _sa_update(AnalysisSession)
            .where(
                AnalysisSession.session_id == session_id,
                AnalysisSession.loading == False,  # noqa: E712
            )
            .values(loading=True, updated_at=datetime.utcnow())
        ).rowcount
        db.session.commit()

        if rows_updated == 0:
            # Either session.loading was already True (duplicate) or session
            # disappeared between the earlier query and this update.
            # Re-fetch to distinguish the two cases.
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            if not session:
                return jsonify({'error': 'Session not found'}), 404
            return jsonify({
                'error': 'Conflict',
                'message': 'Comparable search is already in progress for this session.',
            }), 409

        # Enqueue the Celery task; revert loading on failure.
        try:
            from celery_worker import run_comparable_search_task
            run_comparable_search_task.delay(session_id)
            logger.info(f"Enqueued comparable search for session {session_id}")
        except Exception as e:
            logger.warning(f"Celery unavailable, reverting loading state: {e}")
            db.session.execute(
                _sa_update(AnalysisSession)
                .where(AnalysisSession.session_id == session_id)
                .values(loading=False, updated_at=datetime.utcnow())
            )
            db.session.commit()
            return jsonify({
                'error': 'Service unavailable',
                'message': 'Comparable search queue is unavailable. Please try again.',
            }), 503

        return jsonify({'status': 'accepted', 'session_id': session_id}), 202

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
