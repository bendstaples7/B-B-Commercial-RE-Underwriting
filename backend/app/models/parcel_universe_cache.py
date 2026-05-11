"""ParcelUniverseCache model — local mirror of the Cook County Parcel Universe dataset."""
from app import db


class ParcelUniverseCache(db.Model):
    """Local cache of the Cook County Parcel Universe (Socrata dataset pabr-t5kh).

    Stores latitude/longitude per PIN to support bounding-box lookups without
    hitting the live Socrata API at comparable-search time.
    """

    __tablename__ = 'parcel_universe_cache'

    pin            = db.Column(db.String(14), primary_key=True)
    lat            = db.Column(db.Numeric(precision=10, scale=7), nullable=True)
    lon            = db.Column(db.Numeric(precision=10, scale=7), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.Index('ix_parcel_universe_lat_lon', 'lat', 'lon'),
    )

    def __repr__(self):
        return f'<ParcelUniverseCache pin={self.pin} lat={self.lat} lon={self.lon}>'
