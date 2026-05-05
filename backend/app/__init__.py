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
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory='alembic_migrations')
    CORS(app)
    limiter.init_app(app)

    # Auto-apply pending migrations in development
    if os.getenv('FLASK_ENV', 'development') == 'development':
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
    
    app.logger.info("Flask application initialized successfully")
    
    return app
