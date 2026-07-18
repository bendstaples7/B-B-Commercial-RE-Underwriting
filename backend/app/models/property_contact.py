"""PropertyContact model — join table linking a Property (Lead) to a Contact."""
from app import db


class PropertyContact(db.Model):
    """Associates a Contact with a property (stored in the leads table) with a role and primary flag."""
    __tablename__ = 'property_contacts'

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer,
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    contact_id = db.Column(
        db.Integer,
        db.ForeignKey('contacts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    role = db.Column(
        db.Enum(
            'owner', 'property_manager', 'attorney', 'family_member', 'other',
            'former_owner',
            name='property_contact_role_enum',
            create_type=False,
        ),
        nullable=False,
        default='owner'
    )
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    superseded_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('property_id', 'contact_id', name='uq_property_contact'),
    )

    def __repr__(self):
        return f'<PropertyContact property_id={self.property_id} contact_id={self.contact_id} role={self.role}>'
