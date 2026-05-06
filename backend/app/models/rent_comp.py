"""RentComp model for market comparable rentals."""
from app import db
from datetime import datetime


class RentComp(db.Model):
    """Market comparable rental used to justify market rent assumptions."""
    __tablename__ = 'rent_comps'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    address = db.Column(db.String(500), nullable=False)
    neighborhood = db.Column(db.String(200), nullable=True)
    unit_type = db.Column(db.String(50), nullable=False)
    observed_rent = db.Column(db.Numeric(14, 2), nullable=False)
    sqft = db.Column(db.Integer, nullable=False)
    rent_per_sqft = db.Column(db.Numeric(10, 4), nullable=False)
    observation_date = db.Column(db.Date, nullable=True)
    source_url = db.Column(db.String(1000), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint('sqft > 0', name='ck_rent_comps_sqft_positive'),
    )

    def __repr__(self):
        return f'<RentComp {self.address} {self.unit_type}>'
