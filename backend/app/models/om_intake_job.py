"""OMIntakeJob and OMFieldOverride models for Commercial OM PDF Intake."""
from app import db
from datetime import datetime


class OMIntakeJob(db.Model):
    """Tracks the lifecycle of a Commercial OM PDF intake pipeline job."""
    __tablename__ = 'om_intake_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    original_filename = db.Column(db.String(500), nullable=False)
    intake_status = db.Column(db.String(20), nullable=False, default='PENDING')

    # PDF storage and extraction results
    pdf_bytes = db.Column(db.LargeBinary, nullable=True)
    raw_text = db.Column(db.Text, nullable=True)
    tables_json = db.Column(db.JSON, nullable=True)
    table_extraction_warning = db.Column(db.Text, nullable=True)

    # AI extraction and analysis results
    extracted_om_data = db.Column(db.JSON, nullable=True)
    scenario_comparison = db.Column(db.JSON, nullable=True)
    market_rent_results = db.Column(db.JSON, nullable=True)
    consistency_warnings = db.Column(db.JSON, nullable=True)
    market_research_warnings = db.Column(db.JSON, nullable=True)

    # Validation flags
    partial_realistic_scenario_warning = db.Column(db.Boolean, nullable=True)
    asking_price_missing_error = db.Column(db.Boolean, nullable=True)
    unit_count_missing_error = db.Column(db.Boolean, nullable=True)

    # Failure tracking
    error_message = db.Column(db.Text, nullable=True)
    failed_at_stage = db.Column(db.String(20), nullable=True)

    # Link to created Deal on confirmation
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Relationships
    field_overrides = db.relationship(
        'OMFieldOverride',
        backref='job',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.CheckConstraint(
            "intake_status IN ('PENDING','PARSING','EXTRACTING','RESEARCHING','REVIEW','CONFIRMED','FAILED')",
            name='ck_om_intake_jobs_status',
        ),
        db.Index('ix_om_intake_jobs_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self):
        return f'<OMIntakeJob {self.id} status={self.intake_status}>'


class OMFieldOverride(db.Model):
    """Records user-supplied overrides to Gemini-extracted OM fields."""
    __tablename__ = 'om_field_overrides'

    id = db.Column(db.Integer, primary_key=True)
    om_intake_job_id = db.Column(
        db.Integer,
        db.ForeignKey('om_intake_jobs.id'),
        nullable=False,
    )
    field_name = db.Column(db.String(100), nullable=False)
    original_value = db.Column(db.JSON, nullable=True)
    overridden_value = db.Column(db.JSON, nullable=True)
    overridden_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('om_intake_job_id', 'field_name', name='uq_om_field_override_job_field'),
    )

    def __repr__(self):
        return f'<OMFieldOverride job={self.om_intake_job_id} field={self.field_name}>'
