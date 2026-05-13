"""SaleComp model for sales comparables."""
from app import db
from datetime import datetime


class SaleComp(db.Model):
    """Closed sale comparable used to derive market cap rate and price-per-unit.

    cap_rate_confidence values:
      1.0 — cap rate was stated directly in the source
      0.5 — cap rate was derived from NOI / sale_price
      0.0 — cap rate is unknown (comp included without cap rate data)
      None — not set (legacy rows or manually-added comps without confidence)
    """
    __tablename__ = 'sale_comps'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    address = db.Column(db.String(500), nullable=False)
    unit_count = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=True)
    sale_price = db.Column(db.Numeric(14, 2), nullable=False)
    close_date = db.Column(db.Date, nullable=True)
    # observed_cap_rate is nullable — many comps don't have cap rate data.
    # When null, cap_rate_confidence is 0.0.
    # When derived from noi/sale_price, cap_rate_confidence is 0.5.
    # When stated directly, cap_rate_confidence is 1.0.
    observed_cap_rate = db.Column(db.Numeric(8, 6), nullable=True)
    observed_ppu = db.Column(db.Numeric(14, 2), nullable=False)
    distance_miles = db.Column(db.Numeric(8, 3), nullable=True)
    # Annual NOI — used to derive cap rate when not stated directly
    noi = db.Column(db.Numeric(14, 2), nullable=True)
    # Confidence in the cap rate: 1.0=stated, 0.5=derived, 0.0=unknown, None=not set
    cap_rate_confidence = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint('unit_count > 0', name='ck_sale_comps_unit_count_positive'),
    )

    def __repr__(self):
        return f'<SaleComp {self.address} cap={self.observed_cap_rate} confidence={self.cap_rate_confidence}>'
