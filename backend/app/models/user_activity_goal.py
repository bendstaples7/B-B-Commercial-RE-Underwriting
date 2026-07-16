"""Per-user weekly/monthly activity goal targets for the CRM dashboard."""
from datetime import datetime, timezone

from app import db


PERIOD_TYPES = ('weekly', 'monthly')
METRICS = ('calls', 'mailers', 'emails', 'notes', 'tasks')


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserActivityGoal(db.Model):
    """One target row per (user, period_type, metric)."""

    __tablename__ = 'user_activity_goals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    period_type = db.Column(db.String(20), nullable=False)
    metric = db.Column(db.String(20), nullable=False)
    target = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow_naive)

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'period_type', 'metric',
            name='uq_user_activity_goals_user_period_metric',
        ),
        db.CheckConstraint(
            "period_type IN ('weekly', 'monthly')",
            name='ck_user_activity_goals_period_type',
        ),
        db.CheckConstraint(
            "metric IN ('calls', 'mailers', 'emails', 'notes', 'tasks')",
            name='ck_user_activity_goals_metric',
        ),
        db.CheckConstraint('target >= 0', name='ck_user_activity_goals_target_nonneg'),
    )

    def __repr__(self):
        return (
            f'<UserActivityGoal user_id={self.user_id} '
            f'period={self.period_type} metric={self.metric} target={self.target}>'
        )
