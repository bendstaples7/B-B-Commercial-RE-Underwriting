"""Custom exception classes for the real estate analysis platform."""


class RealEstateAnalysisException(Exception):
    """Base exception for all application-specific errors."""
    
    def __init__(self, message: str, status_code: int = 500, payload: dict = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


class DataRetrievalException(RealEstateAnalysisException):
    """Exception raised when property data retrieval fails."""
    
    def __init__(self, message: str, source: str = None, field: str = None):
        super().__init__(message, status_code=503)
        self.payload = {
            'error_type': 'data_retrieval_error',
            'source': source,
            'field': field
        }


class APIFailoverException(RealEstateAnalysisException):
    """Exception raised when all API sources fail."""
    
    def __init__(self, message: str, attempted_sources: list = None):
        super().__init__(message, status_code=503)
        self.payload = {
            'error_type': 'api_failover_error',
            'attempted_sources': attempted_sources or []
        }


class ValidationException(RealEstateAnalysisException):
    """Exception raised when data validation fails."""
    
    def __init__(self, message: str, field: str = None, value=None):
        super().__init__(message, status_code=400)
        self.payload = {
            'error_type': 'validation_error',
            'field': field,
            'invalid_value': str(value) if value is not None else None
        }


class WorkflowException(RealEstateAnalysisException):
    """Exception raised when workflow operations fail."""
    
    def __init__(self, message: str, current_step: str = None, required_step: str = None):
        super().__init__(message, status_code=400)
        self.payload = {
            'error_type': 'workflow_error',
            'current_step': current_step,
            'required_step': required_step
        }


class SessionNotFoundException(RealEstateAnalysisException):
    """Exception raised when analysis session is not found."""
    
    def __init__(self, session_id: str):
        super().__init__(f"Analysis session not found: {session_id}", status_code=404)
        self.payload = {
            'error_type': 'session_not_found',
            'session_id': session_id
        }


class InsufficientComparablesException(RealEstateAnalysisException):
    """Exception raised when insufficient comparable sales are found."""
    
    def __init__(self, found_count: int, required_count: int = 10):
        super().__init__(
            f"Insufficient comparables found: {found_count} (required: {required_count})",
            status_code=422
        )
        self.payload = {
            'error_type': 'insufficient_comparables',
            'found_count': found_count,
            'required_count': required_count
        }


class RateLimitException(RealEstateAnalysisException):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = None):
        super().__init__(message, status_code=429)
        self.payload = {
            'error_type': 'rate_limit_exceeded',
            'retry_after': retry_after
        }


class ExportException(RealEstateAnalysisException):
    """Exception raised when report export fails."""
    
    def __init__(self, message: str, export_format: str = None):
        super().__init__(message, status_code=500)
        self.payload = {
            'error_type': 'export_error',
            'export_format': export_format
        }


class MissingCriticalDataException(RealEstateAnalysisException):
    """Exception raised when critical required data is missing."""
    
    def __init__(self, missing_fields: list):
        super().__init__(
            f"Critical data missing: {', '.join(missing_fields)}",
            status_code=422
        )
        self.payload = {
            'error_type': 'missing_critical_data',
            'missing_fields': missing_fields
        }


class AuthenticationException(RealEstateAnalysisException):
    """Exception raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)
        self.payload = {
            'error_type': 'authentication_error'
        }


class AuthorizationException(RealEstateAnalysisException):
    """Exception raised when authorization fails."""
    
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, status_code=403)
        self.payload = {
            'error_type': 'authorization_error'
        }
