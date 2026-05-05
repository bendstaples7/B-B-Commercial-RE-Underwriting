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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ScoringWeights user={self.user_id}>'
