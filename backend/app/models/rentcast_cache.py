"""RentCast API response cache model."""
from app import db
from datetime import datetime


class RentCastCache(db.Model):
    """Cached RentCast rent estimate to avoid redundant API calls.

    A cached entry is considered fresh for 90 days after ``fetched_at``.
    The cache key is the combination of address + unit characteristics.
    """
    __tablename__ = 'rentcast_cache'

    id = db.Column(db.Integer, primary_key=True)

    # Cache key fields — normalized address + unit characteristics
    address_key = db.Column(db.String(500), nullable=False)
    unit_type_label = db.Column(db.String(100), nullable=False)
    bedrooms = db.Column(db.Integer, nullable=True)
    bathrooms = db.Column(db.Numeric(4, 1), nullable=True)
    square_footage = db.Column(db.Integer, nullable=True)

    # Cached RentCast response
    rent_estimate = db.Column(db.Numeric(14, 2), nullable=True)
    rent_range_low = db.Column(db.Numeric(14, 2), nullable=True)
    rent_range_high = db.Column(db.Numeric(14, 2), nullable=True)
    comparables_count = db.Column(db.Integer, nullable=False, default=0)

    # When the RentCast API was called
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            'address_key', 'unit_type_label', 'bedrooms', 'bathrooms', 'square_footage',
            name='uq_rentcast_cache_key',
        ),
        db.Index('ix_rentcast_cache_address_fetched', 'address_key', 'fetched_at'),
    )

    def __repr__(self):
        return (
            f'<RentCastCache address={self.address_key!r} '
            f'unit={self.unit_type_label!r} estimate={self.rent_estimate}>'
        )
