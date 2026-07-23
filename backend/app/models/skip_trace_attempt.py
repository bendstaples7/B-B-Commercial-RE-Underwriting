"""Skip-trace attempt history — per-lead source ladder traceability."""
from __future__ import annotations

from datetime import datetime

from app import db


class SkipTraceAttempt(db.Model):
    """One skip-trace source attempt within a lead's escalation cycle."""

    __tablename__ = 'skip_trace_attempts'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer,
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    cycle = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    source_id = db.Column(db.String(64), nullable=False)
    source_label = db.Column(db.String(120), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    outcome = db.Column(db.String(32), nullable=False, default='started')
    # started | completed | failed_address | abandoned
    trigger = db.Column(db.String(32), nullable=False, default='manual_move')
    # invalid_mail | manual_move | initial
    mail_queue_item_id = db.Column(db.Integer, nullable=True)
    olc_order_id = db.Column(db.String(64), nullable=True)

    lead = db.relationship(
        'Property',
        backref=db.backref('skip_trace_attempts', lazy='dynamic'),
    )

    __table_args__ = (
        db.Index('ix_skip_trace_attempts_lead_cycle', 'lead_id', 'cycle'),
    )
