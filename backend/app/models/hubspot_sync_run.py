"""HubSpotSyncRun model for tracking individual record sync operations."""
from datetime import datetime
from app import db


class HubSpotSyncRun(db.Model):
    __tablename__ = 'hubspot_sync_runs'

    id = db.Column(db.Integer, primary_key=True)
    trigger = db.Column(db.String(50), nullable=False, default='webhook')  # 'webhook' | 'manual'
    object_type = db.Column(db.String(50), nullable=False)
    hubspot_id = db.Column(db.String(50), nullable=False)
    upsert_result = db.Column(db.String(20), nullable=True)  # 'created' | 'updated'
    webhook_log_id = db.Column(db.Integer, db.ForeignKey('hubspot_webhook_logs.id'), nullable=True)
    processed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotSyncRun id={self.id} object_type={self.object_type} hubspot_id={self.hubspot_id}>'
