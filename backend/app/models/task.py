"""Task model."""
from app import db
from datetime import datetime


class Task(db.Model):
    """Task model representing a to-do item attached to a property, lead, owner, or organization."""
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.Enum(
        'open', 'completed', 'cancelled', 'overdue',
        name='task_status_enum'
    ), nullable=False, default='open')
    priority = db.Column(db.Enum(
        'high', 'medium', 'low',
        name='task_priority_enum'
    ), nullable=False, default='medium')
    source = db.Column(db.Enum(
        'manual', 'hubspot_import',
        name='task_source_enum'
    ), nullable=False, default='manual')
    hubspot_task_id = db.Column(db.String(50), nullable=True, unique=True, index=True)
    raw_payload = db.Column(db.JSON, nullable=True)
    # CRM task unification — direct lead FK (set for manually-created CRM tasks)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=True, index=True)
    # CRM task type classification (mirrors LeadTask.task_type for tasks created via UI)
    task_type = db.Column(db.String(50), nullable=True)
    completion_timestamp = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    __table_args__ = (
        # Composite index for the frequent overdue predicate:
        # WHERE status IN ('open','overdue') AND due_date < NOW()
        db.Index('ix_tasks_status_due_date', 'status', 'due_date'),
    )

    # Relationships
    associations = db.relationship('TaskAssociation', backref='task',
                                   lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Task id={self.id} title={self.title!r} status={self.status}>'
