"""HubSpotDeal model for storing imported HubSpot deal records."""
from app import db
from datetime import datetime


class HubSpotDeal(db.Model):
    """Stores raw HubSpot deal records imported from the CRM."""
    __tablename__ = 'hubspot_deals'

    id = db.Column(db.Integer, primary_key=True)
    hubspot_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    raw_payload = db.Column(db.JSON, nullable=False)
    import_run_id = db.Column(db.Integer, db.ForeignKey('hubspot_import_runs.id'), nullable=True)
    first_imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    import_run = db.relationship('HubSpotImportRun', backref='deals')

    def __repr__(self):
        return f'<HubSpotDeal hubspot_id={self.hubspot_id}>'
