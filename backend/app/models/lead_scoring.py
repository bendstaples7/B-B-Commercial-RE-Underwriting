"""ScoringWeights model."""
from app import db
from datetime import datetime


class ScoringWeights(db.Model):
    """Scoring weights model for configurable lead scoring criteria."""
    __tablename__ = 'scoring_weights'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, unique=True)
    property_characteristics_weight = db.Column(db.Float, nullable=False, default=0.30)
    data_completeness_weight = db.Column(db.Float, nullable=False, default=0.20)
    owner_situation_weight = db.Column(db.Float, nullable=False, default=0.30)
    location_desirability_weight = db.Column(db.Float, nullable=False, default=0.20)
    # Minimum number of comparable sales required before the user is warned
    # during the COMPARABLE_REVIEW step.  Defaults to 10 (production standard).
    # Users can lower this to proceed with fewer comparables when data is sparse.
    min_comparables = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ScoringWeights user={self.user_id}>'
