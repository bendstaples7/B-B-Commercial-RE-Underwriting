"""MarketingList and MarketingListMember models."""
from app import db
from sqlalchemy import JSON
from datetime import datetime


class MarketingList(db.Model):
    """Marketing list model for organizing leads into campaign groups."""
    __tablename__ = 'marketing_lists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    filter_criteria = db.Column(JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = db.relationship('MarketingListMember', backref='marketing_list', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<MarketingList {self.name}>'


class MarketingListMember(db.Model):
    """Marketing list member model tracking lead membership and outreach status."""
    __tablename__ = 'marketing_list_members'

    id = db.Column(db.Integer, primary_key=True)
    marketing_list_id = db.Column(db.Integer, db.ForeignKey('marketing_lists.id', ondelete='CASCADE'), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True)
    outreach_status = db.Column(db.String(20), nullable=False, default='not_contacted')
    added_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status_updated_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('marketing_list_id', 'lead_id', name='uq_list_member'),
    )

    def __repr__(self):
        return f'<MarketingListMember list={self.marketing_list_id} lead={self.lead_id} status={self.outreach_status}>'
