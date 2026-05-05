"""ImportJob, FieldMapping, and OAuthToken models."""
from app import db
from sqlalchemy import JSON
from datetime import datetime


class ImportJob(db.Model):
    """Import job model tracking the status and progress of a Google Sheets import."""
    __tablename__ = 'import_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    spreadsheet_id = db.Column(db.String(255), nullable=False)
    sheet_name = db.Column(db.String(255), nullable=False)
    field_mapping_id = db.Column(db.Integer, db.ForeignKey('field_mappings.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    total_rows = db.Column(db.Integer, default=0)
    rows_processed = db.Column(db.Integer, default=0)
    rows_imported = db.Column(db.Integer, default=0)
    rows_skipped = db.Column(db.Integer, default=0)
    error_log = db.Column(JSON, default=list)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    field_mapping = db.relationship('FieldMapping', backref='import_jobs')

    def __repr__(self):
        return f'<ImportJob {self.id} status={self.status}>'


class FieldMapping(db.Model):
    """Field mapping model storing column-to-field mappings for Google Sheets imports."""
    __tablename__ = 'field_mappings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    spreadsheet_id = db.Column(db.String(255), nullable=False)
    sheet_name = db.Column(db.String(255), nullable=False)
    mapping = db.Column(JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'spreadsheet_id', 'sheet_name', name='uq_field_mapping'),
    )

    def __repr__(self):
        return f'<FieldMapping user={self.user_id} sheet={self.sheet_name}>'


class OAuthToken(db.Model):
    """OAuth token model for storing encrypted Google OAuth2 refresh tokens."""
    __tablename__ = 'oauth_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, unique=True)
    encrypted_refresh_token = db.Column(db.LargeBinary, nullable=False)
    token_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<OAuthToken user={self.user_id}>'
