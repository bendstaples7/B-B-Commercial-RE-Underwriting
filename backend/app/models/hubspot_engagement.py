"""HubSpotEngagement model for storing raw HubSpot engagement records."""
from app import db
from datetime import datetime


class HubSpotEngagement(db.Model):
    """Stores raw HubSpot engagement records (notes, calls, tasks) with their payloads."""
    __tablename__ = 'hubspot_engagements'

    id = db.Column(db.Integer, primary_key=True)
    hubspot_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    engagement_type = db.Column(db.String(50), nullable=False)  # NOTE, CALL, TASK
    raw_payload = db.Column(db.JSON, nullable=False)
    import_run_id = db.Column(db.Integer, db.ForeignKey('hubspot_import_runs.id'), nullable=True)
    first_imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotEngagement {self.id} hubspot_id={self.hubspot_id} type={self.engagement_type}>'
