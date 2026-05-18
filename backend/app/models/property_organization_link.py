"""PropertyOrganizationLink model."""
from app import db
from datetime import datetime


class PropertyOrganizationLink(db.Model):
    """Link table connecting a Property (Lead) to an Organization with a named role."""
    __tablename__ = 'property_organization_links'

    id = db.Column(db.Integer, primary_key=True)
    # property_id references leads.id (Lead is the property record)
    property_id = db.Column(db.Integer,
                            db.ForeignKey('leads.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    organization_id = db.Column(db.Integer,
                                db.ForeignKey('organizations.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    role = db.Column(db.String(100), nullable=False)  # owner, property_manager, broker, attorney, related_party
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('property_id', 'organization_id', 'role',
                            name='uq_property_org_role'),
    )

    def __repr__(self):
        return f'<PropertyOrganizationLink property_id={self.property_id} org_id={self.organization_id} role={self.role}>'
