"""HubSpotMatch model for tracking record matching between HubSpot and internal data."""
from app import db
from datetime import datetime


class HubSpotMatch(db.Model):
    """Tracks the match status between a HubSpot record and an internal record."""
    __tablename__ = 'hubspot_matches'

    id = db.Column(db.Integer, primary_key=True)
    hubspot_record_type = db.Column(db.String(50), nullable=False)  # deal, contact, company
    hubspot_id = db.Column(db.String(50), nullable=False, index=True)
    internal_record_type = db.Column(db.String(50), nullable=True)  # lead, organization
    internal_record_id = db.Column(db.Integer, nullable=True)
    confidence = db.Column(db.Enum(
        'HIGH', 'MEDIUM', 'LOW', 'UNMATCHED',
        name='match_confidence_enum'
    ), nullable=False)
    status = db.Column(db.Enum(
        'pending', 'confirmed', 'rejected',
        name='match_status_enum'
    ), nullable=False, default='pending')
    matching_criteria = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('hubspot_record_type', 'hubspot_id', name='uq_hubspot_match'),
    )

    def __repr__(self):
        return (
            f'<HubSpotMatch id={self.id} hubspot_record_type={self.hubspot_record_type} '
            f'hubspot_id={self.hubspot_id} confidence={self.confidence} status={self.status}>'
        )
