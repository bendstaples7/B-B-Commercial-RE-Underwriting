"""DealAuditTrail model for tracking changes to Deal records."""
from app import db
from datetime import datetime


class DealAuditTrail(db.Model):
    """Audit trail for tracking mutations to Deal records (mirrors LeadAuditTrail shape)."""
    __tablename__ = 'deal_audit_trails'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.String(255), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    changed_fields = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<DealAuditTrail deal_id={self.deal_id} action={self.action}>'
