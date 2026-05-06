"""DealLenderSelection model for attaching lender profiles to deals."""
from app import db
from datetime import datetime


class DealLenderSelection(db.Model):
    """Associates a LenderProfile with a Deal for a specific scenario (A or B)."""
    __tablename__ = 'deal_lender_selections'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False)
    lender_profile_id = db.Column(db.Integer, db.ForeignKey('lender_profiles.id', ondelete='CASCADE'), nullable=False)
    scenario = db.Column(db.String(1), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            'deal_id', 'scenario', 'lender_profile_id',
            name='uq_deal_lender_selections_deal_scenario_profile',
        ),
        db.CheckConstraint(
            "scenario IN ('A', 'B')",
            name='ck_deal_lender_selections_scenario',
        ),
        db.Index(
            'ix_deal_lender_selections_primary',
            'deal_id', 'scenario',
            unique=True,
            postgresql_where=db.text('is_primary = true'),
        ),
    )

    def __repr__(self):
        return f'<DealLenderSelection deal={self.deal_id} scenario={self.scenario} primary={self.is_primary}>'
