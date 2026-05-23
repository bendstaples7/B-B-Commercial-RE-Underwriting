"""HubSpotWebhookLog model for tracking incoming HubSpot webhook events."""
from datetime import datetime
from app import db


class HubSpotWebhookLog(db.Model):
    __tablename__ = 'hubspot_webhook_logs'

    id = db.Column(db.Integer, primary_key=True)
    hubspot_object_type = db.Column(db.String(50), nullable=False)  # deal, contact, company, engagement
    hubspot_object_id = db.Column(db.String(50), nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False)  # deal.creation, deal.propertyChange, etc.
    subscription_type = db.Column(db.String(100), nullable=True)  # raw HubSpot subscriptionType field
    raw_payload = db.Column(db.JSON, nullable=False)  # full event object
    status = db.Column(db.Enum(
        'pending', 'processing', 'processed', 'failed',
        'deduplicated', 'loop_suppressed',
        name='webhook_log_status_enum'
    ), nullable=False, default='pending')
    error_message = db.Column(db.Text, nullable=True)
    superseded_by_log_id = db.Column(db.Integer, db.ForeignKey('hubspot_webhook_logs.id'), nullable=True)
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_webhook_log_object', 'hubspot_object_type', 'hubspot_object_id'),
        db.Index('ix_webhook_log_status', 'status'),
        db.Index('ix_webhook_log_received', 'received_at'),
    )

    def __repr__(self):
        return f'<HubSpotWebhookLog id={self.id} type={self.hubspot_object_type} status={self.status}>'
