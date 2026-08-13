"""SPA boot-failure beacon events (blank SPA / broken JS class)."""
from datetime import datetime

from app import db


class SpaBootFailureEvent(db.Model):
    __tablename__ = 'spa_boot_failure_events'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip_hash = db.Column(db.String(64), nullable=True, index=True)
    href = db.Column(db.String(1024), nullable=True)
    reason = db.Column(db.String(128), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    asset_hints = db.Column(db.JSON, nullable=True)

    def __repr__(self):
        return f'<SpaBootFailureEvent id={self.id} reason={self.reason!r}>'
