"""LeadTimelineEntry model — append-only activity log for a lead."""
from app import db
from datetime import datetime


class LeadTimelineEntry(db.Model):
    """Append-only timeline entry recording every significant event on a lead."""
    __tablename__ = 'lead_timeline_entries'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'),
                        nullable=False, index=True)

    event_type = db.Column(db.Enum(
        'note_added', 'email_logged', 'call_logged', 'task_created', 'task_completed',
        'task_snoozed', 'recommended_action_changed', 'status_changed',
        'hubspot_note', 'hubspot_call', 'hubspot_task', 'hubspot_deal_stage',
        'property_analysis_completed', 'lead_imported',
        'mail_queued', 'mail_sent', 'mail_delivered',
        'property_match_approved', 'property_match_rejected',
        name='timeline_event_type_enum'
    ), nullable=False, index=True)

    # UTC timestamp of the event (may differ from created_at for HubSpot imports)
    occurred_at = db.Column(db.DateTime, nullable=False, index=True)

    # 'manual', 'system', or 'hubspot'
    source = db.Column(db.String(20), nullable=False, default='manual')

    # Actor: user identifier, 'System', or 'HubSpot'
    actor = db.Column(db.String(100), nullable=False)

    # Summary: up to 500 chars; replaced with '[deleted]' on soft-delete
    summary = db.Column(db.String(500), nullable=False)

    # Structured metadata (previous/new RA, call outcome, task title, etc.)
    # Named 'event_metadata' to avoid conflict with SQLAlchemy's reserved 'metadata' attribute.
    event_metadata = db.Column('metadata', db.JSON, nullable=True)

    # HubSpot deduplication key
    hubspot_activity_id = db.Column(db.String(50), nullable=True, unique=True, index=True)

    # Soft-delete flag
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationship — use 'Property' because the SQLAlchemy class is named Property
    # (Lead is a Python alias, not the registered mapper name).
    # cascade='all, delete-orphan' mirrors the Lead.audit_trail relationship so
    # that deleting a lead also deletes its timeline entries instead of trying
    # to NULL the NOT NULL lead_id FK (the FK already declares ON DELETE CASCADE
    # for the database layer; the ORM cascade covers SQLite where FK enforcement
    # is off).
    lead = db.relationship(
        'Property',
        backref=db.backref(
            'timeline_entries',
            lazy='dynamic',
            cascade='all, delete-orphan',
        ),
    )

    __table_args__ = (
        db.Index('ix_timeline_lead_occurred', 'lead_id', 'occurred_at'),
        db.Index('ix_timeline_actor_occurred', 'actor', 'occurred_at'),
    )

    def __repr__(self):
        return (f'<LeadTimelineEntry id={self.id} lead_id={self.lead_id} '
                f'event_type={self.event_type} occurred_at={self.occurred_at}>')
