"""Mail queue item — lead waiting to be included in the next OLC batch."""
from datetime import datetime

from app import db


class MailQueueItem(db.Model):
    """A lead queued for direct mail via Open Letter Connect."""
    __tablename__ = 'mail_queue_items'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    user_id = db.Column(db.String(100), nullable=False, index=True)
    status = db.Column(
        db.Enum(
            'queued', 'invalid_address', 'removed', 'sent', 'failed',
            name='mail_queue_status_enum',
        ),
        nullable=False,
        default='queued',
        index=True,
    )
    validation_error = db.Column(db.String(500), nullable=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey('mail_campaigns.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    lead = db.relationship('Property', backref=db.backref('mail_queue_items', lazy='dynamic'))
    campaign = db.relationship('MailCampaign', backref=db.backref('queue_items', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_mail_queue_lead_status', 'lead_id', 'status'),
    )

    def __repr__(self):
        return f'<MailQueueItem id={self.id} lead_id={self.lead_id} status={self.status}>'
