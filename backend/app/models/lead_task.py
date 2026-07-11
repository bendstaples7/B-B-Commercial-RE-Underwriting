"""LeadTask model — CRM-specific task tied directly to a lead."""
from app import db
from datetime import datetime


class LeadTask(db.Model):
    """CRM task with typed task types, direct lead_id FK, and open/completed/cancelled lifecycle."""
    __tablename__ = 'lead_tasks'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'),
                        nullable=False, index=True)

    # Task type: built-in enum or 'custom' for free-text
    task_type = db.Column(db.Enum(
        'call_owner_today', 'research_missing_pin', 'match_hubspot_deal',
        'run_property_analysis', 'add_to_mail_batch', 'skip_trace_owner',
        'confirm_building_ownership', 'custom',
        name='lead_task_type_enum'
    ), nullable=False, default='custom')

    # Title: required for custom tasks, auto-populated for built-in types
    title = db.Column(db.String(255), nullable=False)

    status = db.Column(db.Enum(
        'open', 'completed', 'cancelled',
        name='lead_task_status_enum'
    ), nullable=False, default='open', index=True)

    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(100), nullable=False, default='anonymous')
    # HubSpot engagement/task id when this LeadTask was imported or synced from HubSpot.
    # Partial unique index on (hubspot_task_id, lead_id) — one row per lead per HubSpot task.
    hubspot_task_id = db.Column(db.String(50), nullable=True)

    # Relationship — use 'Property' because the SQLAlchemy class is named Property
    # (Lead is a Python alias, not the registered mapper name)
    lead = db.relationship('Property', backref=db.backref('lead_tasks', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_lead_tasks_lead_status', 'lead_id', 'status'),
        db.Index('ix_lead_tasks_status_due_date', 'status', 'due_date'),
        db.Index(
            'ix_lead_tasks_hubspot_task_id_lead_id',
            'hubspot_task_id',
            'lead_id',
            unique=True,
            postgresql_where=db.text('hubspot_task_id IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f'<LeadTask id={self.id} lead_id={self.lead_id} type={self.task_type} status={self.status}>'
