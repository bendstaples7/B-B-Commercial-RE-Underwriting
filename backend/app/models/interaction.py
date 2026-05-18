"""Interaction model."""
from app import db
from datetime import datetime


class Interaction(db.Model):
    """Interaction model representing a communication event (note, call, email, meeting)."""
    __tablename__ = 'interactions'

    id = db.Column(db.Integer, primary_key=True)
    interaction_type = db.Column(db.Enum(
        'note', 'call', 'email', 'meeting', 'other',
        name='interaction_type_enum'
    ), nullable=False)
    body = db.Column(db.Text, nullable=False)
    occurred_at = db.Column(db.DateTime, nullable=False)
    source = db.Column(db.Enum(
        'manual', 'hubspot_import',
        name='interaction_source_enum'
    ), nullable=False, default='manual')
    hubspot_engagement_id = db.Column(db.String(50), nullable=True, unique=True, index=True)
    raw_payload = db.Column(db.JSON, nullable=True)
    is_orphaned = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    # Relationships
    associations = db.relationship('InteractionAssociation', backref='interaction',
                                   lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Interaction id={self.id} type={self.interaction_type}>'
