"""DataSource and EnrichmentRecord models."""
from app import db
from sqlalchemy import JSON
from datetime import datetime


class DataSource(db.Model):
    """Data source model for external enrichment data providers."""
    __tablename__ = 'data_sources'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    endpoint_url = db.Column(db.String(500), nullable=True)
    config = db.Column(JSON, default=dict)
    field_mapping = db.Column(JSON, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    enrichment_records = db.relationship('EnrichmentRecord', backref='data_source', lazy='dynamic')

    def __repr__(self):
        return f'<DataSource {self.name}>'


class EnrichmentRecord(db.Model):
    """Enrichment record tracking data retrieved from external sources for a lead."""
    __tablename__ = 'enrichment_records'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True)
    data_source_id = db.Column(db.Integer, db.ForeignKey('data_sources.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    retrieved_data = db.Column(JSON, nullable=True)
    error_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<EnrichmentRecord lead_id={self.lead_id} source={self.data_source_id} status={self.status}>'
