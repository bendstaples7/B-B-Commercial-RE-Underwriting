"""HubSpotImportRun model for tracking HubSpot CRM data import runs."""
from app import db
from datetime import datetime


class HubSpotImportRun(db.Model):
    """Tracks each HubSpot CRM import run, recording status and per-object-type counts."""
    __tablename__ = 'hubspot_import_runs'

    id = db.Column(db.Integer, primary_key=True)
    object_type = db.Column(db.String(50), nullable=False)  # deals, contacts, companies, engagements
    status = db.Column(db.Enum(
        'running', 'success', 'partial', 'failed',
        name='import_run_status_enum'
    ), nullable=False, default='running')
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    total_fetched = db.Column(db.Integer, nullable=False, default=0)
    created_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<HubSpotImportRun {self.id} object_type={self.object_type} status={self.status}>'
