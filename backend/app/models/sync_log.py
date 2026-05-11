"""SyncLog model — tracks Socrata cache sync operations."""
from app import db


class SyncLog(db.Model):
    """Records each cache sync attempt with status and row counts."""
    __tablename__ = 'sync_log'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dataset_name = db.Column(db.String(100), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rows_upserted = db.Column(db.Integer, nullable=True)
    status = db.Column(
        db.String(10),
        db.CheckConstraint("status IN ('running', 'success', 'failed')", name='ck_sync_log_status'),
        nullable=False,
    )
    error_message = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<SyncLog {self.dataset_name} {self.status} @ {self.started_at}>'
