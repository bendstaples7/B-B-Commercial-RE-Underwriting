"""OrganizationParty model — managers, members, officers, registered agents."""
from app import db
from datetime import datetime


class OrganizationParty(db.Model):
    """A person or company party associated with an Organization filing."""

    __tablename__ = 'organization_parties'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    full_name = db.Column(db.String(500), nullable=False)
    first_name = db.Column(db.String(128), nullable=True)
    last_name = db.Column(db.String(128), nullable=True)
    party_type = db.Column(db.Enum(
        'manager', 'member', 'officer', 'registered_agent',
        name='organization_party_type_enum',
    ), nullable=False)
    is_company = db.Column(db.Boolean, nullable=False, default=False)
    address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    zip = db.Column(db.String(20), nullable=True)
    source = db.Column(db.String(100), nullable=True)
    external_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    organization = db.relationship(
        'Organization', back_populates='parties',
    )

    def __repr__(self):
        return (
            f'<OrganizationParty id={self.id} org={self.organization_id} '
            f'type={self.party_type} name={self.full_name!r}>'
        )
