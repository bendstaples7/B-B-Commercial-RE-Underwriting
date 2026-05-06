"""Unit model for multifamily deals."""
from app import db
from datetime import datetime


class Unit(db.Model):
    """A single rentable dwelling within a multifamily Deal."""
    __tablename__ = 'units'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    unit_identifier = db.Column(db.String(50), nullable=False)
    unit_type = db.Column(db.String(50), nullable=True)
    beds = db.Column(db.Integer, nullable=True)
    baths = db.Column(db.Numeric(4, 1), nullable=True)
    sqft = db.Column(db.Integer, nullable=True)
    occupancy_status = db.Column(db.String(20), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    rent_roll_entry = db.relationship('RentRollEntry', backref='unit', uselist=False, cascade='all, delete-orphan')
    rehab_plan_entry = db.relationship('RehabPlanEntry', backref='unit', uselist=False, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('deal_id', 'unit_identifier', name='uq_units_deal_unit_identifier'),
        db.CheckConstraint(
            "occupancy_status IN ('Occupied', 'Vacant', 'Down')",
            name='ck_units_occupancy_status',
        ),
    )

    def __repr__(self):
        return f'<Unit {self.unit_identifier} deal={self.deal_id}>'
