"""HubSpotPlatformWrite model — stub for loop guard tracking of outbound writes."""
from datetime import datetime
from app import db


class HubSpotPlatformWrite(db.Model):
    __tablename__ = 'hubspot_platform_writes'

    id = db.Column(db.Integer, primary_key=True)
    object_type = db.Column(db.String(50), nullable=False)
    hubspot_id = db.Column(db.String(50), nullable=False)
    written_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<HubSpotPlatformWrite id={self.id} object_type={self.object_type} hubspot_id={self.hubspot_id}>'
