"""MarketRentAssumption model."""
from app import db
from datetime import datetime


class MarketRentAssumption(db.Model):
    """Target market rent per unit type for a Deal."""
    __tablename__ = 'market_rent_assumptions'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False)
    unit_type = db.Column(db.String(50), nullable=False)
    target_rent = db.Column(db.Numeric(14, 2), nullable=True)
    post_reno_target_rent = db.Column(db.Numeric(14, 2), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('deal_id', 'unit_type', name='uq_market_rent_assumptions_deal_unit_type'),
    )

    def __repr__(self):
        return f'<MarketRentAssumption deal={self.deal_id} type={self.unit_type}>'
