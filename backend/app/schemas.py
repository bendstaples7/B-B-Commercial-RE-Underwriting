"""Marshmallow schemas for request validation."""
from marshmallow import Schema, fields, validate, ValidationError, validates_schema, validates, EXCLUDE
from datetime import datetime


class RequestSchema(Schema):
    """Base class for all API request schemas.

    Silently drops any unknown fields (e.g. ``user_id`` injected by the
    frontend Axios interceptor) rather than raising a validation error.
    All request schemas should inherit from this class.
    """

    class Meta:
        unknown = EXCLUDE


class StartAnalysisSchema(Schema):
    """Schema for starting a new analysis."""
    address = fields.Str(required=True, validate=validate.Length(min=5, max=500))


class PropertyFactsSchema(Schema):
    """Schema for property facts data."""
    address = fields.Str(required=True, validate=validate.Length(min=5, max=500))
    property_type = fields.Str(required=True, validate=validate.OneOf([
        'SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL'
    ]))
    units = fields.Int(required=True, validate=validate.Range(min=1))
    bedrooms = fields.Int(required=True, validate=validate.Range(min=0))
    bathrooms = fields.Float(required=True, validate=validate.Range(min=0))
    square_footage = fields.Int(required=True, validate=validate.Range(min=1))
    lot_size = fields.Int(required=True, validate=validate.Range(min=0))
    year_built = fields.Int(required=True)
    construction_type = fields.Str(required=True, validate=validate.OneOf([
        'FRAME', 'BRICK', 'MASONRY', 'CONCRETE', 'STEEL'
    ]))
    basement = fields.Bool(load_default=False)
    parking_spaces = fields.Int(load_default=0, validate=validate.Range(min=0))
    last_sale_price = fields.Float(allow_none=True)
    last_sale_date = fields.Date(allow_none=True)
    assessed_value = fields.Float(required=True, validate=validate.Range(min=0))
    annual_taxes = fields.Float(required=True, validate=validate.Range(min=0))
    zoning = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    interior_condition = fields.Str(required=True, validate=validate.OneOf([
        'NEEDS_GUT', 'POOR', 'AVERAGE', 'NEW_RENO', 'HIGH_END'
    ]))
    latitude = fields.Float(allow_none=True)
    longitude = fields.Float(allow_none=True)
    data_source = fields.Str(allow_none=True)
    user_modified_fields = fields.List(fields.Str(), load_default=[])
    
    @validates_schema
    def validate_year_built(self, data, **kwargs):
        """Validate year built is within reasonable range."""
        year_built = data.get('year_built')
        if year_built and (year_built < 1800 or year_built > datetime.now().year):
            raise ValidationError(
                f'Year built must be between 1800 and {datetime.now().year}',
                field_name='year_built'
            )


class ComparableSchema(Schema):
    """Schema for comparable sale data."""
    address = fields.Str(required=True, validate=validate.Length(min=5, max=500))
    sale_date = fields.Date(required=True)
    sale_price = fields.Float(required=True, validate=validate.Range(min=0))
    property_type = fields.Str(required=True, validate=validate.OneOf([
        'SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL'
    ]))
    units = fields.Int(required=True, validate=validate.Range(min=1))
    bedrooms = fields.Int(required=True, validate=validate.Range(min=0))
    bathrooms = fields.Float(required=True, validate=validate.Range(min=0))
    square_footage = fields.Int(required=True, validate=validate.Range(min=1))
    lot_size = fields.Int(required=True, validate=validate.Range(min=0))
    year_built = fields.Int(required=True)
    construction_type = fields.Str(required=True, validate=validate.OneOf([
        'FRAME', 'BRICK', 'MASONRY', 'CONCRETE', 'STEEL'
    ]))
    interior_condition = fields.Str(required=True, validate=validate.OneOf([
        'NEEDS_GUT', 'POOR', 'AVERAGE', 'NEW_RENO', 'HIGH_END'
    ]))
    distance_miles = fields.Float(required=True, validate=validate.Range(min=0))
    latitude = fields.Float(allow_none=True)
    longitude = fields.Float(allow_none=True)


class UpdateComparablesSchema(Schema):
    """Schema for updating comparables (add or remove)."""
    action = fields.Str(required=True, validate=validate.OneOf(['add', 'remove']))
    comparable_id = fields.Int(allow_none=True)
    # Include all comparable fields for 'add' action
    address = fields.Str(allow_none=True)
    sale_date = fields.Date(allow_none=True)
    sale_price = fields.Float(allow_none=True)
    property_type = fields.Str(allow_none=True)
    units = fields.Int(allow_none=True)
    bedrooms = fields.Int(allow_none=True)
    bathrooms = fields.Float(allow_none=True)
    square_footage = fields.Int(allow_none=True)
    lot_size = fields.Int(allow_none=True)
    year_built = fields.Int(allow_none=True)
    construction_type = fields.Str(allow_none=True)
    interior_condition = fields.Str(allow_none=True)
    distance_miles = fields.Float(allow_none=True)
    latitude = fields.Float(allow_none=True)
    longitude = fields.Float(allow_none=True)
    
    @validates_schema
    def validate_action_data(self, data, **kwargs):
        """Validate required fields based on action."""
        action = data.get('action')
        
        if action == 'remove':
            if not data.get('comparable_id'):
                raise ValidationError('comparable_id is required for remove action')
        
        elif action == 'add':
            required_fields = [
                'address', 'sale_date', 'sale_price', 'property_type', 'units',
                'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
                'construction_type', 'interior_condition', 'distance_miles'
            ]
            for field in required_fields:
                if not data.get(field):
                    raise ValidationError(f'{field} is required for add action')


class AdvanceStepSchema(Schema):
    """Schema for advancing to next step."""
    approval_data = fields.Dict(allow_none=True, load_default=None)


class ExportGoogleSheetsSchema(Schema):
    """Schema for Google Sheets export."""
    credentials = fields.Dict(required=True)


# ---------------------------------------------------------------------------
# Lead Management Schemas
# ---------------------------------------------------------------------------

# Valid outreach statuses used across multiple schemas
VALID_OUTREACH_STATUSES = [
    'not_contacted', 'contacted', 'responded', 'converted', 'opted_out',
]

VALID_SORT_FIELDS = ['lead_score', 'created_at', 'property_street']
VALID_SORT_ORDERS = ['asc', 'desc']


class LeadListQuerySchema(Schema):
    """Schema for lead list query parameters (GET /api/leads/).

    Validates pagination bounds, filter parameters, and sort options.
    """
    # Pagination
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))

    # Filters
    property_type = fields.Str(load_default=None, validate=validate.Length(max=50))
    lead_category = fields.Str(load_default=None, validate=validate.OneOf(['residential', 'commercial']))
    city = fields.Str(load_default=None, validate=validate.Length(max=100))
    state = fields.Str(load_default=None, validate=validate.Length(max=50))
    zip = fields.Str(load_default=None, validate=validate.Length(max=20))
    owner_name = fields.Str(load_default=None, validate=validate.Length(max=255))
    score_min = fields.Float(load_default=None, validate=validate.Range(min=0, max=100))
    score_max = fields.Float(load_default=None, validate=validate.Range(min=0, max=100))
    marketing_list_id = fields.Int(load_default=None, validate=validate.Range(min=1))

    # Sorting
    sort_by = fields.Str(
        load_default='created_at',
        validate=validate.OneOf(VALID_SORT_FIELDS),
    )
    sort_order = fields.Str(
        load_default='desc',
        validate=validate.OneOf(VALID_SORT_ORDERS),
    )

    @validates_schema
    def validate_score_range(self, data, **kwargs):
        """Ensure score_min <= score_max when both are provided."""
        score_min = data.get('score_min')
        score_max = data.get('score_max')
        if score_min is not None and score_max is not None:
            if score_min > score_max:
                raise ValidationError(
                    'score_min must be less than or equal to score_max',
                    field_name='score_min',
                )


class LeadDetailResponseSchema(Schema):
    """Schema for serializing a full lead detail response."""
    id = fields.Int(dump_only=True)

    # Property details
    property_street = fields.Str()
    property_city = fields.Str(allow_none=True)
    property_state = fields.Str(allow_none=True)
    property_zip = fields.Str(allow_none=True)
    property_type = fields.Str(allow_none=True)
    bedrooms = fields.Int(allow_none=True)
    bathrooms = fields.Float(allow_none=True)
    square_footage = fields.Int(allow_none=True)
    lot_size = fields.Int(allow_none=True)
    year_built = fields.Int(allow_none=True)

    # Owner information
    owner_first_name = fields.Str()
    owner_last_name = fields.Str()
    ownership_type = fields.Str(allow_none=True)
    acquisition_date = fields.Date(allow_none=True)

    # Contact information
    phone_1 = fields.Str(allow_none=True)
    phone_2 = fields.Str(allow_none=True)
    phone_3 = fields.Str(allow_none=True)
    email_1 = fields.Str(allow_none=True)
    email_2 = fields.Str(allow_none=True)
    phone_4 = fields.Str(allow_none=True)
    phone_5 = fields.Str(allow_none=True)
    phone_6 = fields.Str(allow_none=True)
    phone_7 = fields.Str(allow_none=True)
    email_3 = fields.Str(allow_none=True)
    email_4 = fields.Str(allow_none=True)
    email_5 = fields.Str(allow_none=True)
    socials = fields.Str(allow_none=True)

    # Mailing information
    mailing_address = fields.Str(allow_none=True)
    mailing_city = fields.Str(allow_none=True)
    mailing_state = fields.Str(allow_none=True)
    mailing_zip = fields.Str(allow_none=True)
    address_2 = fields.Str(allow_none=True)
    returned_addresses = fields.Str(allow_none=True)

    # Additional property details
    units = fields.Int(allow_none=True)
    units_allowed = fields.Int(allow_none=True)
    zoning = fields.Str(allow_none=True)
    county_assessor_pin = fields.Str(allow_none=True)
    tax_bill_2021 = fields.Float(allow_none=True)
    most_recent_sale = fields.Str(allow_none=True)

    # Second owner
    owner_2_first_name = fields.Str(allow_none=True)
    owner_2_last_name = fields.Str(allow_none=True)

    # Research tracking
    source = fields.Str(allow_none=True)
    date_identified = fields.Date(allow_none=True)
    notes = fields.Str(allow_none=True)
    needs_skip_trace = fields.Bool(allow_none=True)
    skip_tracer = fields.Str(allow_none=True)
    date_skip_traced = fields.Date(allow_none=True)
    date_added_to_hubspot = fields.Date(allow_none=True)

    # Mailing tracking
    up_next_to_mail = fields.Bool(allow_none=True)
    mailer_history = fields.Dict(allow_none=True)

    # Scoring
    lead_score = fields.Float()

    # Classification
    lead_category = fields.Str()

    # Metadata
    data_source = fields.Str(allow_none=True)
    last_import_job_id = fields.Int(allow_none=True)
    created_at = fields.DateTime(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)

    # Analysis link
    analysis_session_id = fields.Int(allow_none=True)

    # Nested data
    enrichment_records = fields.List(fields.Dict(), dump_default=[])
    marketing_lists = fields.List(fields.Dict(), dump_default=[])
    analysis_session = fields.Dict(allow_none=True, dump_default=None)


class AnalyzeLeadRequestSchema(Schema):
    """Schema for starting an analysis session from a lead (POST /api/leads/{lead_id}/analyze)."""
    pass  # user_id is read from X-User-Id header


# ---------------------------------------------------------------------------
# Import Schemas
# ---------------------------------------------------------------------------

class ImportAuthRequestSchema(Schema):
    """Schema for Google OAuth2 authentication (POST /api/leads/import/auth).

    The credentials dict must contain either refresh_token + client_id/client_secret
    or auth_code + redirect_uri for the OAuth2 code-exchange flow.
    """
    credentials = fields.Dict(required=True)
    user_id = fields.Str(load_default='default', validate=validate.Length(min=1, max=255))

    @validates('credentials')
    def validate_credentials(self, value):
        """Ensure credentials dict is not empty."""
        if not value:
            raise ValidationError('credentials must not be empty')


class ImportSheetsQuerySchema(Schema):
    """Schema for listing available sheets (GET /api/leads/import/sheets)."""
    spreadsheet_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    user_id = fields.Str(load_default='default', validate=validate.Length(min=1, max=255))


class ImportHeadersQuerySchema(Schema):
    """Schema for reading headers from a sheet (GET /api/leads/import/headers)."""
    spreadsheet_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    sheet_name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    user_id = fields.Str(load_default='default', validate=validate.Length(min=1, max=255))


class FieldMappingRequestSchema(Schema):
    """Schema for saving/updating a field mapping (POST /api/leads/import/mapping).

    Validates that the mapping is a non-empty dict and that required database
    fields (property_street, owner_first_name, owner_last_name) are present as values in the mapping.
    """
    spreadsheet_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    sheet_name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    mapping = fields.Dict(keys=fields.Str(), values=fields.Str(), required=True)

    @validates('mapping')
    def validate_mapping_not_empty(self, value):
        """Ensure mapping dict is not empty."""
        if not value:
            raise ValidationError('mapping must not be empty')

    @validates_schema
    def validate_required_fields_mapped(self, data, **kwargs):
        """Ensure required database fields are present as values in the mapping."""
        mapping = data.get('mapping')
        if not mapping:
            return

        mapped_fields = set(mapping.values())
        required_fields = set()
        missing = required_fields - mapped_fields
        if missing:
            raise ValidationError(
                f'Required fields not mapped: {", ".join(sorted(missing))}',
                field_name='mapping',
            )


class ImportStartRequestSchema(Schema):
    """Schema for starting an import job (POST /api/leads/import/start)."""
    spreadsheet_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    sheet_name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    field_mapping_id = fields.Int(load_default=None, validate=validate.Range(min=1))
    lead_category = fields.Str(
        load_default='residential',
        validate=validate.OneOf(['residential', 'commercial']),
    )


class ImportJobsQuerySchema(Schema):
    """Schema for listing import jobs (GET /api/leads/import/jobs)."""
    user_id = fields.Str(load_default=None, validate=validate.Length(max=255))
    status = fields.Str(
        load_default=None,
        validate=validate.OneOf(['pending', 'in_progress', 'completed', 'failed']),
    )
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


# ---------------------------------------------------------------------------
# Scoring Schemas
# ---------------------------------------------------------------------------

class ScoringWeightsQuerySchema(Schema):
    """Schema for getting scoring weights (GET /api/leads/scoring/weights)."""
    user_id = fields.Str(load_default='default', validate=validate.Length(min=1, max=255))


class ScoringWeightsUpdateSchema(Schema):
    """Schema for updating scoring weights (PUT /api/leads/scoring/weights).

    Validates that all four weights are provided, are non-negative, and sum to 1.0.
    """
    property_characteristics_weight = fields.Float(
        required=True, validate=validate.Range(min=0.0, max=1.0),
    )
    data_completeness_weight = fields.Float(
        required=True, validate=validate.Range(min=0.0, max=1.0),
    )
    owner_situation_weight = fields.Float(
        required=True, validate=validate.Range(min=0.0, max=1.0),
    )
    location_desirability_weight = fields.Float(
        required=True, validate=validate.Range(min=0.0, max=1.0),
    )

    @validates_schema
    def validate_weights_sum(self, data, **kwargs):
        """Ensure all four weights sum to 1.0 (within floating-point tolerance)."""
        weight_fields = [
            'property_characteristics_weight',
            'data_completeness_weight',
            'owner_situation_weight',
            'location_desirability_weight',
        ]
        total = sum(data.get(f, 0.0) for f in weight_fields)
        if abs(total - 1.0) > 0.01:
            raise ValidationError(
                f'Scoring weights must sum to 1.0, got {total:.4f}',
                field_name='property_characteristics_weight',
            )


# ---------------------------------------------------------------------------
# Enrichment Schemas
# ---------------------------------------------------------------------------

class EnrichLeadRequestSchema(Schema):
    """Schema for enriching a single lead (POST /api/leads/{lead_id}/enrich)."""
    source_name = fields.Str(required=True, validate=validate.Length(min=1, max=100))


class BulkEnrichRequestSchema(Schema):
    """Schema for bulk enrichment (POST /api/leads/enrichment/bulk)."""
    lead_ids = fields.List(
        fields.Int(validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1),
    )
    source_name = fields.Str(required=True, validate=validate.Length(min=1, max=100))


# ---------------------------------------------------------------------------
# Marketing List Schemas
# ---------------------------------------------------------------------------

class MarketingListCreateSchema(Schema):
    """Schema for creating a marketing list (POST /api/leads/marketing/lists)."""
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    filter_criteria = fields.Dict(load_default=None)


class MarketingListRenameSchema(Schema):
    """Schema for renaming a marketing list (PUT /api/leads/marketing/lists/{list_id})."""
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))


class MarketingListMembersQuerySchema(Schema):
    """Schema for listing marketing list members (GET /api/leads/marketing/lists/{list_id}/members)."""
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=25, validate=validate.Range(min=1, max=100))


class MarketingListAddMembersSchema(Schema):
    """Schema for adding leads to a marketing list (POST /api/leads/marketing/lists/{list_id}/members)."""
    lead_ids = fields.List(
        fields.Int(validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1),
    )


class MarketingListRemoveMembersSchema(Schema):
    """Schema for removing leads from a marketing list (DELETE /api/leads/marketing/lists/{list_id}/members)."""
    lead_ids = fields.List(
        fields.Int(validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1),
    )


class OutreachStatusUpdateSchema(Schema):
    """Schema for updating outreach status (PUT /api/leads/marketing/lists/{list_id}/members/{lead_id}/status)."""
    status = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_OUTREACH_STATUSES),
    )


class MarketingListsQuerySchema(Schema):
    """Schema for listing marketing lists (GET /api/leads/marketing/lists)."""
    user_id = fields.Str(load_default=None, validate=validate.Length(max=255))
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=25, validate=validate.Range(min=1, max=100))


# ---------------------------------------------------------------------------
# Condo Filter Schemas
# ---------------------------------------------------------------------------

VALID_CONDO_RISK_STATUSES = [
    'likely_condo', 'likely_not_condo', 'partial_condo_possible', 'needs_review', 'unknown',
]

VALID_BUILDING_SALE_POSSIBLE = ['yes', 'no', 'maybe', 'unknown']


class CondoFilterResultsQuerySchema(Schema):
    """Query params for GET /api/condo-filter/results."""
    condo_risk_status = fields.Str(
        load_default=None,
        validate=validate.OneOf(VALID_CONDO_RISK_STATUSES),
    )
    building_sale_possible = fields.Str(
        load_default=None,
        validate=validate.OneOf(VALID_BUILDING_SALE_POSSIBLE),
    )
    manually_reviewed = fields.Bool(load_default=None)
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


class CondoFilterOverrideSchema(Schema):
    """Request body for PUT /api/condo-filter/results/<id>/override."""
    condo_risk_status = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_CONDO_RISK_STATUSES),
    )
    building_sale_possible = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_BUILDING_SALE_POSSIBLE),
    )
    reason = fields.Str(required=True, validate=validate.Length(min=1, max=1000))


# ---------------------------------------------------------------------------
# Multifamily Underwriting Schemas
# ---------------------------------------------------------------------------

VALID_OCCUPANCY_STATUSES = ['Occupied', 'Vacant', 'Down']
VALID_LENDER_TYPES = ['Construction_To_Perm', 'Self_Funded_Reno']
VALID_FUNDING_SOURCE_TYPES = ['Cash', 'HELOC_1', 'HELOC_2']


class DealCreateSchema(Schema):
    """Schema for creating a multifamily deal."""
    # Required fields
    property_address = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    unit_count = fields.Int(required=True, validate=validate.Range(min=5))
    purchase_price = fields.Float(required=True, validate=validate.Range(min=0, min_inclusive=False))
    close_date = fields.Date(required=True)

    # Optional fields
    property_city = fields.Str(load_default=None, validate=validate.Length(max=100))
    property_state = fields.Str(load_default=None, validate=validate.Length(max=50))
    property_zip = fields.Str(load_default=None, validate=validate.Length(max=20))
    closing_costs = fields.Float(load_default=0, validate=validate.Range(min=0))
    vacancy_rate = fields.Float(load_default=0.05, validate=validate.Range(min=0, max=1))
    other_income_monthly = fields.Float(load_default=0, validate=validate.Range(min=0))
    management_fee_rate = fields.Float(load_default=0.08, validate=validate.Range(min=0, max=0.30))
    reserve_per_unit_per_year = fields.Float(load_default=250, validate=validate.Range(min=0))
    property_taxes_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    insurance_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    utilities_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    repairs_and_maintenance_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    admin_and_marketing_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    payroll_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    other_opex_annual = fields.Float(load_default=None, validate=validate.Range(min=0))
    interest_reserve_amount = fields.Float(load_default=0, validate=validate.Range(min=0))
    custom_cap_rate = fields.Float(
        load_default=None, allow_none=True,
        validate=validate.Range(min=0, max=0.25),
    )
    status = fields.Str(load_default='draft', validate=validate.Length(max=50))


class DealUpdateSchema(Schema):
    """Schema for updating a multifamily deal (all fields optional)."""
    property_address = fields.Str(validate=validate.Length(min=1, max=500))
    unit_count = fields.Int(validate=validate.Range(min=5))
    purchase_price = fields.Float(validate=validate.Range(min=0, min_inclusive=False))
    close_date = fields.Date()
    property_city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    property_state = fields.Str(allow_none=True, validate=validate.Length(max=50))
    property_zip = fields.Str(allow_none=True, validate=validate.Length(max=20))
    closing_costs = fields.Float(validate=validate.Range(min=0))
    vacancy_rate = fields.Float(validate=validate.Range(min=0, max=1))
    other_income_monthly = fields.Float(validate=validate.Range(min=0))
    management_fee_rate = fields.Float(validate=validate.Range(min=0, max=0.30))
    reserve_per_unit_per_year = fields.Float(validate=validate.Range(min=0))
    property_taxes_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    insurance_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    utilities_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    repairs_and_maintenance_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    admin_and_marketing_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    payroll_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    other_opex_annual = fields.Float(allow_none=True, validate=validate.Range(min=0))
    interest_reserve_amount = fields.Float(validate=validate.Range(min=0))
    custom_cap_rate = fields.Float(
        allow_none=True,
        validate=validate.Range(min=0, max=0.25),
    )
    status = fields.Str(validate=validate.Length(max=50))


class DealResponseSchema(Schema):
    """Schema for serializing a deal response (dump only)."""
    id = fields.Int(dump_only=True)
    property_address = fields.Str(dump_only=True)
    property_city = fields.Str(dump_only=True, allow_none=True)
    property_state = fields.Str(dump_only=True, allow_none=True)
    property_zip = fields.Str(dump_only=True, allow_none=True)
    unit_count = fields.Int(dump_only=True)
    purchase_price = fields.Float(dump_only=True)
    closing_costs = fields.Float(dump_only=True)
    close_date = fields.Date(dump_only=True)
    vacancy_rate = fields.Float(dump_only=True)
    other_income_monthly = fields.Float(dump_only=True)
    management_fee_rate = fields.Float(dump_only=True)
    reserve_per_unit_per_year = fields.Float(dump_only=True)
    property_taxes_annual = fields.Float(dump_only=True, allow_none=True)
    insurance_annual = fields.Float(dump_only=True, allow_none=True)
    utilities_annual = fields.Float(dump_only=True, allow_none=True)
    repairs_and_maintenance_annual = fields.Float(dump_only=True, allow_none=True)
    admin_and_marketing_annual = fields.Float(dump_only=True, allow_none=True)
    payroll_annual = fields.Float(dump_only=True, allow_none=True)
    other_opex_annual = fields.Float(dump_only=True, allow_none=True)
    interest_reserve_amount = fields.Float(dump_only=True)
    custom_cap_rate = fields.Float(dump_only=True, allow_none=True)
    status = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True, allow_none=True)
    deleted_at = fields.DateTime(dump_only=True, allow_none=True)
    # Include units list for Req 1.4 (complete Deal record)
    units = fields.Method('get_units', dump_only=True)
    # Include rent roll entries so the frontend can display current rents without a second request
    rent_roll_entries = fields.Method('get_rent_roll_entries', dump_only=True)
    # Include rehab plan entries for the Rehab Plan tab
    rehab_plan_entries = fields.Method('get_rehab_plan_entries', dump_only=True)
    # Include lender selections for the Lenders tab
    lender_selections = fields.Method('get_lender_selections', dump_only=True)
    # Include funding sources for the Funding tab
    funding_sources = fields.Method('get_funding_sources', dump_only=True)

    def get_units(self, deal):
        """Return the list of units for this deal."""
        unit_list = deal.units.all() if hasattr(deal.units, 'all') else list(deal.units)
        return [
            {
                'id': u.id,
                'deal_id': u.deal_id,
                'unit_identifier': u.unit_identifier,
                'unit_type': u.unit_type,
                'beds': u.beds,
                'baths': float(u.baths) if u.baths is not None else None,
                'sqft': u.sqft,
                'occupancy_status': u.occupancy_status,
            }
            for u in unit_list
        ]

    def get_rent_roll_entries(self, deal):
        """Return rent roll entries for all units in this deal."""
        unit_list = deal.units.all() if hasattr(deal.units, 'all') else list(deal.units)
        entries = []
        for u in unit_list:
            rr = u.rent_roll_entry
            if rr is not None:
                entries.append({
                    'id': rr.id,
                    'unit_id': rr.unit_id,
                    'current_rent': str(rr.current_rent) if rr.current_rent is not None else None,
                    'lease_start_date': rr.lease_start_date.isoformat() if rr.lease_start_date else None,
                    'lease_end_date': rr.lease_end_date.isoformat() if rr.lease_end_date else None,
                    'notes': rr.notes,
                })
        return entries

    def get_rehab_plan_entries(self, deal):
        """Return rehab plan entries for all units in this deal."""
        unit_list = deal.units.all() if hasattr(deal.units, 'all') else list(deal.units)
        entries = []
        for u in unit_list:
            rpe = u.rehab_plan_entry
            if rpe is not None:
                entries.append({
                    'id': rpe.id,
                    'unit_id': rpe.unit_id,
                    'renovate_flag': rpe.renovate_flag,
                    'current_rent': float(rpe.current_rent) if rpe.current_rent is not None else None,
                    'suggested_post_reno_rent': float(rpe.suggested_post_reno_rent) if rpe.suggested_post_reno_rent is not None else None,
                    'underwritten_post_reno_rent': float(rpe.underwritten_post_reno_rent) if rpe.underwritten_post_reno_rent is not None else None,
                    'rehab_start_month': rpe.rehab_start_month,
                    'downtime_months': rpe.downtime_months,
                    'stabilized_month': rpe.stabilized_month,
                    'rehab_budget': float(rpe.rehab_budget) if rpe.rehab_budget is not None else None,
                    'scope_notes': rpe.scope_notes,
                    'stabilizes_after_horizon': rpe.stabilizes_after_horizon,
                })
        return entries

    def get_lender_selections(self, deal):
        """Return lender selections for this deal."""
        selections = deal.lender_selections.all() if hasattr(deal.lender_selections, 'all') else list(deal.lender_selections)
        return [
            {
                'id': s.id,
                'deal_id': s.deal_id,
                'lender_profile_id': s.lender_profile_id,
                'scenario': s.scenario,
                'is_primary': s.is_primary,
            }
            for s in selections
        ]

    def get_funding_sources(self, deal):
        """Return funding sources for this deal."""
        sources = deal.funding_sources.all() if hasattr(deal.funding_sources, 'all') else list(deal.funding_sources)
        return [
            {
                'id': s.id,
                'deal_id': s.deal_id,
                'source_type': s.source_type,
                'total_available': float(s.total_available) if s.total_available is not None else None,
                'interest_rate': float(s.interest_rate) if s.interest_rate is not None else None,
                'origination_fee_rate': float(s.origination_fee_rate) if s.origination_fee_rate is not None else None,
            }
            for s in sources
        ]


class UnitCreateSchema(Schema):
    """Schema for adding a unit to a deal."""
    unit_identifier = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    unit_type = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    beds = fields.Int(required=True, validate=validate.Range(min=0))
    baths = fields.Float(required=True, validate=validate.Range(min=0))
    sqft = fields.Int(required=True, validate=validate.Range(min=1))
    occupancy_status = fields.Str(
        required=True,
        validate=validate.OneOf(VALID_OCCUPANCY_STATUSES),
    )


class UnitUpdateSchema(Schema):
    """Schema for updating a unit (all fields optional)."""
    unit_identifier = fields.Str(validate=validate.Length(min=1, max=50))
    unit_type = fields.Str(validate=validate.Length(min=1, max=50))
    beds = fields.Int(validate=validate.Range(min=0))
    baths = fields.Float(validate=validate.Range(min=0))
    sqft = fields.Int(validate=validate.Range(min=1))
    occupancy_status = fields.Str(validate=validate.OneOf(VALID_OCCUPANCY_STATUSES))


class RentRollEntrySchema(Schema):
    """Schema for setting a rent roll entry on a unit."""
    current_rent = fields.Float(required=True, validate=validate.Range(min=0))
    lease_start_date = fields.Date(load_default=None)
    lease_end_date = fields.Date(load_default=None)
    notes = fields.Str(load_default=None)

    @validates_schema
    def validate_lease_dates(self, data, **kwargs):
        """Enforce lease_end_date >= lease_start_date when both are provided."""
        start = data.get('lease_start_date')
        end = data.get('lease_end_date')
        if start is not None and end is not None:
            if end < start:
                raise ValidationError(
                    'lease_end_date must be on or after lease_start_date',
                    field_name='lease_end_date',
                )


class MarketRentAssumptionSchema(Schema):
    """Schema for setting a market rent assumption for a unit type."""
    unit_type = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    target_rent = fields.Float(load_default=None, validate=validate.Range(min=0))
    post_reno_target_rent = fields.Float(load_default=None, validate=validate.Range(min=0))


class RentCompCreateSchema(Schema):
    """Schema for adding a rent comparable."""
    address = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    unit_type = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    observed_rent = fields.Float(required=True, validate=validate.Range(min=0))
    sqft = fields.Int(required=True, validate=validate.Range(min=1))
    observation_date = fields.Date(required=True)
    neighborhood = fields.Str(load_default=None, validate=validate.Length(max=200))
    source_url = fields.Str(load_default=None, validate=validate.Length(max=1000))


class RentCompResponseSchema(Schema):
    """Schema for serializing a rent comp response (dump only)."""
    id = fields.Int(dump_only=True)
    address = fields.Str(dump_only=True)
    unit_type = fields.Str(dump_only=True)
    observed_rent = fields.Float(dump_only=True)
    sqft = fields.Int(dump_only=True)
    observation_date = fields.Date(dump_only=True)
    neighborhood = fields.Str(dump_only=True, allow_none=True)
    source_url = fields.Str(dump_only=True, allow_none=True)
    rent_per_sqft = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class SaleCompCreateSchema(Schema):
    """Schema for adding a sale comparable."""
    address = fields.Str(required=True, validate=validate.Length(min=1, max=500))
    unit_count = fields.Int(required=True, validate=validate.Range(min=1))
    sale_price = fields.Float(required=True, validate=validate.Range(min=0, min_inclusive=False))
    close_date = fields.Date(required=True)
    # observed_cap_rate is now optional — many comps don't have cap rate data.
    # If omitted but noi is provided, cap rate will be derived as noi / sale_price.
    observed_cap_rate = fields.Float(
        load_default=None,
        allow_none=True,
        validate=validate.Range(min=0, max=0.25),
    )
    # Annual NOI — used to derive cap rate when observed_cap_rate is not provided
    noi = fields.Float(load_default=None, allow_none=True, validate=validate.Range(min=0))
    status = fields.Str(load_default=None, validate=validate.Length(max=50))
    distance_miles = fields.Float(load_default=None, validate=validate.Range(min=0))


class SaleCompResponseSchema(Schema):
    """Schema for serializing a sale comp response (dump only)."""
    id = fields.Int(dump_only=True)
    address = fields.Str(dump_only=True)
    unit_count = fields.Int(dump_only=True)
    sale_price = fields.Float(dump_only=True)
    close_date = fields.Date(dump_only=True)
    observed_cap_rate = fields.Float(dump_only=True)
    status = fields.Str(dump_only=True, allow_none=True)
    distance_miles = fields.Float(dump_only=True, allow_none=True)
    observed_ppu = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class RehabPlanEntrySchema(Schema):
    """Schema for setting a rehab plan entry on a unit."""
    renovate_flag = fields.Bool(required=True)
    current_rent = fields.Float(load_default=None, validate=validate.Range(min=0))
    suggested_post_reno_rent = fields.Float(load_default=None, validate=validate.Range(min=0))
    underwritten_post_reno_rent = fields.Float(load_default=None, validate=validate.Range(min=0))
    rehab_start_month = fields.Int(load_default=None, validate=validate.Range(min=1, max=24))
    downtime_months = fields.Int(load_default=None, validate=validate.Range(min=0))
    rehab_budget = fields.Float(load_default=None, validate=validate.Range(min=0))
    scope_notes = fields.Str(load_default=None)


class LenderProfileCreateSchema(Schema):
    """Schema for creating a lender profile."""
    # Common required fields
    company = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    lender_type = fields.Str(required=True, validate=validate.OneOf(VALID_LENDER_TYPES))
    origination_fee_rate = fields.Float(required=True, validate=validate.Range(min=0, max=0.30))

    # Common optional
    prepay_penalty_description = fields.Str(load_default=None)

    # Construction_To_Perm fields
    ltv_total_cost = fields.Float(load_default=None, validate=validate.Range(min=0, max=1))
    construction_rate = fields.Float(load_default=None, validate=validate.Range(min=0, max=0.30))
    construction_io_months = fields.Int(load_default=None, validate=validate.Range(min=1))
    construction_term_months = fields.Int(load_default=None, validate=validate.Range(min=1))
    perm_rate = fields.Float(load_default=None, validate=validate.Range(min=0, max=0.30))
    perm_amort_years = fields.Int(load_default=None, validate=validate.Range(min=1))
    min_interest_or_yield = fields.Float(load_default=None, validate=validate.Range(min=0))

    # Self_Funded_Reno fields
    max_purchase_ltv = fields.Float(load_default=None, validate=validate.Range(min=0, max=1))
    treasury_5y_rate = fields.Float(load_default=None, validate=validate.Range(min=0, max=0.30))
    spread_bps = fields.Int(load_default=None, validate=validate.Range(min=0))
    term_years = fields.Int(load_default=None, validate=validate.Range(min=1))
    amort_years = fields.Int(load_default=None, validate=validate.Range(min=1))

    @validates_schema
    def validate_lender_type_fields(self, data, **kwargs):
        """Enforce required fields based on lender_type."""
        lender_type = data.get('lender_type')

        if lender_type == 'Construction_To_Perm':
            required_fields = [
                'ltv_total_cost', 'construction_rate', 'construction_io_months',
                'construction_term_months', 'perm_rate', 'perm_amort_years',
            ]
            for field_name in required_fields:
                if data.get(field_name) is None:
                    raise ValidationError(
                        f'{field_name} is required for Construction_To_Perm lender type',
                        field_name=field_name,
                    )

        elif lender_type == 'Self_Funded_Reno':
            required_fields = [
                'max_purchase_ltv', 'treasury_5y_rate', 'spread_bps',
                'term_years', 'amort_years',
            ]
            for field_name in required_fields:
                if data.get(field_name) is None:
                    raise ValidationError(
                        f'{field_name} is required for Self_Funded_Reno lender type',
                        field_name=field_name,
                    )


class DealLenderSelectionSchema(Schema):
    """Schema for attaching a lender profile to a deal scenario."""
    lender_profile_id = fields.Int(required=True, validate=validate.Range(min=1))
    is_primary = fields.Bool(load_default=False)


class FundingSourceSchema(Schema):
    """Schema for adding or updating a funding source on a deal."""
    source_type = fields.Str(required=True, validate=validate.OneOf(VALID_FUNDING_SOURCE_TYPES))
    total_available = fields.Float(required=True, validate=validate.Range(min=0))
    interest_rate = fields.Float(load_default=0, validate=validate.Range(min=0, max=0.30))
    origination_fee_rate = fields.Float(load_default=0, validate=validate.Range(min=0, max=0.30))


# ---------------------------------------------------------------------------
# OM Intake schemas
# ---------------------------------------------------------------------------

class ScenarioMetricsSchema(Schema):
    """Schema for a single scenario's computed metrics."""
    gross_potential_income_annual = fields.Decimal(allow_none=True)
    effective_gross_income_annual = fields.Decimal(allow_none=True)
    gross_expenses_annual = fields.Decimal(allow_none=True)
    noi_annual = fields.Decimal(allow_none=True)
    cap_rate = fields.Decimal(allow_none=True)
    grm = fields.Decimal(allow_none=True)
    monthly_rent_total = fields.Decimal(allow_none=True)
    dscr = fields.Decimal(allow_none=True)
    cash_on_cash = fields.Decimal(allow_none=True)


class UnitMixComparisonRowSchema(Schema):
    """Schema for a single row in the unit mix comparison table."""
    unit_type_label = fields.Str()
    unit_count = fields.Int()
    sqft = fields.Decimal(allow_none=True)
    current_avg_rent = fields.Decimal(allow_none=True)
    proforma_rent = fields.Decimal(allow_none=True)
    market_rent_estimate = fields.Decimal(allow_none=True)
    market_rent_low = fields.Decimal(allow_none=True)
    market_rent_high = fields.Decimal(allow_none=True)


class ScenarioComparisonSchema(Schema):
    """Schema for the three-scenario comparison result."""
    broker_current = fields.Nested(ScenarioMetricsSchema)
    broker_proforma = fields.Nested(ScenarioMetricsSchema)
    realistic = fields.Nested(ScenarioMetricsSchema)
    unit_mix_comparison = fields.List(fields.Nested(UnitMixComparisonRowSchema))
    significant_variance_flag = fields.Bool(allow_none=True)
    realistic_cap_rate_below_proforma = fields.Bool(allow_none=True)


class OMIntakeJobStatusSchema(Schema):
    """Schema for job status responses (GET /jobs/{id})."""
    id = fields.Int()
    intake_status = fields.Str()
    original_filename = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    expires_at = fields.DateTime()
    error_message = fields.Str(allow_none=True)
    deal_id = fields.Int(allow_none=True)


class OMIntakeJobListSchema(Schema):
    """Schema for job list items (GET /jobs)."""
    id = fields.Int()
    intake_status = fields.Str()
    original_filename = fields.Str()
    created_at = fields.DateTime()
    deal_id = fields.Int(allow_none=True)
    # Summary fields from extracted_om_data
    property_address = fields.Str(allow_none=True)
    asking_price = fields.Decimal(allow_none=True)
    unit_count = fields.Int(allow_none=True)


class OMIntakeReviewSchema(Schema):
    """Schema for full review data (GET /jobs/{id}/review)."""
    id = fields.Int()
    intake_status = fields.Str()
    original_filename = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    extracted_om_data = fields.Raw(allow_none=True)
    scenario_comparison = fields.Raw(allow_none=True)
    consistency_warnings = fields.Raw(allow_none=True)
    market_research_warnings = fields.Raw(allow_none=True)
    partial_realistic_scenario_warning = fields.Bool(allow_none=True)
    asking_price_missing_error = fields.Bool(allow_none=True)
    unit_count_missing_error = fields.Bool(allow_none=True)
    deal_id = fields.Int(allow_none=True)


class OMIntakeJobSchema(Schema):
    """Schema for full job serialization."""
    id = fields.Int()
    user_id = fields.Str()
    intake_status = fields.Str()
    original_filename = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    expires_at = fields.DateTime()
    error_message = fields.Str(allow_none=True)
    deal_id = fields.Int(allow_none=True)


class OMIntakeConfirmRequestSchema(RequestSchema):
    """Schema for the confirm request body (POST /jobs/{id}/confirm)."""

    asking_price = fields.Decimal(allow_none=True)
    unit_count = fields.Int(allow_none=True)
    unit_mix = fields.List(fields.Raw(), allow_none=True)
    expense_items = fields.List(fields.Raw(), allow_none=True)
    other_income_items = fields.List(fields.Raw(), allow_none=True)
    property_address = fields.Str(allow_none=True)
    property_city = fields.Str(allow_none=True)
    property_state = fields.Str(allow_none=True)
    property_zip = fields.Str(allow_none=True)

