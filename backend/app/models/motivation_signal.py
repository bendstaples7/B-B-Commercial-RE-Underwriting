"""Motivation signal models for structured seller-distress scoring."""
from datetime import datetime

from app import db
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import TypeDecorator, JSON as SaJSON


class _JSONBCompatible(TypeDecorator):
    impl = SaJSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(SaJSON())


class MotivationSignal(db.Model):
    __tablename__ = 'motivation_signals'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=True, index=True)
    signal_type = db.Column(db.String(64), nullable=False)
    severity = db.Column(db.String(16), nullable=False)
    points = db.Column(db.Float, nullable=False, default=0.0)
    source = db.Column(db.String(32), nullable=False)
    source_dataset = db.Column(db.String(64), nullable=True)
    evidence_key = db.Column(db.String(255), nullable=True)
    evidence = db.Column(_JSONBCompatible, nullable=True)
    detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    lead = db.relationship('Property', backref=db.backref('motivation_signals', lazy='dynamic'))

    def __repr__(self):
        return f'<MotivationSignal {self.id} lead={self.lead_id} type={self.signal_type}>'


class ProspectCandidate(db.Model):
    __tablename__ = 'prospect_candidates'

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.String(36), nullable=False, index=True)
    pin = db.Column(db.String(50), nullable=True, index=True)
    property_street = db.Column(db.String(500), nullable=True)
    property_city = db.Column(db.String(100), nullable=True)
    property_state = db.Column(db.String(50), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    primary_signal_type = db.Column(db.String(64), nullable=False)
    motivation_score = db.Column(db.Float, nullable=False, default=0.0)
    signals = db.Column(_JSONBCompatible, nullable=True)
    source_feed = db.Column(db.String(64), nullable=False)
    external_key = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='pending')
    duplicate_lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True)
    imported_lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.String(36), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    raw_record = db.Column(_JSONBCompatible, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProspectCandidate {self.id} feed={self.source_feed} status={self.status}>'


class ProspectFeedState(db.Model):
    __tablename__ = 'prospect_feed_state'

    id = db.Column(db.Integer, primary_key=True)
    feed_name = db.Column(db.String(64), nullable=False, unique=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    cursor = db.Column(db.String(255), nullable=True)
    rows_processed = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ProspectAreaFilter(db.Model):
    """Per-user optional map-drawn area for Prospect Review display filtering."""

    __tablename__ = 'prospect_area_filters'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    label = db.Column(db.String(255), nullable=True)
    geometry = db.Column(_JSONBCompatible, nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f'<ProspectAreaFilter user_id={self.user_id} enabled={self.enabled}>'
