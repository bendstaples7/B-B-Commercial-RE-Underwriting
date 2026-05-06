"""ProFormaResult model for caching computed pro forma outputs."""
from app import db
from datetime import datetime
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


class ProFormaResult(db.Model):
    """Cached pro forma computation result for a Deal (one row per Deal)."""
    __tablename__ = 'pro_forma_results'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False, unique=True)
    inputs_hash = db.Column(db.String(64), nullable=False)
    computed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    result_json = db.Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)

    def __repr__(self):
        return f'<ProFormaResult deal={self.deal_id} hash={self.inputs_hash[:8]}>'
