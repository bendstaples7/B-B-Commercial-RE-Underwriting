"""FacebookAdCampaign — synced Meta Marketing API campaign metrics."""
from datetime import datetime

from app import db


class FacebookAdCampaign(db.Model):
    """One Meta Ads campaign with spend / clicks and CRM response attribution."""

    __tablename__ = 'facebook_ad_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    meta_campaign_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(512), nullable=False, default='')
    status = db.Column(db.String(64), nullable=True)
    spend = db.Column(db.Numeric(14, 4), nullable=False, default=0)
    impressions = db.Column(db.Integer, nullable=False, default=0)
    link_clicks = db.Column(db.Integer, nullable=False, default=0)
    response_count = db.Column(db.Integer, nullable=False, default=0)
    synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f'<FacebookAdCampaign id={self.id} meta={self.meta_campaign_id}>'
