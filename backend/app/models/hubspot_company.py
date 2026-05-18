"""HubSpotCompany model for storing raw HubSpot company (organization) records."""
from app import db
from datetime import datetime


class HubSpotCompany(db.Model):
    """Stores raw HubSpot company payloads imported from the HubSpot CRM API."""
    __tablename__ = 'hubspot_companies'

    id = db.Column(db.Integer, primary_key=True)
    hubspot_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    raw_payload = db.Column(db.JSON, nullable=False)
    import_run_id = db.Column(db.Integer, db.ForeignKey('hubspot_import_runs.id'), nullable=True)
    first_imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotCompany {self.id} hubspot_id={self.hubspot_id}>'
