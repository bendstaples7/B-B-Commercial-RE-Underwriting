"""TaskAssociation model."""
from app import db


class TaskAssociation(db.Model):
    """Association table linking a Task to a target record (lead or organization)."""
    __tablename__ = 'task_associations'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer,
                        db.ForeignKey('tasks.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    target_type = db.Column(db.Enum(
        'lead', 'organization',
        name='task_target_type_enum'
    ), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.Index('ix_task_assoc_target', 'target_type', 'target_id'),
        db.UniqueConstraint('task_id', 'target_type', 'target_id',
                            name='uq_task_association'),
    )

    def __repr__(self):
        return f'<TaskAssociation task_id={self.task_id} target={self.target_type}:{self.target_id}>'
