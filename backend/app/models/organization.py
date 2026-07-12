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
        'law_firm', 'property_management', 'nonprofit', 'unknown',
        name='org_type_enum'
    ), nullable=False, default='unknown')
    status = db.Column(db.Enum(
        'active', 'inactive', 'unknown',
        name='org_status_enum'
    ), nullable=False, default='unknown')
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(100), nullable=True)
    hubspot_company_id = db.Column(db.String(50), nullable=True, index=True)

    # Entity-lookup / SOS filing metadata (Illinois LLC resolution)
    jurisdiction = db.Column(db.String(20), nullable=True)  # e.g. us_il
    file_number = db.Column(db.String(50), nullable=True, index=True)
    registered_agent_name = db.Column(db.String(500), nullable=True)
    registered_office_address = db.Column(db.Text, nullable=True)
    entity_lookup_status = db.Column(db.Enum(
        'pending', 'resolved', 'no_match', 'unsupported_jurisdiction', 'error',
        name='entity_lookup_status_enum',
    ), nullable=True, index=True)
    entity_lookup_provider = db.Column(db.String(100), nullable=True)
    entity_lookup_checked_at = db.Column(db.DateTime, nullable=True)
    entity_lookup_error = db.Column(db.Text, nullable=True)
    entity_lookup_person_found = db.Column(db.Boolean, nullable=False, default=False)

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
    parties = db.relationship(
        'OrganizationParty', back_populates='organization',
        lazy='dynamic', cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<Organization {self.name}>'
