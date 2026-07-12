"""IRS Exempt Organizations Business Master File (EO BMF) rows."""
from datetime import datetime

from app import db


class IrsEoOrganization(db.Model):
    """One tax-exempt organization from the IRS EO BMF extract."""

    __tablename__ = 'irs_eo_organizations'

    ein = db.Column(db.String(9), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(200), nullable=False, index=True)
    city = db.Column(db.String(64), nullable=True)
    state = db.Column(db.String(2), nullable=True, index=True)
    ntee_cd = db.Column(db.String(10), nullable=True)
    subsection = db.Column(db.String(4), nullable=True)
    status = db.Column(db.String(2), nullable=True)
    imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<IrsEoOrganization {self.ein} {self.name!r}>'
