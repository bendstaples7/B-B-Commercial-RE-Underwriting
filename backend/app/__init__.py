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
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory='alembic_migrations')
    CORS(app)
    limiter.init_app(app)

    # Auto-apply pending migrations in development only.
    # Uses FLASK_ENV if set, otherwise falls back to config_name.
    # This ensures: tests (config_name='testing') skip, production (FLASK_ENV='production') skips,
    # local dev (both default to 'development') runs migrations.
    effective_env = os.getenv('FLASK_ENV', config_name)
    if effective_env == 'development':
        with app.app_context():
            try:
                from flask_migrate import upgrade
                upgrade(directory='alembic_migrations')
            except Exception as e:
                app.logger.warning("Auto-migrate skipped: %s", e)
    
    # Configure logging
    from app.logging_config import setup_logging
    setup_logging(app)
    
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
    
    app.logger.info("Flask application initialized successfully")
    
    return app
