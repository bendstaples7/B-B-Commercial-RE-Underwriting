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
    default_limits=["200 per day", "50 per hour"]
)

def _assert_single_migration_head(app):
    """
    Abort startup if the Alembic migration graph has more than one head.

    Multiple heads mean two migration files share the same down_revision,
    creating a branch that `upgrade head` cannot resolve automatically.
    This check surfaces the problem immediately with a clear error rather
    than letting Flask start in a partially-migrated or broken state.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        # Use absolute path to alembic_migrations directory
        # (parent of app/ is backend/, then join with alembic_migrations)
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        migrations_dir = os.path.join(backend_dir, 'alembic_migrations')

        alembic_cfg = Config()
        alembic_cfg.set_main_option('script_location', migrations_dir)
        script = ScriptDirectory.from_config(alembic_cfg)
        heads = script.get_heads()

        if len(heads) > 1:
            head_list = ', '.join(heads)
            raise SystemExit(
                f"\n\n*** MIGRATION ERROR: Multiple Alembic heads detected: {head_list}\n"
                "Two migration files share the same down_revision, creating a branch.\n"
                "Fix: set one migration's down_revision to point to the other so the\n"
                "chain is linear, then restart.\n"
            )
    except SystemExit:
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
                    raise SystemExit(
                        f"\n\n*** ENUM MISMATCH: '{pg_type_name}'\n"
                        f"  Python values : {sorted(python_values)}\n"
                        f"  DB values     : {sorted(db_values)}\n"
                        f"  In Python, not in DB : {sorted(missing_in_db)}\n"
                        f"  In DB, not in Python : {sorted(missing_in_python)}\n"
                        "Fix: align the Python enum values in models/property_facts.py "
                        "with the PostgreSQL enum, then restart.\n"
                    )
    except SystemExit:
        raise
    except Exception as e:
        app.logger.warning("Could not verify enum values against DB: %s", e)


def _warn_missing_optional_keys(app):
    """
    Log a clear warning at startup for env vars that are not strictly required
    to start the app but will cause silent failures mid-workflow if absent.
    """
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
        import redis as _redis
        r = _redis.from_url(redis_url)
        r.ping()
    except Exception:
        # Redact credentials from the URL before logging
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}"
        warnings.append(
            f"Redis is not reachable at {safe_url}. "
            "The Celery worker cannot run — comparable search (Step 2) will fail. "
            "Start Redis with: docker compose up -d"
        )

    for w in warnings:
        app.logger.warning("*** STARTUP WARNING: %s", w)


def create_app(config_name='development'):
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    # Load configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://localhost/real_estate_analysis')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    app.config['REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

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
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory=migrations_dir)
    CORS(app)
    limiter.init_app(app)

    # Auto-apply pending migrations in development only.
    # Uses FLASK_ENV if set, otherwise falls back to config_name.
    # This ensures: tests (config_name='testing') skip, production (FLASK_ENV='production') skips,
    # local dev (both default to 'development') runs migrations.
    effective_env = os.getenv('FLASK_ENV', config_name)
    if effective_env == 'development':
        with app.app_context():
            _assert_single_migration_head(app)
            from flask_migrate import upgrade
            upgrade(directory=migrations_dir)
            _assert_enum_values_match_db(app)
    
    # Configure logging
    from app.logging_config import setup_logging
    setup_logging(app)

    # Warn about missing env vars that will cause mid-workflow failures
    if effective_env == 'development':
        _warn_missing_optional_keys(app)
    
    # Register error handlers
    from app.error_handlers import register_error_handlers
    register_error_handlers(app)
    
    # Register blueprints
    from app.controllers import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from app.controllers.lead_controller import lead_bp
    app.register_blueprint(lead_bp, url_prefix='/api/leads')
    
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

    from app.controllers.cache_controller import cache_bp
    app.register_blueprint(cache_bp, url_prefix='/api/cache')
    
    app.logger.info("Flask application initialized successfully")
    
    return app
