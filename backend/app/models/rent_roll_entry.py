"""RentRollEntry model for in-place rent records."""
from app import db
from datetime import datetime


class RentRollEntry(db.Model):
    """In-place rent record for a single Unit (one-to-one)."""
    __tablename__ = 'rent_roll_entries'

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id', ondelete='CASCADE'), nullable=False, unique=True)
    current_rent = db.Column(db.Numeric(14, 2), nullable=False)
    lease_start_date = db.Column(db.Date, nullable=True)
    lease_end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            'lease_end_date >= lease_start_date',
            name='ck_rent_roll_entries_lease_dates',
        ),
    )

    def __repr__(self):
        return f'<RentRollEntry unit_id={self.unit_id} rent={self.current_rent}>'
