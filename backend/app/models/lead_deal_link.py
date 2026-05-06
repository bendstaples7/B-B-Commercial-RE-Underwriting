"""LeadDealLink model for bridging Lead and Deal permissions."""
from app import db
from datetime import datetime


class LeadDealLink(db.Model):
    """Bidirectional link between a Lead and a Deal for permission inheritance."""
    __tablename__ = 'lead_deal_links'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('lead_id', 'deal_id', name='uq_lead_deal_links_lead_deal'),
    )

    def __repr__(self):
        return f'<LeadDealLink lead={self.lead_id} deal={self.deal_id}>'
