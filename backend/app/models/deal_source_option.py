"""User-defined deal / capture sources (extends HubSpot-aligned builtins)."""
from datetime import datetime

from app import db


class DealSourceOption(db.Model):
    """Custom deal_source / contact.source values created from the Source dropdown.

    Built-in HubSpot-aligned options live in ``DEAL_SOURCE_OPTIONS`` and are not
    stored here. Custom rows power Channel-ROI-friendly tagging (e.g. Facebook Ad)
    without requiring a code deploy.
    """

    __tablename__ = 'deal_source_options'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    created_by = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<DealSourceOption id={self.id} name={self.name!r}>'
