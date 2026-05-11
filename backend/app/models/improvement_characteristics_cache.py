"""ImprovementCharacteristicsCache model — local mirror of the Cook County
Improvement Characteristics Socrata dataset (bcnq-qi2z)."""
from app import db


class ImprovementCharacteristicsCache(db.Model):
    """Local cache of Cook County improvement (building) characteristics per PIN."""
    __tablename__ = 'improvement_characteristics_cache'

    pin            = db.Column(db.String(14), primary_key=True)
    bldg_sf        = db.Column(db.Integer, nullable=True)
    beds           = db.Column(db.Integer, nullable=True)
    fbath          = db.Column(db.Numeric(precision=4, scale=1), nullable=True)
    hbath          = db.Column(db.Numeric(precision=4, scale=1), nullable=True)
    age            = db.Column(db.Integer, nullable=True)
    ext_wall       = db.Column(db.Integer, nullable=True)
    apts           = db.Column(db.Integer, nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f'<ImprovementCharacteristicsCache pin={self.pin}>'
