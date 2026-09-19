"""MailCampaignLeadAttribution — once-per-lead direct-mail response ledger."""
from datetime import datetime

from app import db


class MailCampaignLeadAttribution(db.Model):
    """Unique lead×campaign row so response_count bumps are race- and soft-delete-safe."""

    __tablename__ = 'mail_campaign_lead_attributions'

    lead_id = db.Column(
        db.Integer,
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        primary_key=True,
    )
    mail_campaign_id = db.Column(
        db.Integer,
        db.ForeignKey('mail_campaigns.id', ondelete='CASCADE'),
        primary_key=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return (
            f'<MailCampaignLeadAttribution lead={self.lead_id} '
            f'campaign={self.mail_campaign_id}>'
        )
