"""Flask application factory."""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
import os

db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    # No global default — limits are applied explicitly per route category.
    # This prevents legitimate high-frequency reads (SSE, status checks, dashboards)
    # from being throttled while still protecting expensive write/AI endpoints.
    default_limits=[],
)

def create_app(config_name='development'):
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    # Load configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://localhost/real_estate_analysis')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    app.config['REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

    # Limit the SQLAlchemy connection pool to prevent exhausting PostgreSQL's
    # max_connections when multiple processes start simultaneously (Flask +
    # Celery worker threads + Celery Beat). Each process gets at most 3
    # connections (pool_size=3, max_overflow=0 = hard cap of 3).
    # With Flask (3) + 4 Celery threads (12) + Beat (3) = 18 total,
    # well under PostgreSQL's default limit of 100.
    # Tests use NullPool (no persistent connections) to avoid interference.
    if config_name == 'testing':
        from sqlalchemy.pool import NullPool
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}
    else:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 3,
            'max_overflow': 0,
            'pool_pre_ping': True,   # discard stale connections silently
            'pool_timeout': 30,      # wait up to 30s for a free connection
        }

    # Disable rate limiting in tests so performance tests can create many resources
    if config_name == 'testing':
        app.config['RATELIMIT_ENABLED'] = False
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory='alembic_migrations')
    CORS(app)
    limiter.init_app(app)

    # Auto-apply pending migrations in development only.
    # Uses FLASK_ENV if set, otherwise falls back to config_name.
    # Skip in Celery worker/beat processes — they share the same DB but
    # should not run migrations (Flask handles that on startup).
    effective_env = os.getenv('FLASK_ENV', config_name)
    _is_celery = os.getenv('CELERY_WORKER_RUNNING') == '1'
    if effective_env == 'development' and not _is_celery:
        with app.app_context():
            try:
                from flask_migrate import upgrade
                upgrade(directory='alembic_migrations')
            except Exception as e:
                app.logger.warning("Auto-migrate skipped: %s", e)
    
    # Configure logging
    from app.logging_config import setup_logging
    setup_logging(app)

    # ---------------------------------------------------------------------------
    # User identity — Option 1: centralise in g.user_id via before_request
    #
    # Every request sets g.user_id from the X-User-Id header.  Controllers
    # read g.user_id instead of parsing the header or request body themselves.
    # If the header is absent, g.user_id defaults to 'anonymous'.
    # ---------------------------------------------------------------------------
    from flask import g, request as _request

    @app.before_request
    def set_user_identity():
        """Populate g.user_id from the X-User-Id request header."""
        g.user_id = _request.headers.get('X-User-Id', 'anonymous')

    # Register error handlers
    from app.error_handlers import register_error_handlers
    register_error_handlers(app)
    
    # Register blueprints
    from app.controllers import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from app.controllers.property_controller import properties_bp, leads_legacy_bp
    app.register_blueprint(properties_bp, url_prefix='/api/properties')
    app.register_blueprint(leads_legacy_bp, url_prefix='/api/leads')
    
    from app.controllers.import_controller import import_bp
    app.register_blueprint(import_bp, url_prefix='/api/leads/import')
    
    from app.controllers.enrichment_controller import enrichment_bp
    app.register_blueprint(enrichment_bp, url_prefix='/api/leads')
    
    from app.controllers.marketing_controller import marketing_bp
    app.register_blueprint(marketing_bp, url_prefix='/api/leads/marketing')
    
    from app.controllers.condo_filter_controller import condo_filter_bp
    app.register_blueprint(condo_filter_bp, url_prefix='/api/condo-filter')
    
    from app.controllers.lead_score_controller import lead_score_bp
    app.register_blueprint(lead_score_bp, url_prefix='/api/lead-scores')

    # Multifamily underwriting blueprints
    from app.controllers.multifamily_deal_controller import multifamily_deal_bp
    app.register_blueprint(multifamily_deal_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_rent_roll_controller import multifamily_rent_roll_bp
    app.register_blueprint(multifamily_rent_roll_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_market_rent_controller import multifamily_market_rent_bp
    app.register_blueprint(multifamily_market_rent_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_sale_comp_controller import multifamily_sale_comp_bp
    app.register_blueprint(multifamily_sale_comp_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_rehab_controller import multifamily_rehab_bp
    app.register_blueprint(multifamily_rehab_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_lender_controller import multifamily_lender_bp
    app.register_blueprint(multifamily_lender_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_funding_controller import multifamily_funding_bp
    app.register_blueprint(multifamily_funding_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_pro_forma_controller import multifamily_pro_forma_bp
    app.register_blueprint(multifamily_pro_forma_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_dashboard_controller import multifamily_dashboard_bp
    app.register_blueprint(multifamily_dashboard_bp, url_prefix='/api/multifamily')
    
    from app.controllers.multifamily_import_export_controller import multifamily_import_export_bp
    app.register_blueprint(multifamily_import_export_bp, url_prefix='/api/multifamily')
    
    from app.tasks.multifamily_recompute import multifamily_admin_bp
    app.register_blueprint(multifamily_admin_bp, url_prefix='/api/multifamily')

    # Commercial OM PDF Intake
    from app.controllers.om_intake_controller import om_intake_bp
    app.register_blueprint(om_intake_bp, url_prefix='/api/om-intake')

    # HubSpot CRM — Organization, Interaction, Task, and Timeline blueprints
    from app.controllers.organization_controller import organization_bp
    app.register_blueprint(organization_bp, url_prefix='/api/organizations')

    from app.controllers.interaction_controller import interaction_bp, timeline_bp
    app.register_blueprint(interaction_bp, url_prefix='/api/interactions')
    app.register_blueprint(timeline_bp, url_prefix='')  # routes already carry full /api/... paths

    from app.controllers.task_controller import task_bp
    app.register_blueprint(task_bp, url_prefix='/api/tasks')

    # HubSpot CRM — import, config, review queue, and backup endpoints
    from app.controllers.hubspot_controller import hubspot_bp
    app.register_blueprint(hubspot_bp, url_prefix='/api/hubspot')

    # Contact management (CRUD + property-contact nested routes)
    from app.controllers.contact_controller import contacts_bp
    app.register_blueprint(contacts_bp, url_prefix='')

    # OpenAPI spec endpoint
    from app.openapi import openapi_bp
    app.register_blueprint(openapi_bp, url_prefix='/api')
    
    # ---------------------------------------------------------------------------
    # Startup cleanup — mark any import runs stuck in 'running' as 'failed'.
    # This happens when the server was restarted without a Celery worker running,
    # leaving runs permanently stuck. We mark them failed so the UI is accurate.
    # ---------------------------------------------------------------------------
    if config_name != 'testing':
        with app.app_context():
            try:
                from app.models.hubspot_import_run import HubSpotImportRun
                from app.models.hubspot_signal import HubSpotSignal
                from datetime import datetime, timedelta

                # Bulk mark overdue tasks — update any task with status='open'
                # and a past due_date to status='overdue'. This runs at startup
                # so the follow-up-overdue view is accurate immediately, without
                # waiting for individual tasks to be lazily read.
                from app.models.task import Task as _Task
                overdue_updated = _Task.query.filter(
                    _Task.status == 'open',
                    _Task.due_date.isnot(None),
                    _Task.due_date < datetime.utcnow(),
                ).update({'status': 'overdue'}, synchronize_session=False)
                if overdue_updated:
                    db.session.commit()
                    app.logger.info(
                        "Startup: marked %d task(s) as overdue.", overdue_updated
                    )

                # Any run still 'running' after 2 hours is orphaned
                cutoff = datetime.utcnow() - timedelta(hours=2)
                orphaned = HubSpotImportRun.query.filter(
                    HubSpotImportRun.status == 'running',
                    HubSpotImportRun.start_time < cutoff,
                ).all()
                if orphaned:
                    for run in orphaned:
                        run.status = 'failed'
                        run.end_time = datetime.utcnow()
                        run.error_message = (
                            'Worker not available — Celery was not running when this '
                            'import was triggered. No data was fetched. Re-trigger the '
                            'import with the Celery worker running (use python dev.py).'
                        )
                    db.session.commit()
                    app.logger.warning(
                        "Marked %d orphaned import run(s) as failed on startup.",
                        len(orphaned),
                    )

                # Option 2: startup recovery — log if imports completed but no signals exist.
                # The pipeline will run automatically on the next import trigger via the
                # background thread (Option 3). We don't spawn a thread here to avoid
                # interfering with Werkzeug's reloader on Windows.
                from datetime import timedelta
                recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                recent_completed = HubSpotImportRun.query.filter(
                    HubSpotImportRun.status.in_(['success', 'partial']),
                    HubSpotImportRun.end_time >= recent_cutoff,
                ).count()
                signal_count = HubSpotSignal.query.count()

                if recent_completed > 0 and signal_count == 0:
                    app.logger.warning(
                        "Startup check: %d recent completed import run(s) found but no signals exist. "
                        "Use 'Run Pipeline Now' in HubSpot Import to process signals.",
                        recent_completed,
                    )

                # Option 1: startup recovery — if interactions exist but no signals,
                # spawn a background thread to run signal extraction + rescore.
                # This recovers from the case where the pipeline ran activity conversion
                # but signal extraction never completed (e.g. server crash, Redis down).
                interaction_count = db.session.execute(
                    db.text("SELECT COUNT(*) FROM interactions WHERE source='hubspot_import'")
                ).scalar()

                # Orphaned association backfill — if task_associations is empty but
                # hubspot tasks exist, spawn a thread to backfill associations now that
                # matching has completed. Same for orphaned interactions.
                task_assoc_count = db.session.execute(
                    db.text("SELECT COUNT(*) FROM task_associations")
                ).scalar()
                orphaned_task_count = db.session.execute(
                    db.text(
                        "SELECT COUNT(*) FROM tasks WHERE source='hubspot_import' "
                        "AND NOT EXISTS (SELECT 1 FROM task_associations ta WHERE ta.task_id=tasks.id)"
                    )
                ).scalar()
                interaction_assoc_count = db.session.execute(
                    db.text(
                        "SELECT COUNT(*) FROM interaction_associations WHERE target_type='lead'"
                    )
                ).scalar()

                needs_assoc_backfill = (orphaned_task_count > 0 or
                                        (interaction_count > 0 and interaction_assoc_count == 0))

                if needs_assoc_backfill:
                    app.logger.warning(
                        "Startup recovery: %d orphaned tasks, %d interactions with 0 lead associations. "
                        "Spawning background thread to backfill associations.",
                        orphaned_task_count, interaction_count,
                    )
                    import threading as _threading

                    def _startup_assoc_backfill(flask_app):
                        """Backfill InteractionAssociation and TaskAssociation rows for orphaned records.

                        Builds an engagement→lead_id map via confirmed HubSpot deal matches,
                        then creates missing association rows for all orphaned interactions and tasks.
                        """
                        with flask_app.app_context():
                            try:
                                from app import db as _db
                                from app.models import Interaction, InteractionAssociation
                                from app.models.task import Task
                                from app.models.task_association import TaskAssociation
                                from app.models.hubspot_match import HubSpotMatch
                                from app.models.hubspot_engagement import HubSpotEngagement

                                # Build engagement_id → lead_id map via deal matches
                                engagement_to_lead = {}
                                for eng in HubSpotEngagement.query.all():
                                    assoc = (eng.raw_payload or {}).get('associations', {})
                                    deal_ids = assoc.get('dealIds') or []
                                    for deal_id in deal_ids:
                                        match = HubSpotMatch.query.filter_by(
                                            hubspot_record_type='deal',
                                            hubspot_id=str(deal_id),
                                            status='confirmed',
                                            internal_record_type='lead',
                                        ).first()
                                        if match and match.internal_record_id:
                                            engagement_to_lead[eng.hubspot_id] = match.internal_record_id
                                            break

                                flask_app.logger.info(
                                    "Assoc backfill: resolved %d engagement→lead mappings",
                                    len(engagement_to_lead),
                                )

                                # Backfill InteractionAssociation for orphaned interactions
                                inter_backfilled = 0
                                for interaction in Interaction.query.filter_by(
                                    source='hubspot_import', is_orphaned=True
                                ).all():
                                    if not interaction.hubspot_engagement_id:
                                        continue
                                    lead_id = engagement_to_lead.get(interaction.hubspot_engagement_id)
                                    if lead_id is None:
                                        continue
                                    existing = InteractionAssociation.query.filter_by(
                                        interaction_id=interaction.id, target_type='lead'
                                    ).first()
                                    if existing:
                                        continue
                                    _db.session.add(InteractionAssociation(
                                        interaction_id=interaction.id,
                                        target_type='lead',
                                        target_id=lead_id,
                                    ))
                                    interaction.is_orphaned = False
                                    inter_backfilled += 1
                                    if inter_backfilled % 500 == 0:
                                        _db.session.commit()
                                _db.session.commit()
                                flask_app.logger.info(
                                    "Assoc backfill: backfilled %d interaction associations", inter_backfilled
                                )

                                # Backfill TaskAssociation for orphaned tasks
                                task_backfilled = 0
                                for task in Task.query.filter_by(source='hubspot_import').all():
                                    if not task.hubspot_task_id:
                                        continue
                                    existing = TaskAssociation.query.filter_by(task_id=task.id).first()
                                    if existing:
                                        continue
                                    lead_id = engagement_to_lead.get(task.hubspot_task_id)
                                    if lead_id is None:
                                        continue
                                    _db.session.add(TaskAssociation(
                                        task_id=task.id,
                                        target_type='lead',
                                        target_id=lead_id,
                                    ))
                                    task_backfilled += 1
                                    if task_backfilled % 500 == 0:
                                        _db.session.commit()
                                _db.session.commit()
                                flask_app.logger.info(
                                    "Assoc backfill: backfilled %d task associations", task_backfilled
                                )

                            except Exception as exc:
                                flask_app.logger.error(
                                    "Assoc backfill: failed: %s", exc, exc_info=True
                                )

                    assoc_thread = _threading.Thread(
                        target=_startup_assoc_backfill,
                        args=(app,),
                        daemon=True,
                        name="hubspot-startup-assoc-backfill",
                    )
                    assoc_thread.start()

                if interaction_count > 0 and signal_count == 0:
                    app.logger.warning(
                        "Startup recovery: %d hubspot interactions exist but 0 signals. "
                        "Spawning background thread to run signal extraction.",
                        interaction_count,
                    )
                    import threading

                    def _startup_signal_recovery(flask_app):
                        with flask_app.app_context():
                            try:
                                from app import db as _db
                                from app.models import Interaction, InteractionAssociation
                                from app.models.hubspot_match import HubSpotMatch
                                from app.models.hubspot_engagement import HubSpotEngagement
                                from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

                                extractor = HubSpotSignalExtractorService()

                                # Build a lookup: engagement hubspot_id → lead_id
                                # via engagement.associations.dealIds → HubSpotMatch(deal, confirmed)
                                engagement_to_lead = {}
                                for eng in HubSpotEngagement.query.all():
                                    assoc = (eng.raw_payload or {}).get('associations', {})
                                    deal_ids = assoc.get('dealIds') or []
                                    for deal_id in deal_ids:
                                        match = HubSpotMatch.query.filter_by(
                                            hubspot_record_type='deal',
                                            hubspot_id=str(deal_id),
                                            status='confirmed',
                                            internal_record_type='lead',
                                        ).first()
                                        if match and match.internal_record_id:
                                            engagement_to_lead[eng.hubspot_id] = match.internal_record_id
                                            break

                                flask_app.logger.info(
                                    "Startup recovery: resolved %d engagement→lead mappings",
                                    len(engagement_to_lead),
                                )

                                interactions = (
                                    Interaction.query
                                    .filter_by(source='hubspot_import')
                                    .all()
                                )
                                processed = 0
                                signal_count = 0
                                for interaction in interactions:
                                    try:
                                        # Try existing InteractionAssociation first
                                        lead_assoc = (
                                            InteractionAssociation.query
                                            .filter_by(interaction_id=interaction.id, target_type='lead')
                                            .first()
                                        )
                                        lead_id = lead_assoc.target_id if lead_assoc else None

                                        # Fallback: resolve via engagement→deal→lead mapping
                                        if lead_id is None and interaction.hubspot_engagement_id:
                                            lead_id = engagement_to_lead.get(interaction.hubspot_engagement_id)

                                        if lead_id is None:
                                            continue

                                        class _A:
                                            def __init__(self, b, h):
                                                self.raw_payload = {'metadata': {'body': b or ''}}
                                                self.hubspot_id = h
                                        signals = extractor.extract_signals(
                                            _A(interaction.body, interaction.hubspot_engagement_id),
                                            lead_id,
                                        )
                                        for s in signals:
                                            _db.session.add(s)
                                            signal_count += 1
                                        if signals:
                                            extractor.apply_suppression(signals)
                                        _db.session.commit()
                                        processed += 1
                                    except Exception as exc:
                                        _db.session.rollback()
                                flask_app.logger.info(
                                    "Startup recovery: signal extraction complete — processed=%d signals=%d",
                                    processed, signal_count,
                                )
                                # Rescore leads
                                from app.services import LeadScoringEngine
                                LeadScoringEngine().bulk_rescore('default')
                                flask_app.logger.info("Startup recovery: lead rescore complete.")
                            except Exception as exc:
                                flask_app.logger.error(
                                    "Startup recovery: signal extraction failed: %s", exc, exc_info=True
                                )

                    recovery_thread = threading.Thread(
                        target=_startup_signal_recovery,
                        args=(app,),
                        daemon=True,
                        name="hubspot-startup-signal-recovery",
                    )
                    recovery_thread.start()

            except Exception as e:
                app.logger.warning("Startup import-run cleanup skipped: %s", e)

    app.logger.info("Flask application initialized successfully")
    
    return app
