"""FundingSource model for down-payment funding waterfall."""
from app import db
from datetime import datetime


class FundingSource(db.Model):
    """A tranche of renovation capital (Cash, HELOC_1, or HELOC_2) for a Deal."""
    __tablename__ = 'funding_sources'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False)
    source_type = db.Column(db.String(10), nullable=False)
    total_available = db.Column(db.Numeric(14, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(8, 6), nullable=False, default=0)
    origination_fee_rate = db.Column(db.Numeric(8, 6), nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('deal_id', 'source_type', name='uq_funding_sources_deal_source_type'),
        db.CheckConstraint(
            "source_type IN ('Cash', 'HELOC_1', 'HELOC_2')",
            name='ck_funding_sources_source_type',
        ),
    )

    def __repr__(self):
        return f'<FundingSource deal={self.deal_id} type={self.source_type}>'
