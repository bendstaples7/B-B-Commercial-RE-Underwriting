"""ChannelRoiConfig — org-level Meta Ads + projection assumptions for Channel ROI."""
from datetime import datetime

from app import db


class ChannelRoiConfig(db.Model):
    """Singleton-ish company settings for marketing channel ROI.

    Prefer the latest row (``order_by(id.desc()).first()``), same pattern as HubSpotConfig.
    """

    __tablename__ = 'channel_roi_config'

    id = db.Column(db.Integer, primary_key=True)
    encrypted_meta_token = db.Column(db.Text, nullable=True)
    meta_ad_account_id = db.Column(db.String(64), nullable=True)
    expected_profit_per_deal = db.Column(db.Numeric(12, 2), nullable=True)
    assumed_close_rate = db.Column(db.Numeric(5, 4), nullable=True)  # 0–1 fraction
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_sync_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f'<ChannelRoiConfig id={self.id} ad_account={self.meta_ad_account_id}>'
