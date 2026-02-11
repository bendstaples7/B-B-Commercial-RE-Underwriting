"""Marshmallow schemas for request validation."""
from marshmallow import Schema, fields, validate, ValidationError, validates_schema
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
