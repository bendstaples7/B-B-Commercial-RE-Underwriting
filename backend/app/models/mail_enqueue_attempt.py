"""Durable audit record for a direct-mail enqueue attempt."""
from datetime import datetime

from app import db


class MailEnqueueAttempt(db.Model):
    """One immutable summary and per-lead result set for a bulk enqueue."""

    __tablename__ = 'mail_enqueue_attempts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=False)
    source_queue = db.Column(db.String(100), nullable=True)
    requested_count = db.Column(db.Integer, nullable=False)
    added_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    invalid_count = db.Column(db.Integer, nullable=False, default=0)
    results = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    __table_args__ = (
        db.Index(
            'ix_mail_enqueue_attempts_user_created',
            'user_id',
            created_at.desc(),
            id.desc(),
        ),
        db.Index('ix_mail_enqueue_attempts_created_at', 'created_at'),
    )

    def __repr__(self):
        return (
            f'<MailEnqueueAttempt id={self.id} user_id={self.user_id} '
            f'requested={self.requested_count}>'
        )
