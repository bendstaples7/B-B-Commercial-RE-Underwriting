"""Logging configuration for the real estate analysis platform."""
import logging
import logging.handlers
import os
from datetime import datetime


def setup_logging(app):
    """
    Configure comprehensive logging for the application.
    
    Args:
        app: Flask application instance
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Set logging level from environment or default to INFO
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers = []
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(name)s (%(filename)s:%(lineno)d): %(message)s'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Console handler (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler for general logs (rotating)
    general_log_file = os.path.join(log_dir, 'app.log')
    file_handler = logging.handlers.RotatingFileHandler(
        general_log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    # File handler for errors only
    error_log_file = os.path.join(log_dir, 'errors.log')
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)
    
    # Configure Flask app logger
    app.logger.setLevel(numeric_level)
    
    # Log startup message
    app.logger.info(f"Logging configured - Level: {log_level}")
    app.logger.info(f"Log directory: {log_dir}")


class APICallLogger:
    """Logger for tracking external API calls."""
    
    def __init__(self):
        self.logger = logging.getLogger('api_calls')
        
        # Create API calls log file
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        api_log_file = os.path.join(log_dir, 'api_calls.log')
        handler = logging.handlers.RotatingFileHandler(
            api_log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_api_call(self, source: str, endpoint: str, status: str, 
                     response_time: float = None, error: str = None):
        """
        Log an external API call.
        
        Args:
            source: API source name (e.g., 'MLS', 'TaxAssessor')
            endpoint: API endpoint or method called
            status: Call status ('success', 'failure', 'timeout')
            response_time: Response time in seconds
            error: Error message if call failed
        """
        log_data = {
            'source': source,
            'endpoint': endpoint,
            'status': status,
            'response_time': response_time,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if error:
            log_data['error'] = error
            self.logger.error(f"API call failed: {log_data}")
        else:
            self.logger.info(f"API call: {log_data}")
    
    def log_failover(self, primary_source: str, fallback_source: str, 
                     field: str, success: bool):
        """
        Log API failover event.
        
        Args:
            primary_source: Primary API source that failed
            fallback_source: Fallback source attempted
            field: Data field being retrieved
            success: Whether fallback succeeded
        """
        log_data = {
            'event': 'api_failover',
            'primary_source': primary_source,
            'fallback_source': fallback_source,
            'field': field,
            'success': success,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if success:
            self.logger.info(f"Failover successful: {log_data}")
        else:
            self.logger.warning(f"Failover failed: {log_data}")


class UserActionLogger:
    """Logger for tracking user actions and workflow events."""
    
    def __init__(self):
        self.logger = logging.getLogger('user_actions')
        
        # Create user actions log file
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        user_log_file = os.path.join(log_dir, 'user_actions.log')
        handler = logging.handlers.RotatingFileHandler(
            user_log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_action(self, user_id: str, action: str, session_id: str = None, 
                   details: dict = None):
        """
        Log a user action.
        
        Args:
            user_id: User identifier
            action: Action performed (e.g., 'start_analysis', 'approve_step')
            session_id: Analysis session ID
            details: Additional action details
        """
        log_data = {
            'user_id': user_id,
            'action': action,
            'session_id': session_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if details:
            log_data['details'] = details
        
        self.logger.info(f"User action: {log_data}")
    
    def log_workflow_event(self, session_id: str, event: str, 
                          from_step: str = None, to_step: str = None):
        """
        Log a workflow state change event.
        
        Args:
            session_id: Analysis session ID
            event: Event type (e.g., 'step_advance', 'step_back', 'data_modified')
            from_step: Previous workflow step
            to_step: New workflow step
        """
        log_data = {
            'event': 'workflow_event',
            'session_id': session_id,
            'event_type': event,
            'from_step': from_step,
            'to_step': to_step,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self.logger.info(f"Workflow event: {log_data}")


# Create singleton instances
api_call_logger = APICallLogger()
user_action_logger = UserActionLogger()
