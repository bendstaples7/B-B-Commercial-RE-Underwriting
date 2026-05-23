"""HubSpotConfig model for storing HubSpot API credentials."""
from app import db
from datetime import datetime


class HubSpotConfig(db.Model):
    """Stores the HubSpot API token and portal metadata for CRM integration."""
    __tablename__ = 'hubspot_config'

    id = db.Column(db.Integer, primary_key=True)
    # Token stored as Fernet-encrypted bytes, base64-encoded
    encrypted_token = db.Column(db.Text, nullable=False)
    # Fernet-encrypted HubSpot client secret for webhook signature verification
    encrypted_client_secret = db.Column(db.Text, nullable=True)
    portal_id = db.Column(db.String(50), nullable=True)
    account_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotConfig id={self.id} portal_id={self.portal_id}>'
