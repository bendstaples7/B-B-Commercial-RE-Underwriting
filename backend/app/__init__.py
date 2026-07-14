"""Flask application factory."""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
import os

from app.api_utils import require_auth
# Re-export the reusable chain validator so callers can import it from either
# ``app`` or ``app.migration_utils`` without caring where it lives.
from app.migration_utils import assert_single_head_and_root  # noqa: F401
from app.exceptions import ConfigurationError

db = SQLAlchemy()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    # No global default — limits are applied explicitly per route category.
    # This prevents legitimate high-frequency reads (SSE, status checks, dashboards)
    # from being throttled while still protecting expensive write/AI endpoints.
    default_limits=[],
)

def _is_migration_context() -> bool:
    """Return True when the current process is executing a Flask-Migrate / Alembic command.

    Three detection mechanisms are used, any of which is sufficient:

    1. **Explicit env-var guard** – the operator (or CI) sets ``KIRO_MIGRATION=1``
       or ``FLASK_DB_COMMAND=1`` before invoking ``flask db ...``.  This is the
       most reliable mechanism and is used in deployment scripts.

    2. **sys.argv heuristic** – the ``flask`` CLI is invoked with a ``db``
       sub-command (e.g. ``flask db upgrade``).  We inspect ``sys.argv`` for the
       pattern ``db`` appearing as an argument, which covers the common cases
       ``flask db upgrade``, ``flask db downgrade``, ``flask db stamp``, etc.

    3. **Flask CLI environment variable** – Flask sets ``FLASK_APP`` when
       running under the ``flask`` command.  Combined with the ``db`` argv
       check this guards against false positives from other tools that set
       ``FLASK_APP`` for non-CLI purposes.

    Requirements: 5.1, 5.2, 5.4
    """
    import sys

    # Mechanism 1: explicit opt-in guard vars
    if os.environ.get('KIRO_MIGRATION') == '1':
        return True
    if os.environ.get('FLASK_DB_COMMAND') == '1':
        return True

    # Mechanism 2 + 3: Flask CLI with a db sub-command
    argv = sys.argv
    flask_app_set = bool(os.environ.get('FLASK_APP'))
    if flask_app_set and len(argv) >= 2 and 'db' in argv:
        return True

    # Mechanism 2 standalone: invoked as "flask db ..."
    # argv[0] may be the flask script path; check argv[1] is 'db'
    if len(argv) >= 2 and argv[1] == 'db':
        return True

    return False


def _assert_single_migration_head(app):
    """Abort startup if the Alembic migration graph has more than one head.

    Delegates to :func:`app.migration_utils.assert_single_head_and_root` for
    the graph traversal so the logic is reusable by the CLI/CI entry point
    (``scripts/check_migration_chain.py``) and the Alembic ``env.py`` guard.

    The underlying validator does NOT call ``SystemExit`` — this wrapper
    raises ``RuntimeError`` on violation, consistent with the non-blocking
    app factory approach (Req 5.1, 5.4, 7.1).
    """
    try:
        result = assert_single_head_and_root()
        head_count = result["head_count"]
        head_revisions = result["head_revisions"]

        if head_count > 1:
            head_list = ', '.join(head_revisions)
            msg = (
                f"Multiple Alembic heads detected: {head_list}. "
                "Two migration files share the same down_revision, creating a branch. "
                "Fix: set one migration's down_revision to point to the other so the "
                "chain is linear, then restart."
            )
            app.logger.error("*** MIGRATION ERROR: %s", msg)
            raise RuntimeError(msg)
    except RuntimeError:
        raise
    except Exception as e:
        app.logger.warning("Could not check migration heads: %s", e)


def _assert_enum_values_match_db(app):
    """
    Verify that every Python enum value used in SQLAlchemy models is present
    in the corresponding PostgreSQL enum type.

    This catches the class of bug where Python enum values (e.g. 'SINGLE_FAMILY')
    diverge from the DB enum values (e.g. 'single_family') — which causes silent
    data errors or IntegrityErrors at runtime rather than at startup.

    Only runs against PostgreSQL. Skipped for SQLite (used in tests).
    """
    try:
        from sqlalchemy import text
        from app.models.property_facts import PropertyType, ConstructionType, InteriorCondition

        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'postgresql' not in db_url:
            return  # SQLite in tests — skip

        enum_checks = [
            ('property_type',      PropertyType),
            ('construction_type',  ConstructionType),
            ('interior_condition', InteriorCondition),
        ]

        with app.app_context():
            for pg_type_name, py_enum in enum_checks:
                result = db.session.execute(text(
                    "SELECT enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON e.enumtypid = t.oid "
                    "WHERE t.typname = :typname"
                ), {'typname': pg_type_name})
                db_values = {row[0] for row in result}

                if not db_values:
                    # Type doesn't exist yet (fresh DB) — skip
                    continue

                python_values = {e.value for e in py_enum}
                missing_in_db = python_values - db_values
                missing_in_python = db_values - python_values

                if missing_in_db or missing_in_python:
                    raise ConfigurationError(
                        f"\n\n*** ENUM MISMATCH: '{pg_type_name}'\n"
                        f"  Python values : {sorted(python_values)}\n"
                        f"  DB values     : {sorted(db_values)}\n"
                        f"  In Python, not in DB : {sorted(missing_in_db)}\n"
                        f"  In DB, not in Python : {sorted(missing_in_python)}\n"
                        "Fix: align the Python enum values in models/property_facts.py "
                        "with the PostgreSQL enum, then restart.\n"
                    )
    except ConfigurationError:
        raise
    except Exception as e:
        app.logger.warning("Could not verify enum values against DB: %s", e)


def _warn_missing_optional_keys(app):
    """
    Log a clear warning at startup for env vars that are not strictly required
    to start the app but will cause silent failures mid-workflow if absent.

    Skipped entirely when running in a migration context to avoid blocking or
    adding latency to ``flask db upgrade`` and related commands (Req 5.6).
    """
    if _is_migration_context():
        return

    warnings = []

    if not os.getenv('GOOGLE_MAPS_API_KEY') or os.getenv('GOOGLE_MAPS_API_KEY') == 'your-google-maps-api-key':
        warnings.append(
            "GOOGLE_MAPS_API_KEY is not set. Geocoding will be skipped — "
            "subject properties will have no coordinates unless the frontend "
            "supplies them via Google Places Autocomplete. "
            "Comparable search (Step 2) will fail for any property without coordinates."
        )

    if not os.environ.get('GOOGLE_AI_API_KEY', '').strip():
        warnings.append(
            "GOOGLE_AI_API_KEY is not set or is empty. "
            "Gemini-powered comparable search (Step 2) will fail at runtime. "
            "Set GOOGLE_AI_API_KEY in backend/.env to enable AI comparable search."
        )

    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    try:
        import socket as _socket
        import redis as _redis
        r = _redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
    except Exception:
        # Redact credentials from the URL before logging; fall back to raw URL
        # if parsing fails (e.g. malformed URL) to avoid turning a connectivity
        # warning into a startup exception.
        try:
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}"
        except Exception:
            safe_url = '<redis-url>'
        warnings.append(
            f"Redis is not reachable at {safe_url}. "
            "The Celery worker cannot run — comparable search (Step 2) will fail. "
            "Start Redis with: wsl -d Ubuntu -- redis-server --daemonize yes"
        )

    for w in warnings:
        app.logger.warning("*** STARTUP WARNING: %s", w)


def _validate_and_log_database_url(app, config_name='development'):
    """
    Validate DATABASE_URL at startup and log the resolved host with credentials redacted.

    Requirements: 7.8, 8.1, 8.2
    """
    # Skip validation in testing mode — tests use SQLite in-memory
    if app.config.get('TESTING'):
        return

    from urllib.parse import urlparse

    def _safe_host(url: str) -> str:
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 5432}/{parsed.path.lstrip('/')}"
        except Exception:
            return url

    raw_url = os.getenv('DATABASE_URL', '')
    if not raw_url:
        msg = (
            "DATABASE_URL is not set. Set DATABASE_URL in backend/.env to a valid "
            "PostgreSQL connection string and restart."
        )
        app.logger.error(msg)
        raise ConfigurationError(msg, config_key='DATABASE_URL')

    try:
        parsed = urlparse(raw_url)
        if parsed.scheme not in ('postgresql', 'postgres'):
            raise ValueError(f"Unsupported scheme: {parsed.scheme!r}")
    except ConfigurationError:
        raise
    except Exception as exc:
        msg = (
            "DATABASE_URL is missing or malformed. Provide a valid PostgreSQL "
            f"connection string in backend/.env. Error: {exc}"
        )
        app.logger.error(msg)
        raise ConfigurationError(msg, config_key='DATABASE_URL') from exc

    app.logger.info("Database host resolved: %s", _safe_host(raw_url))
    app.config['DB_MODE'] = 'local'


def _assert_pool_pre_ping(app):
    """
    Raise RuntimeError if pool_pre_ping is absent from engine options
    when not running in test mode. Stale connections silently fail without it.
    Requirements: 8.4, 8.5
    """
    if app.config.get('TESTING'):
        return
    engine_opts = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
    if not engine_opts.get('pool_pre_ping'):
        raise RuntimeError(
            "pool_pre_ping=True is required in SQLALCHEMY_ENGINE_OPTIONS when "
            "TESTING is not True. Add it to create_app() and restart."
        )


def _assert_not_superuser(app):
    """
    Refuse to operate if the connected database user has superuser privileges
    on a non-localhost database. Superuser access to a cloud/remote database
    violates the principle of least privilege and is a security risk.

    Skipped for localhost/127.0.0.1 connections (local development) since
    developers commonly run as a superuser locally. Only enforced for remote
    (cloud) database connections.
    Requirements: 7.4, 7.5
    """
    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    # Skip for SQLite (tests) — check both postgresql:// and postgres:// schemes
    from urllib.parse import urlparse as _urlparse
    try:
        _scheme = _urlparse(db_url).scheme
    except Exception:
        _scheme = ''
    if _scheme not in ('postgresql', 'postgres'):
        return  # SQLite in tests — skip

    # Skip for local development connections
    from urllib.parse import urlparse
    try:
        parsed = urlparse(db_url)
        hostname = parsed.hostname or ''
        if hostname in ('localhost', '127.0.0.1', ''):
            return  # local DB — superuser is fine
    except Exception:
        return  # can't parse URL, skip check

    try:
        from sqlalchemy import text
        with app.app_context():
            result = db.session.execute(
                text("SELECT usesuper FROM pg_user WHERE usename = current_user")
            ).fetchone()
            if result and result[0]:
                msg = (
                    "SECURITY ERROR: The database user configured in DATABASE_URL "
                    "has superuser privileges. "
                    "Create a dedicated application user with minimum required privileges "
                    "(SELECT, INSERT, UPDATE, DELETE, schema modification for migrations) "
                    "and update DATABASE_URL in backend/.env."
                )
                app.logger.error(msg)
                raise ConfigurationError(msg, config_key='DATABASE_URL')
    except ConfigurationError:
        raise
    except Exception as e:
        app.logger.warning("Could not verify superuser status: %s", e)


def _warn_provider_dashboard(app):
    """
    Log a startup warning pointing operators to the provider's performance dashboard.
    The dashboard URL is read from PROVIDER_DASHBOARD_URL env var if set.
    Requirements: 8.3
    """
    dashboard_url = os.getenv('PROVIDER_DASHBOARD_URL', '')
    if dashboard_url:
        app.logger.warning(
            "*** OBSERVABILITY: Provider performance dashboard available at %s — "
            "monitor slow queries and connection counts here.", dashboard_url
        )
    else:
        app.logger.warning(
            "*** OBSERVABILITY: Set PROVIDER_DASHBOARD_URL in backend/.env to enable "
            "startup logging of the provider's performance dashboard URL."
        )


def create_app(config_name='development'):
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    # Load configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://localhost/real_estate_analysis')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Require a real SECRET_KEY — never allow the insecure default in production.
    _secret_key = os.getenv('SECRET_KEY', '')
    if config_name != 'testing' and (not _secret_key or _secret_key == 'dev-secret-key'):
        msg = (
            "SECRET_KEY is missing or set to the insecure default 'dev-secret-key'. "
            "Set a strong random SECRET_KEY in backend/.env before starting the server."
        )
        app.logger.error("FATAL: %s", msg)
        raise ConfigurationError(msg, config_key='SECRET_KEY')
    app.config['SECRET_KEY'] = _secret_key or 'dev-secret-key'  # testing only
    app.config['REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    # ENV check removed — ALLOW_LEGACY_X_USER_ID is no longer configurable
    # via environment. The X-User-Id header fallback is testing-only (set in
    # the testing config block below). This prevents production impersonation.

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
        app.config['TESTING'] = True  # set early so guards can check it
        # In testing, allow X-User-Id header as auth fallback — tests cannot
        # issue real JWTs. Never enable this in production/development.
        app.config['ALLOW_LEGACY_X_USER_ID'] = True  # testing only
    else:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 3,
            'max_overflow': 0,
            'pool_pre_ping': True,   # discard stale connections silently
            'pool_timeout': 30,      # wait up to 30s for a free connection
        }

    _assert_pool_pre_ping(app)

    # Disable rate limiting in tests so performance tests can create many resources
    if config_name == 'testing':
        app.config['RATELIMIT_ENABLED'] = False

    # Workflow thresholds — lower in development/testing so the full pipeline
    # can be exercised without needing a full set of real comparable sales.
    effective_threshold_env = os.getenv('FLASK_ENV', config_name)
    if effective_threshold_env == 'production':
        app.config['MIN_COMPARABLES'] = 10
        app.config['MIN_VALUATION_COMPARABLES'] = 5
    else:
        # development and testing both use 1 so the workflow is never blocked
        # by a lack of comparable data during local development or CI.
        app.config['MIN_COMPARABLES'] = 1
        app.config['MIN_VALUATION_COMPARABLES'] = 1
    
    # Use absolute path to alembic_migrations directory
    # (parent of app/ is backend/, then join with alembic_migrations)
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    migrations_dir = os.path.join(backend_dir, 'alembic_migrations')

    # Configure logging early so all startup guard messages appear in the console
    from app.logging_config import setup_logging
    setup_logging(app)

    # Validate DATABASE_URL and log the resolved host (credentials redacted).
    # Must run after SQLALCHEMY_DATABASE_URI is set and before db.init_app.
    _validate_and_log_database_url(app, config_name)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory=migrations_dir)
    CORS(app)
    limiter.init_app(app)

    # Auto-apply pending migrations in development only.
    # Uses FLASK_ENV if set, otherwise falls back to config_name.
    # Skip in Celery worker/beat processes — they share the same DB but
    # should not run migrations (Flask handles that on startup).
    # Skip entirely when running under a migration command (flask db ...) so
    # that the migration command itself is not aborted before producing output.
    effective_env = os.getenv('FLASK_ENV', config_name)
    _is_celery = os.getenv('CELERY_WORKER_RUNNING') == '1'
    if effective_env == 'development' and not _is_celery and not _is_migration_context():
        with app.app_context():
            _assert_single_migration_head(app)
            try:
                from flask_migrate import upgrade
                upgrade(directory=migrations_dir)
            except Exception as e:
                # ---------------------------------------------------------------------------
                # LOUD FAILURE: a migration error means the DB schema is out of sync with
                # the code. Silently continuing causes every request to 500 with
                # "column does not exist" errors that are very hard to diagnose.
                #
                # Instead, we assert the DB is at the expected head revision and raise
                # a RuntimeError that prevents the app from starting in a broken state.
                # ---------------------------------------------------------------------------
                app.logger.error(
                    "Migration failed during startup: %s\n"
                    "The database schema is out of sync with the application code.\n"
                    "Run:  cd backend && flask db upgrade head\n"
                    "Then restart the server.",
                    e,
                )
                # Verify whether the DB is actually at head despite the error
                # (e.g. the error was a no-op like a duplicate index that already exists)
                try:
                    from alembic.runtime.migration import MigrationContext
                    from alembic.script import ScriptDirectory
                    from flask_migrate import _get_config  # type: ignore[attr-defined]
                    alembic_cfg = _get_config('alembic_migrations')
                    script = ScriptDirectory.from_config(alembic_cfg)
                    head_revisions = {s.revision for s in script.get_revisions('heads')}
                    with db.engine.connect() as conn:
                        context = MigrationContext.configure(conn)
                        current_revisions = context.get_current_heads()
                    if set(current_revisions) != head_revisions:
                        raise RuntimeError(
                            f"\n\n"
                            f"  ╔══════════════════════════════════════════════════════════╗\n"
                            f"  ║  DATABASE SCHEMA OUT OF SYNC — SERVER WILL NOT START    ║\n"
                            f"  ╠══════════════════════════════════════════════════════════╣\n"
                            f"  ║  Current DB revision : {str(current_revisions):<34} ║\n"
                            f"  ║  Expected head       : {str(head_revisions):<34} ║\n"
                            f"  ╠══════════════════════════════════════════════════════════╣\n"
                            f"  ║  Fix:  cd backend && flask db upgrade head               ║\n"
                            f"  ╚══════════════════════════════════════════════════════════╝\n"
                        ) from e
                    else:
                        # DB is at head — the migration error was a harmless no-op
                        # (e.g. duplicate index/enum that already existed). Log and continue.
                        app.logger.warning(
                            "Migration raised an error but DB is already at head revision %s. "
                            "This is likely a harmless duplicate-object error. Continuing.",
                            current_revisions,
                        )
                except RuntimeError:
                    raise
                except Exception as check_err:
                    app.logger.warning("Could not verify migration head: %s", check_err)
            _assert_enum_values_match_db(app)
            _assert_not_superuser(app)
    elif effective_env != 'testing' and not _is_celery and not _is_migration_context():
        # In production (and any non-development, non-testing env), run the
        # superuser check without auto-migration. This ensures the security
        # guard fires on every production startup, not just development.
        with app.app_context():
            _assert_not_superuser(app)

    # Warn about missing env vars that will cause mid-workflow failures
    if effective_env == 'development':
        _warn_missing_optional_keys(app)
        _warn_provider_dashboard(app)

    # ---------------------------------------------------------------------------
    # User identity — centralise in g.user_id via before_request
    #
    # Production/development: identity comes exclusively from the verified Bearer
    # JWT (`sub` claim). X-User-Id header is not trusted in these environments.
    #
    # Testing: X-User-Id fallback is allowed so the test suite can set user
    # identity without issuing real JWTs.
    #
    # If no valid identity is resolved, g.user_id defaults to 'anonymous',
    # which authenticated endpoints reject with 401.
    # ---------------------------------------------------------------------------
    from flask import g, request as _request
    _is_testing = config_name == 'testing'

    @app.before_request
    def set_user_identity():
        """Populate g.user_id from Bearer JWT (required) or X-User-Id header (testing only)."""
        auth_header = _request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                from app.services.auth_service import AuthService
                claims = AuthService().verify_token(token)
                g.user_id = claims['sub']
                return  # Bearer token verified — done
            except Exception:
                # Invalid/expired token — fall through to anonymous
                pass

        if _is_testing:
            # In tests or when ALLOW_LEGACY_X_USER_ID=true, allow X-User-Id header
            # as a convenience identity mechanism since the frontend sends it.
            g.user_id = _request.headers.get('X-User-Id', 'anonymous')
        else:
            # In production/development, never trust the unauthenticated X-User-Id
            # header. No valid Bearer token means anonymous.
            g.user_id = 'anonymous'
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

    from app.controllers.open_letter_controller import open_letter_bp
    app.register_blueprint(open_letter_bp, url_prefix='/api/open-letter')

    from app.controllers.mail_queue_controller import mail_queue_bp
    app.register_blueprint(mail_queue_bp, url_prefix='/api/mail-queue')
    
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

    from app.controllers.cache_controller import cache_bp
    app.register_blueprint(cache_bp, url_prefix='/api/cache')

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

    # HubSpot Webhook Receiver — unauthenticated endpoint, isolated from hubspot_bp
    from app.controllers.hubspot_webhook_controller import hubspot_webhook_bp
    app.register_blueprint(hubspot_webhook_bp, url_prefix='/api/hubspot')

    # Contact management (CRUD + property-contact nested routes)
    from app.controllers.contact_controller import contacts_bp
    app.register_blueprint(contacts_bp, url_prefix='')

    # Actionable Lead Command Center — Queue endpoints
    from app.controllers.queue_controller import queue_bp
    app.register_blueprint(queue_bp, url_prefix='/api/queues')

    # Actionable Lead Command Center — Bulk Action endpoints (registered BEFORE
    # command_center_bp to avoid route conflicts with /api/leads/<int:lead_id>/*)
    from app.controllers.bulk_action_controller import bulk_action_bp
    app.register_blueprint(bulk_action_bp, url_prefix='/api/leads/bulk')

    # Actionable Lead Command Center — Command Center endpoints
    from app.controllers.command_center_controller import command_center_bp
    app.register_blueprint(command_center_bp, url_prefix='/api/leads')

    from app.controllers.property_match_controller import property_match_bp
    app.register_blueprint(property_match_bp, url_prefix='/api/leads')

    from app.controllers.entity_resolution_controller import entity_resolution_bp
    app.register_blueprint(entity_resolution_bp, url_prefix='/api/leads')

    from app.controllers.quick_add_controller import quick_add_bp
    app.register_blueprint(quick_add_bp, url_prefix='/api/leads')

    # Pipeline Config — stages and weights for Kanban scoring
    from app.controllers.pipeline_config_controller import pipeline_config_bp
    app.register_blueprint(pipeline_config_bp, url_prefix='/api')

    # Lead Kanban board endpoints
    from app.controllers.lead_kanban_controller import lead_kanban_bp
    app.register_blueprint(lead_kanban_bp)  # routes already carry full /api/... paths

    # Authentication endpoints (public — no token required for login)
    from app.controllers.auth_controller import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    # Admin panel endpoints (admin-only, guarded by require_admin)
    from app.controllers.admin_controller import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    # DuPage lead database ingestion endpoints
    from app.controllers.ingestion_controller import ingestion_bp
    app.register_blueprint(ingestion_bp, url_prefix='/api/ingestion')

    # OpenAPI spec endpoint
    from app.openapi import openapi_bp
    app.register_blueprint(openapi_bp, url_prefix='/api')

    # Global search endpoint
    from app.controllers.search_controller import search_bp
    app.register_blueprint(search_bp, url_prefix='/api')

    # Data Sources Panel — read-only diagnostic status endpoint
    from app.controllers.data_sources_controller import data_sources_bp
    app.register_blueprint(data_sources_bp, url_prefix='/api/data-sources')

    from app.controllers.prospect_controller import prospect_bp
    app.register_blueprint(prospect_bp, url_prefix='/api/prospects')

    # ---------------------------------------------------------------------------
    # Auto-configure HubSpot client secret from environment variable.
    #
    # If HUBSPOT_CLIENT_SECRET is set in .env and a HubSpotConfig row exists
    # but has no encrypted_client_secret yet, encrypt and store it automatically
    # at startup. This means the user never has to enter the secret in the UI —
    # just set the env var and restart the server.
    # ---------------------------------------------------------------------------
    # Skip HubSpot secret auto-config and all startup recovery/backfill when this
    # process is a migration/script context (KIRO_MIGRATION=1) — maintenance
    # scripts need app context for scoring without launching CRM backfills.
    if config_name != 'testing' and not _is_migration_context():
        with app.app_context():
            try:
                hs_client_secret = os.environ.get('HUBSPOT_CLIENT_SECRET', '').strip()
                if hs_client_secret:
                    from app.models.hubspot_config import HubSpotConfig as _HubSpotConfig
                    from app.services.hubspot_client_service import HubSpotClientService as _HCS
                    _config = _HubSpotConfig.query.order_by(_HubSpotConfig.id.desc()).first()
                    if _config and not _config.encrypted_client_secret:
                        _config.encrypted_client_secret = _HCS.encrypt_client_secret(hs_client_secret)
                        db.session.commit()
                        app.logger.info(
                            "Startup: auto-configured HubSpot client secret from HUBSPOT_CLIENT_SECRET env var."
                        )
            except Exception as _e:
                app.logger.warning("Startup: could not auto-configure HubSpot client secret: %s", _e)

    # ---------------------------------------------------------------------------
    # Startup cleanup — mark any import runs stuck in 'running' as 'failed'.
    # This happens when the server was restarted without a Celery worker running,
    # leaving runs permanently stuck. We mark them failed so the UI is accurate.
    # ---------------------------------------------------------------------------
    if config_name != 'testing' and not _is_migration_context():
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

                # Dangling confirmed lead matches (Bug 4): a deal/contact match still
                # points at a deleted lead, so enrichment and activity re-association
                # skip the surviving duplicate. Run the full post-import pipeline once
                # on startup when any are detected — deploy also runs this via
                # scripts/post_deploy_sync.py, but gunicorn reload must self-heal too.
                from app.services.hubspot_pipeline_runner import (  # noqa: PLC0415
                    count_dangling_confirmed_lead_matches,
                    maybe_start_startup_pipeline_recovery,
                )

                dangling_match_count = count_dangling_confirmed_lead_matches()
                maybe_start_startup_pipeline_recovery(app, dangling_match_count)

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

        # ---------------------------------------------------------------------------
        # CRM field backfill + Action Engine — runs automatically on first startup
        # after CRM columns were added to the leads table.
        #
        # Three-phase backfill (runs in a background thread so startup is not blocked):
        #   Phase 1: Backfill has_phone / has_email from existing flat columns
        #   Phase 2: Backfill has_property_match from confirmed HubSpot matches
        #   Phase 3: Run Action Engine bulk_recompute to set recommended_action
        #
        # Guard: only runs when any lead has recommended_action IS NULL.
        # After the first run, all leads have recommended_action set, so this
        # block becomes a no-op on subsequent startups.
        # ---------------------------------------------------------------------------
        with app.app_context():
            try:
                unclassified_count = db.session.execute(
                    db.text("SELECT COUNT(*) FROM leads WHERE recommended_action IS NULL")
                ).scalar()

                if unclassified_count > 0:
                    app.logger.info(
                        "Startup: %d unclassified leads detected. "
                        "Spawning background thread for CRM field backfill + Action Engine.",
                        unclassified_count,
                    )
                    import threading as _crm_threading

                    def _crm_backfill(flask_app):
                        """Backfill CRM fields and run Action Engine for all unclassified leads."""
                        with flask_app.app_context():
                            try:
                                from app import db as _db

                                # --------------------------------------------------
                                # Phase 1: Backfill has_phone / has_email
                                # Uses the flat phone_1..phone_7 / email_1..email_5
                                # columns that were populated during import.
                                # Also checks the contact_phones / contact_emails
                                # relational tables for leads migrated to the new model.
                                # --------------------------------------------------
                                flask_app.logger.info("CRM backfill: Phase 1 — has_phone / has_email")

                                phone_updated = _db.session.execute(_db.text("""
                                    UPDATE leads
                                    SET has_phone = TRUE
                                    WHERE has_phone = FALSE
                                    AND (
                                        phone_1 IS NOT NULL AND phone_1 != ''
                                        OR phone_2 IS NOT NULL AND phone_2 != ''
                                        OR phone_3 IS NOT NULL AND phone_3 != ''
                                        OR phone_4 IS NOT NULL AND phone_4 != ''
                                        OR phone_5 IS NOT NULL AND phone_5 != ''
                                        OR phone_6 IS NOT NULL AND phone_6 != ''
                                        OR phone_7 IS NOT NULL AND phone_7 != ''
                                        OR EXISTS (
                                            SELECT 1 FROM property_contacts pc
                                            JOIN contact_phones cp ON cp.contact_id = pc.contact_id
                                            WHERE pc.property_id = leads.id
                                        )
                                    )
                                """)).rowcount
                                _db.session.commit()
                                flask_app.logger.info(
                                    "CRM backfill: has_phone set TRUE for %d leads", phone_updated
                                )

                                email_updated = _db.session.execute(_db.text("""
                                    UPDATE leads
                                    SET has_email = TRUE
                                    WHERE has_email = FALSE
                                    AND (
                                        email_1 IS NOT NULL AND email_1 != ''
                                        OR email_2 IS NOT NULL AND email_2 != ''
                                        OR email_3 IS NOT NULL AND email_3 != ''
                                        OR email_4 IS NOT NULL AND email_4 != ''
                                        OR email_5 IS NOT NULL AND email_5 != ''
                                        OR EXISTS (
                                            SELECT 1 FROM property_contacts pc
                                            JOIN contact_emails ce ON ce.contact_id = pc.contact_id
                                            WHERE pc.property_id = leads.id
                                        )
                                    )
                                """)).rowcount
                                _db.session.commit()
                                flask_app.logger.info(
                                    "CRM backfill: has_email set TRUE for %d leads", email_updated
                                )

                                # --------------------------------------------------
                                # Phase 2: Backfill has_property_match
                                # A lead has a property match if there is a confirmed
                                # HubSpot match record linking it to a deal.
                                # --------------------------------------------------
                                flask_app.logger.info("CRM backfill: Phase 2 — has_property_match")

                                match_updated = _db.session.execute(_db.text("""
                                    UPDATE leads
                                    SET has_property_match = TRUE
                                    WHERE has_property_match = FALSE
                                    AND EXISTS (
                                        SELECT 1 FROM hubspot_matches hm
                                        WHERE hm.internal_record_id = leads.id
                                        AND hm.internal_record_type = 'lead'
                                        AND hm.status = 'confirmed'
                                    )
                                """)).rowcount
                                _db.session.commit()
                                flask_app.logger.info(
                                    "CRM backfill: has_property_match set TRUE for %d leads", match_updated
                                )

                                # --------------------------------------------------
                                # Phase 3: Run Action Engine bulk recompute
                                # Now that has_phone, has_email, has_property_match
                                # are accurate, the engine can classify correctly.
                                # --------------------------------------------------
                                flask_app.logger.info("CRM backfill: Phase 3 — Action Engine bulk recompute")
                                from app.services.action_engine_service import ActionEngineService
                                total = ActionEngineService.bulk_recompute()
                                flask_app.logger.info(
                                    "CRM backfill: Action Engine classified %d leads.", total
                                )

                            except Exception as exc:
                                flask_app.logger.error(
                                    "CRM backfill failed: %s", exc, exc_info=True
                                )

                    crm_thread = _crm_threading.Thread(
                        target=_crm_backfill,
                        args=(app,),
                        daemon=True,
                        name="crm-startup-backfill",
                    )
                    crm_thread.start()

            except Exception as e:
                app.logger.warning("CRM backfill check skipped: %s", e)

        # ---------------------------------------------------------------------------
        # Building ownership backfill — enqueue Celery sweep for commercial leads
        # without a condo_analysis_id (runs in background; capped per task).
        # Skip in Celery worker/beat: create_app() runs there too and would
        # recursively enqueue another backfill task.
        # ---------------------------------------------------------------------------
        if not _is_celery and not _is_migration_context():
            with app.app_context():
                try:
                    from app.services.building_ownership_backfill import (
                        release_startup_backfill_advisory_lock,
                        try_claim_startup_backfill_dispatch,
                    )

                    if not try_claim_startup_backfill_dispatch():
                        app.logger.info(
                            "Building ownership startup backfill already claimed by another worker"
                        )
                    else:
                        try:
                            pending_count = db.session.execute(
                                db.text(
                                    """
                                    SELECT COUNT(*) FROM leads
                                    WHERE lead_category = 'commercial'
                                      AND property_street IS NOT NULL
                                      AND TRIM(property_street) != ''
                                      AND condo_analysis_id IS NULL
                                      AND lead_status NOT IN (
                                        'suppressed', 'do_not_contact', 'deal_won', 'deal_lost'
                                      )
                                    """
                                )
                            ).scalar()

                            if pending_count and pending_count > 0:
                                app.logger.info(
                                    "Startup: %d commercial leads lack building ownership analysis; "
                                    "enqueueing backfill task.",
                                    pending_count,
                                )
                                from celery_worker import (
                                    building_ownership_backfill_commercial_task,
                                )
                                building_ownership_backfill_commercial_task.apply_async(
                                    ignore_result=True,
                                )
                        finally:
                            release_startup_backfill_advisory_lock()
                except Exception as e:
                    app.logger.warning("Building ownership startup check skipped: %s", e)

    app.logger.info("Flask application initialized successfully")
    
    return app
