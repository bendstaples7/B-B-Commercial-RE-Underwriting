"""ComparableSale model."""
from app import db
from app.models.property_facts import PropertyType, ConstructionType, InteriorCondition
from datetime import date

class ComparableSale(db.Model):
    """Comparable sale model with sale data and similarity metrics."""
    __tablename__ = 'comparable_sales'
    
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(500), nullable=False, index=True)
    sale_date = db.Column(db.Date, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    property_type = db.Column(
        db.Enum(PropertyType, values_callable=lambda x: [e.value for e in x], name='property_type'),
        nullable=False
    )
    units = db.Column(db.Integer, nullable=False)
    bedrooms = db.Column(db.Integer, nullable=False)
    bathrooms = db.Column(db.Float, nullable=False)
    square_footage = db.Column(db.Integer, nullable=False)
    lot_size = db.Column(db.Integer, nullable=False)
    year_built = db.Column(db.Integer, nullable=False)
    construction_type = db.Column(
        db.Enum(ConstructionType, values_callable=lambda x: [e.value for e in x], name='construction_type'),
        nullable=False
    )
    interior_condition = db.Column(
        db.Enum(InteriorCondition, values_callable=lambda x: [e.value for e in x], name='interior_condition'),
        nullable=False
    )
    
    # Distance from subject property
    distance_miles = db.Column(db.Float, nullable=False)
    
    # Geocoding coordinates
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Similarity notes
    similarity_notes = db.Column(db.Text, nullable=True)
    
    # Relationship to analysis session
    session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=False, index=True)
    
    def __repr__(self):
        return f'<ComparableSale {self.address} - ${self.sale_price}>'
