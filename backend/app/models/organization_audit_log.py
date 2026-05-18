"""OrganizationAuditLog model."""
from app import db
from datetime import datetime


class OrganizationAuditLog(db.Model):
    """Audit log for tracking changes to Organization records."""
    __tablename__ = 'organization_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer,
                                db.ForeignKey('organizations.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.String(100), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<OrganizationAuditLog org_id={self.organization_id} field={self.field_name}>'
