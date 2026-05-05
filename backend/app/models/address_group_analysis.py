"""AddressGroupAnalysis model for condo filter analysis results."""
from app import db
from datetime import datetime


class AddressGroupAnalysis(db.Model):
    """Stores per-building condo filter analysis results."""
    __tablename__ = 'address_group_analyses'

    id = db.Column(db.Integer, primary_key=True)
    normalized_address = db.Column(db.String(500), unique=True, nullable=False, index=True)
    source_type = db.Column(db.String(50), nullable=True)

    # Computed metrics
    property_count = db.Column(db.Integer, nullable=False, default=0)
    pin_count = db.Column(db.Integer, nullable=False, default=0)
    owner_count = db.Column(db.Integer, nullable=False, default=0)
    has_unit_number = db.Column(db.Boolean, nullable=False, default=False)
    has_condo_language = db.Column(db.Boolean, nullable=False, default=False)
    missing_pin_count = db.Column(db.Integer, nullable=False, default=0)
    missing_owner_count = db.Column(db.Integer, nullable=False, default=0)

    # Classification results
    condo_risk_status = db.Column(db.String(50), nullable=False, index=True)
    building_sale_possible = db.Column(db.String(50), nullable=False)
    analysis_details = db.Column(db.JSON, nullable=True)

    # Manual override
    manually_reviewed = db.Column(db.Boolean, nullable=False, default=False)
    manual_override_status = db.Column(db.String(50), nullable=True)
    manual_override_reason = db.Column(db.Text, nullable=True)

    # Timestamps
    analyzed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    leads = db.relationship('Lead', backref='condo_analysis', lazy='dynamic')

    def __repr__(self):
        return f'<AddressGroupAnalysis {self.normalized_address} ({self.condo_risk_status})>'
