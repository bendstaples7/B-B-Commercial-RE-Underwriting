"""ValuationResult model."""
from app import db
from sqlalchemy import JSON

class ValuationResult(db.Model):
    """Valuation result with ARV range and comparable valuations."""
    __tablename__ = 'valuation_results'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=False, unique=True, index=True)
    
    # ARV Range (25th, 50th, 75th percentiles)
    conservative_arv = db.Column(db.Float, nullable=False)  # 25th percentile
    likely_arv = db.Column(db.Float, nullable=False)  # median
    aggressive_arv = db.Column(db.Float, nullable=False)  # 75th percentile
    
    # All valuation estimates (stored as JSON array)
    all_valuations = db.Column(JSON, nullable=False)
    
    # Key drivers (stored as JSON array of strings)
    key_drivers = db.Column(JSON, nullable=True)
    
    # Relationship to comparable valuations
    comparable_valuations = db.relationship('ComparableValuation', backref='valuation_result', lazy='dynamic')
    
    def __repr__(self):
        return f'<ValuationResult ARV: ${self.conservative_arv:.0f} - ${self.likely_arv:.0f} - ${self.aggressive_arv:.0f}>'

class ComparableValuation(db.Model):
    """Individual comparable valuation with adjustments."""
    __tablename__ = 'comparable_valuations'
    
    id = db.Column(db.Integer, primary_key=True)
    valuation_result_id = db.Column(db.Integer, db.ForeignKey('valuation_results.id'), nullable=False, index=True)
    comparable_id = db.Column(db.Integer, db.ForeignKey('comparable_sales.id'), nullable=False)
    
    # Valuation methods
    price_per_sqft = db.Column(db.Float, nullable=False)
    price_per_unit = db.Column(db.Float, nullable=False)
    price_per_bedroom = db.Column(db.Float, nullable=False)
    adjusted_value = db.Column(db.Float, nullable=False)
    
    # Adjustments (stored as JSON array of adjustment objects)
    adjustments = db.Column(JSON, nullable=True)
    
    # Narrative summary
    narrative = db.Column(db.Text, nullable=True)
    
    # Relationship
    comparable = db.relationship('ComparableSale', backref='valuations')
    
    def __repr__(self):
        return f'<ComparableValuation Adjusted: ${self.adjusted_value:.0f}>'
