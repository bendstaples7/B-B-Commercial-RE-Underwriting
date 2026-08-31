"""FacebookCampaignLeadAttribution — once-per-lead response bump ledger."""
from datetime import datetime

from app import db


class FacebookCampaignLeadAttribution(db.Model):
    """Unique lead×campaign row so response_count bumps are race- and soft-delete-safe."""

    __tablename__ = 'facebook_campaign_lead_attributions'

    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), primary_key=True)
    facebook_campaign_id = db.Column(
        db.Integer, db.ForeignKey('facebook_ad_campaigns.id'), primary_key=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return (
            f'<FacebookCampaignLeadAttribution lead={self.lead_id} '
            f'campaign={self.facebook_campaign_id}>'
        )
