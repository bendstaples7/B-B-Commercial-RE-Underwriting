"""PropertyFacts model."""
from app import db
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import JSON
from datetime import date
import enum

class PropertyType(enum.Enum):
    """Property type enumeration."""
    SINGLE_FAMILY = 'single_family'
    MULTI_FAMILY = 'multi_family'
    COMMERCIAL = 'commercial'

class ConstructionType(enum.Enum):
    """Construction type enumeration."""
    FRAME = 'frame'
    BRICK = 'brick'
    MASONRY = 'masonry'

class InteriorCondition(enum.Enum):
    """Interior condition enumeration."""
    NEEDS_GUT = 'needs_gut'
    POOR = 'poor'
    AVERAGE = 'average'
    NEW_RENO = 'new_reno'
    HIGH_END = 'high_end'

class PropertyFacts(db.Model):
    """Property facts model with comprehensive property details."""
    __tablename__ = 'property_facts'
    
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(500), nullable=False, index=True)
    property_type = db.Column(db.Enum(PropertyType), nullable=False)
    units = db.Column(db.Integer, nullable=False)
    bedrooms = db.Column(db.Integer, nullable=False)
    bathrooms = db.Column(db.Float, nullable=False)
    square_footage = db.Column(db.Integer, nullable=False)
    lot_size = db.Column(db.Integer, nullable=False)  # in square feet
    year_built = db.Column(db.Integer, nullable=False)
    construction_type = db.Column(db.Enum(ConstructionType), nullable=False)
    basement = db.Column(db.Boolean, nullable=False, default=False)
    parking_spaces = db.Column(db.Integer, nullable=False, default=0)
    last_sale_price = db.Column(db.Float, nullable=True)
    last_sale_date = db.Column(db.Date, nullable=True)
    assessed_value = db.Column(db.Float, nullable=False)
    annual_taxes = db.Column(db.Float, nullable=False)
    zoning = db.Column(db.String(50), nullable=False)
    interior_condition = db.Column(db.Enum(InteriorCondition), nullable=False)
    
    # Geocoding coordinates
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Metadata
    data_source = db.Column(db.String(100), nullable=True)
    # Use JSON for cross-database compatibility (works with both PostgreSQL and SQLite)
    user_modified_fields = db.Column(JSON, nullable=True, default=list)
    
    # Relationship to analysis sessions
    session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=True)
    
    def __repr__(self):
        return f'<PropertyFacts {self.address}>'
