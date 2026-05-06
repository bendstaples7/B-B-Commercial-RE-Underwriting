"""RehabPlanEntry model for per-unit renovation plans."""
from app import db
from datetime import datetime


class RehabPlanEntry(db.Model):
    """Renovation plan for a single Unit (one-to-one)."""
    __tablename__ = 'rehab_plan_entries'

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id', ondelete='CASCADE'), nullable=False, unique=True)
    renovate_flag = db.Column(db.Boolean, nullable=False, default=False)
    current_rent = db.Column(db.Numeric(14, 2), nullable=True)
    suggested_post_reno_rent = db.Column(db.Numeric(14, 2), nullable=True)
    underwritten_post_reno_rent = db.Column(db.Numeric(14, 2), nullable=True)
    rehab_start_month = db.Column(db.Integer, nullable=True)
    downtime_months = db.Column(db.Integer, nullable=True)
    stabilized_month = db.Column(db.Integer, nullable=True)
    rehab_budget = db.Column(db.Numeric(14, 2), nullable=True)
    scope_notes = db.Column(db.Text, nullable=True)
    stabilizes_after_horizon = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            'rehab_start_month IS NULL OR (rehab_start_month >= 1 AND rehab_start_month <= 24)',
            name='ck_rehab_plan_entries_start_month_range',
        ),
        db.CheckConstraint(
            'downtime_months IS NULL OR downtime_months >= 0',
            name='ck_rehab_plan_entries_downtime_non_negative',
        ),
    )

    def __repr__(self):
        return f'<RehabPlanEntry unit_id={self.unit_id} renovate={self.renovate_flag}>'
