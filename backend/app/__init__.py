"""Flask application factory."""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

db = SQLAlchemy()
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
    CORS(app)
    limiter.init_app(app)
    
    # Configure logging
    from app.logging_config import setup_logging
    setup_logging(app)
    
    # Register error handlers
    from app.error_handlers import register_error_handlers
    register_error_handlers(app)
    
    # Register blueprints
    from app.controllers import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    app.logger.info("Flask application initialized successfully")
    
    return app
