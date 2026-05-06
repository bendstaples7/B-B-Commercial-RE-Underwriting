"""SaleComp model for sales comparables."""
from app import db
from datetime import datetime


class SaleComp(db.Model):
    """Closed sale comparable used to derive market cap rate and price-per-unit."""
    __tablename__ = 'sale_comps'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    address = db.Column(db.String(500), nullable=False)
    unit_count = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=True)
    sale_price = db.Column(db.Numeric(14, 2), nullable=False)
    close_date = db.Column(db.Date, nullable=True)
    observed_cap_rate = db.Column(db.Numeric(8, 6), nullable=False)
    observed_ppu = db.Column(db.Numeric(14, 2), nullable=False)
    distance_miles = db.Column(db.Numeric(8, 3), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint('unit_count > 0', name='ck_sale_comps_unit_count_positive'),
        db.CheckConstraint(
            'observed_cap_rate > 0 AND observed_cap_rate <= 0.25',
            name='ck_sale_comps_cap_rate_range',
        ),
    )

    def __repr__(self):
        return f'<SaleComp {self.address} cap={self.observed_cap_rate}>'
