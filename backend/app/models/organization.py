"""Organization model."""
from app import db
from datetime import datetime


class Organization(db.Model):
    """Organization model representing a legal entity (LLC, trust, corporation, etc.)."""
    __tablename__ = 'organizations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(500), nullable=False)
    org_type = db.Column(db.Enum(
        'llc', 'trust', 'corporation', 'brokerage',
        'law_firm', 'property_management', 'unknown',
        name='org_type_enum'
    ), nullable=False, default='unknown')
    status = db.Column(db.Enum(
        'active', 'inactive', 'unknown',
        name='org_status_enum'
    ), nullable=False, default='unknown')
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(100), nullable=True)
    hubspot_company_id = db.Column(db.String(50), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    # Relationships
    property_links = db.relationship('PropertyOrganizationLink', backref='organization',
                                     lazy='dynamic', cascade='all, delete-orphan')
    owner_links = db.relationship('OwnerOrganizationLink', backref='organization',
                                  lazy='dynamic', cascade='all, delete-orphan')
    audit_entries = db.relationship('OrganizationAuditLog', backref='organization',
                                    lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Organization {self.name}>'
