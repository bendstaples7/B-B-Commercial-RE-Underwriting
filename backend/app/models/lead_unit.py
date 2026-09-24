"""Per-lead unit inventory (Quick Add / Command Center capture)."""
from datetime import datetime

from app import db

# Canonical unit_type values for lead_units.unit_type
LEAD_UNIT_TYPES: tuple[str, ...] = (
    'residential',
    'storefront',
    'office',
    'other',
)

# lead.lead_subtype — orthogonal to lead_category (residential/commercial).
LEAD_SUBTYPES: tuple[str, ...] = (
    'residential',
    'mixed_use',
    'commercial',
)


class LeadUnit(db.Model):
    """One rentable unit on a CRM lead (not multifamily Deal.units)."""

    __tablename__ = 'lead_units'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer,
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    unit_label = db.Column(db.String(50), nullable=False)
    unit_type = db.Column(db.String(50), nullable=False, default='residential')
    beds = db.Column(db.Integer, nullable=True)
    baths = db.Column(db.Numeric(4, 1), nullable=True)
    sqft = db.Column(db.Integer, nullable=True)
    current_rent = db.Column(db.Numeric(12, 2), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    lead = db.relationship(
        'Property',
        backref=db.backref('lead_units', lazy='dynamic', cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.UniqueConstraint('lead_id', 'unit_label', name='uq_lead_units_lead_label'),
    )

    def __repr__(self):
        return f'<LeadUnit lead={self.lead_id} label={self.unit_label!r}>'
