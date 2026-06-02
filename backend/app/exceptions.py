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


# ---------------------------------------------------------------------------
# Multifamily Underwriting Exceptions
# ---------------------------------------------------------------------------


class DealValidationError(RealEstateAnalysisException):
    """Exception raised when deal validation fails (e.g., unit_count < 5, non-positive purchase_price)."""

    def __init__(self, message: str, field: str, constraint: str = None):
        super().__init__(message, status_code=400)
        self.payload = {
            'error_type': 'deal_validation_error',
            'field': field,
            'constraint': constraint,
        }


class DuplicateUnitIdentifierError(RealEstateAnalysisException):
    """Exception raised when a duplicate unit_identifier is added within the same deal."""

    def __init__(self, message: str, deal_id: int, unit_identifier: str):
        super().__init__(message, status_code=409)
        self.payload = {
            'error_type': 'duplicate_unit_identifier',
            'deal_id': deal_id,
            'unit_identifier': unit_identifier,
        }


class DuplicateFundingSourceError(RealEstateAnalysisException):
    """Exception raised when a duplicate source_type is added within the same deal."""

    def __init__(self, message: str, deal_id: int, source_type: str):
        super().__init__(message, status_code=409)
        self.payload = {
            'error_type': 'duplicate_funding_source',
            'deal_id': deal_id,
            'source_type': source_type,
        }


class LenderAttachmentLimitError(RealEstateAnalysisException):
    """Exception raised when exceeding the maximum lender profiles per scenario."""

    def __init__(self, message: str, deal_id: int, scenario: str, limit: int = 3):
        super().__init__(message, status_code=400)
        self.payload = {
            'error_type': 'lender_attachment_limit',
            'deal_id': deal_id,
            'scenario': scenario,
            'limit': limit,
        }


class ProFormaMissingInputsError(RealEstateAnalysisException):
    """Exception raised when required pro forma inputs are missing."""

    def __init__(self, message: str, missing_inputs: list):
        super().__init__(message, status_code=422)
        self.payload = {
            'error_type': 'pro_forma_missing_inputs',
            'missing_inputs': missing_inputs,
        }


class UnsupportedImportFormatError(RealEstateAnalysisException):
    """Exception raised when an import workbook has format issues (missing sheet or column)."""

    def __init__(self, message: str, missing_sheet: str = None, missing_column: str = None, sheet: str = None):
        super().__init__(message, status_code=422)
        self.payload = {
            'error_type': 'unsupported_import_format',
            'missing_sheet': missing_sheet,
            'missing_column': missing_column,
            'sheet': sheet,
        }


# ---------------------------------------------------------------------------
# Commercial OM PDF Intake Exceptions
# ---------------------------------------------------------------------------


class InvalidFileError(RealEstateAnalysisException):
    """Exception raised when an uploaded file is invalid, corrupt, or an unsupported MIME type."""

    def __init__(self, message: str, payload: dict = None):
        super().__init__(message, status_code=422)
        base_payload = {'error_type': 'invalid_file'}
        if payload:
            base_payload.update(payload)
        self.payload = base_payload


class ExternalServiceError(RealEstateAnalysisException):
    """Exception raised when an external API call fails. Base class for service-specific errors."""

    def __init__(self, message: str, payload: dict = None):
        super().__init__(message, status_code=502)
        base_payload = {'error_type': 'external_service_error'}
        if payload:
            base_payload.update(payload)
        self.payload = base_payload


class ResourceNotFoundError(RealEstateAnalysisException):
    """Exception raised when a requested resource is not found or belongs to another user."""

    def __init__(self, message: str, payload: dict = None):
        super().__init__(message, status_code=404)
        base_payload = {'error_type': 'resource_not_found'}
        if payload:
            base_payload.update(payload)
        self.payload = base_payload


class ConflictError(RealEstateAnalysisException):
    """Exception raised when a request conflicts with the current state (e.g., re-confirming an already-confirmed job)."""

    def __init__(self, message: str, payload: dict = None):
        super().__init__(message, status_code=409)
        base_payload = {'error_type': 'conflict'}
        if payload:
            base_payload.update(payload)
        self.payload = base_payload


class GeminiConfigurationError(ExternalServiceError):
    """Exception raised when the Gemini API key is missing or not configured."""

    def __init__(self, message: str, payload: dict = None):
        combined_payload = {'error_type': 'gemini_configuration_error'}
        if payload:
            combined_payload.update(payload)
        # Call RealEstateAnalysisException directly to set status_code and payload cleanly
        RealEstateAnalysisException.__init__(self, message, status_code=502)
        self.payload = combined_payload


class GeminiAPIError(ExternalServiceError):
    """Exception raised when a network or HTTP error occurs communicating with the Gemini API."""

    def __init__(self, message: str, payload: dict = None):
        combined_payload = {'error_type': 'gemini_api_error'}
        if payload:
            combined_payload.update(payload)
        RealEstateAnalysisException.__init__(self, message, status_code=502)
        self.payload = combined_payload


class GeminiParseError(ExternalServiceError):
    """Exception raised when the Gemini API returns a response that is not valid JSON."""

    def __init__(self, message: str, payload: dict = None):
        combined_payload = {'error_type': 'gemini_parse_error'}
        if payload:
            combined_payload.update(payload)
        RealEstateAnalysisException.__init__(self, message, status_code=502)
        self.payload = combined_payload


class GeminiResponseError(ExternalServiceError):
    """Exception raised when the Gemini API response is valid JSON but is missing required fields."""

    def __init__(self, message: str, payload: dict = None, missing_keys: list = None):
        combined_payload = {'error_type': 'gemini_response_error'}
        if payload:
            combined_payload.update(payload)
        if missing_keys is not None:
            combined_payload['missing_keys'] = missing_keys
        RealEstateAnalysisException.__init__(self, message, status_code=502)
        self.payload = combined_payload


# ---------------------------------------------------------------------------
# HubSpot CRM Migration Exceptions
# ---------------------------------------------------------------------------


class HubSpotReadOnlyViolation(RealEstateAnalysisException):
    """Exception raised when a code path attempts to call a non-GET HubSpot API endpoint.

    The HubSpot integration is strictly read-only; any write attempt is a
    programming error and is treated as an internal server error (500).
    """

    def __init__(self, message: str = "HubSpot integration is read-only; write operations are not permitted"):
        super().__init__(message, status_code=500)
        self.payload = {
            'error_type': 'hubspot_readonly_violation',
        }


class HubSpotAuthenticationError(RealEstateAnalysisException):
    """Exception raised when the HubSpot API returns a 401 or 403 response.

    Indicates the stored token is invalid, expired, or lacks required scopes.
    """

    def __init__(self, message: str = "HubSpot authentication failed; check that the token is valid and has the required scopes"):
        super().__init__(message, status_code=401)
        self.payload = {
            'error_type': 'hubspot_authentication_error',
        }


class HubSpotRateLimitError(RealEstateAnalysisException):
    """Exception raised when the HubSpot API returns a 429 Too Many Requests response.

    The ``retry_after`` field (seconds) is surfaced in the payload so that
    Celery tasks can schedule an exponential-backoff retry.
    """

    def __init__(self, message: str = "HubSpot API rate limit exceeded", retry_after: int = None):
        super().__init__(message, status_code=429)
        self.payload = {
            'error_type': 'hubspot_rate_limit_error',
            'retry_after': retry_after,
        }


class ImportRunNotFoundError(ResourceNotFoundError):
    """Exception raised when a requested HubSpot import run record does not exist."""

    def __init__(self, message: str, payload: dict = None):
        combined_payload = {'error_type': 'import_run_not_found'}
        if payload:
            combined_payload.update(payload)
        RealEstateAnalysisException.__init__(self, message, status_code=404)
        self.payload = combined_payload


class MatchNotFoundError(ResourceNotFoundError):
    """Exception raised when a requested HubSpot match record does not exist."""

    def __init__(self, message: str, payload: dict = None):
        combined_payload = {'error_type': 'match_not_found'}
        if payload:
            combined_payload.update(payload)
        RealEstateAnalysisException.__init__(self, message, status_code=404)
        self.payload = combined_payload


class OrganizationValidationError(ValidationException):
    """Exception raised when Organization data fails validation (e.g., empty name)."""

    def __init__(self, message: str, field: str = None, value=None):
        # Call the grandparent directly so we can set our own error_type
        RealEstateAnalysisException.__init__(self, message, status_code=400)
        self.payload = {
            'error_type': 'organization_validation_error',
            'field': field,
            'invalid_value': str(value) if value is not None else None,
        }


class InteractionValidationError(ValidationException):
    """Exception raised when Interaction data fails validation (e.g., empty body, no association target)."""

    def __init__(self, message: str, field: str = None, value=None):
        RealEstateAnalysisException.__init__(self, message, status_code=400)
        self.payload = {
            'error_type': 'interaction_validation_error',
            'field': field,
            'invalid_value': str(value) if value is not None else None,
        }


class TaskValidationError(ValidationException):
    """Exception raised when Task data fails validation (e.g., empty title)."""

    def __init__(self, message: str, field: str = None, value=None):
        RealEstateAnalysisException.__init__(self, message, status_code=400)
        self.payload = {
            'error_type': 'task_validation_error',
            'field': field,
            'invalid_value': str(value) if value is not None else None,
        }


# ── Actionable Lead Command Center exceptions ──────────────────────────────


class LeadTaskValidationError(RealEstateAnalysisException):
    """Raised when a LeadTask field fails validation (e.g. title too long, invalid due date)."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message, status_code=400)
        self.payload = {'error_type': 'lead_task_validation_error', 'field': field} if field else {'error_type': 'lead_task_validation_error'}


class InvalidLeadStatusTransitionError(RealEstateAnalysisException):
    """Raised when a Lead_Status transition is not permitted."""

    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            f"Cannot transition lead status from '{from_status}' to '{to_status}'.",
            status_code=422,
        )
        self.payload = {
            'error_type': 'invalid_lead_status_transition',
            'from_status': from_status,
            'to_status': to_status,
        }


class InvalidTaskStatusTransitionError(RealEstateAnalysisException):
    """Raised when a LeadTask status transition is not permitted (e.g. re-completing a completed task)."""

    def __init__(self, task_id: int, current_status: str, attempted_status: str):
        super().__init__(
            f"Cannot transition task {task_id} from '{current_status}' to '{attempted_status}'.",
            status_code=422,
        )
        self.payload = {
            'error_type': 'invalid_task_status_transition',
            'task_id': task_id,
            'current_status': current_status,
            'attempted_status': attempted_status,
        }


class DoNotContactViolationError(RealEstateAnalysisException):
    """Raised when an outreach action is attempted on a Do Not Contact lead."""

    def __init__(self, lead_id: int):
        super().__init__(
            f"Lead {lead_id} is marked Do Not Contact. Outreach actions are not permitted.",
            status_code=403,
        )
        self.payload = {'error_type': 'do_not_contact_violation', 'lead_id': lead_id}


class ActionEngineRecomputationError(RealEstateAnalysisException):
    """Raised when the Action Engine fails to recompute a recommended action."""

    def __init__(self, lead_id: int, reason: str):
        super().__init__(
            f"Action Engine failed to recompute recommended action for lead {lead_id}: {reason}",
            status_code=500,
        )
        self.payload = {
            'error_type': 'action_engine_recomputation_error',
            'lead_id': lead_id,
            'reason': reason,
        }


# ---------------------------------------------------------------------------
# Chicago Socrata Local Cache Exceptions
# ---------------------------------------------------------------------------


class CacheSyncException(RealEstateAnalysisException):
    """Raised when a cache sync operation fails unrecoverably."""

    def __init__(self, message: str, dataset: str, page_offset: int = None):
        super().__init__(message, status_code=503)
        self.payload = {
            'error_type': 'cache_sync_error',
            'dataset': dataset,
            'page_offset': page_offset,
        }


class InvalidCronExpressionException(RealEstateAnalysisException):
    """Raised at startup when SOCRATA_SYNC_SCHEDULE contains an invalid cron expression."""

    def __init__(self, expression: str):
        super().__init__(
            f"Invalid cron expression in SOCRATA_SYNC_SCHEDULE: {expression!r}",
            status_code=500,
        )
        self.payload = {
            'error_type': 'invalid_cron_expression',
            'expression': expression,
        }


# ---------------------------------------------------------------------------
# Admin Panel — Password Setup Exceptions
# ---------------------------------------------------------------------------


class PasswordSetupRequiredException(RealEstateAnalysisException):
    """Exception raised when a user has not yet set their password.

    Raised by AuthService.authenticate when the user exists and is active but
    has no password set (empty hash or password_set=False). The caller issues a
    short-lived setup JWT and returns HTTP 200 with {"setup_required": true,
    "setup_token": "..."} so the client can redirect to POST /api/auth/set-password.

    The ``user`` attribute holds the User instance so the caller can issue a
    setup token without an extra database lookup.
    """

    def __init__(self, user):
        super().__init__(
            "Password setup required. Please set your password before logging in.",
            status_code=200,
        )
        self.user = user
        self.payload = {
            "error_type": "password_setup_required",
        }


# ---------------------------------------------------------------------------
# Backward-compatible aliases
#
# These names were used in admin_service.py (introduced by the admin-panel
# branch) but don't match the canonical names defined above. The aliases make
# the wrong names work correctly so a typo never crashes the Celery worker
# again. New code should use the canonical names.
# ---------------------------------------------------------------------------

#: Alias for ResourceNotFoundError — use ResourceNotFoundError in new code.
NotFoundError = ResourceNotFoundError

#: Alias for ValidationException — use ValidationException in new code.
ValidationError = ValidationException
