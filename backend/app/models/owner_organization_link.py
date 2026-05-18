"""OwnerOrganizationLink model."""
from app import db
from datetime import datetime


class OwnerOrganizationLink(db.Model):
    """Link table connecting an Owner (Lead) to an Organization with a named role."""
    __tablename__ = 'owner_organization_links'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer,
                         db.ForeignKey('leads.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    organization_id = db.Column(db.Integer,
                                db.ForeignKey('organizations.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    role = db.Column(db.String(100), nullable=False)  # principal, member, attorney, broker
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<OwnerOrganizationLink owner_id={self.owner_id} org_id={self.organization_id} role={self.role}>'
