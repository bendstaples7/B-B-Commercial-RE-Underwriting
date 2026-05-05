"""Marshmallow schemas for request validation."""
from marshmallow import Schema, fields, validate, ValidationError, validates_schema, validates
from datetime import datetime


class StartAnalysisSchema(Schema):
    """Schema for starting a new analysis."""
    address = fields.Str(required=True, validate=validate.Length(min=5, max=500))
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))


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
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))


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
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
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
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
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
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
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
    user_id = fields.Str(required=True, validate=validate.Length(min=1, max=255))
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
