"""LeadScore model for storing versioned lead score records."""
from datetime import datetime
from app import db


class LeadScore(db.Model):
    """Stores a versioned score record for a lead with full breakdown.

    Each recalculation creates a new row, preserving full score history.
    """
    __tablename__ = 'lead_scores'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    property_id = db.Column(db.Integer, nullable=True)
    score_version = db.Column(db.String(50), nullable=False)
    total_score = db.Column(db.Float, nullable=False)
    score_tier = db.Column(db.String(1), nullable=False)
    data_quality_score = db.Column(db.Float, nullable=False)
    recommended_action = db.Column(db.String(50), nullable=False)
    top_signals = db.Column(db.JSON, nullable=False, default=list)
    score_details = db.Column(db.JSON, nullable=False, default=dict)
    missing_data = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    lead = db.relationship(
        'Lead',
        backref=db.backref('score_records', lazy='dynamic', order_by='LeadScore.created_at.desc()')
    )

    def __repr__(self):
        return f'<LeadScore lead_id={self.lead_id} tier={self.score_tier} score={self.total_score}>'
