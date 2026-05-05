"""Lead and LeadAuditTrail models."""
from app import db
from datetime import datetime, date


class Lead(db.Model):
    """Lead model representing a property owner who is a potential seller or marketing target."""
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)

    # Property details
    property_street = db.Column(db.String(500), nullable=True, unique=True)
    property_city = db.Column(db.String(100), nullable=True)
    property_state = db.Column(db.String(50), nullable=True)
    property_zip = db.Column(db.String(20), nullable=True)
    property_type = db.Column(db.String(50), nullable=True)
    bedrooms = db.Column(db.Integer, nullable=True)
    bathrooms = db.Column(db.Float, nullable=True)
    square_footage = db.Column(db.Integer, nullable=True)
    lot_size = db.Column(db.Integer, nullable=True)
    year_built = db.Column(db.Integer, nullable=True)

    # Owner information
    owner_first_name = db.Column(db.String(128), nullable=True)
    owner_last_name = db.Column(db.String(128), nullable=True)
    ownership_type = db.Column(db.String(100), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=True)

    # Contact information
    phone_1 = db.Column(db.Text, nullable=True)
    phone_2 = db.Column(db.Text, nullable=True)
    phone_3 = db.Column(db.Text, nullable=True)
    email_1 = db.Column(db.String(255), nullable=True)
    email_2 = db.Column(db.String(255), nullable=True)

    # Mailing information
    mailing_address = db.Column(db.String(500), nullable=True)
    mailing_city = db.Column(db.String(100), nullable=True, index=True)
    mailing_state = db.Column(db.String(50), nullable=True, index=True)
    mailing_zip = db.Column(db.String(20), nullable=True, index=True)

    # Research tracking
    source = db.Column(db.String(100), nullable=True)  # where the property was found
    date_identified = db.Column(db.Date, nullable=True)  # when it was found
    notes = db.Column(db.Text, nullable=True)  # general notes

    # Skip tracing
    needs_skip_trace = db.Column(db.Boolean, nullable=True, default=False)
    skip_tracer = db.Column(db.String(100), nullable=True)
    date_skip_traced = db.Column(db.Date, nullable=True)

    # CRM integration
    date_added_to_hubspot = db.Column(db.Date, nullable=True)

    # Additional property details
    units = db.Column(db.Integer, nullable=True)
    units_allowed = db.Column(db.Integer, nullable=True)
    zoning = db.Column(db.String(100), nullable=True)
    county_assessor_pin = db.Column(db.String(50), nullable=True)
    tax_bill_2021 = db.Column(db.Float, nullable=True)
    most_recent_sale = db.Column(db.String(255), nullable=True)

    # Second owner
    owner_2_first_name = db.Column(db.String(128), nullable=True)
    owner_2_last_name = db.Column(db.String(128), nullable=True)

    # Additional address
    address_2 = db.Column(db.String(500), nullable=True)
    returned_addresses = db.Column(db.Text, nullable=True)

    # Additional phones (phone_1 through phone_3 already exist)
    phone_4 = db.Column(db.Text, nullable=True)
    phone_5 = db.Column(db.Text, nullable=True)
    phone_6 = db.Column(db.Text, nullable=True)
    phone_7 = db.Column(db.Text, nullable=True)

    # Additional emails (email_1 and email_2 already exist)
    email_3 = db.Column(db.String(255), nullable=True)
    email_4 = db.Column(db.String(255), nullable=True)
    email_5 = db.Column(db.String(255), nullable=True)

    # Social media
    socials = db.Column(db.Text, nullable=True)

    # Mailing tracking
    up_next_to_mail = db.Column(db.Boolean, nullable=True, default=False)
    mailer_history = db.Column(db.JSON, nullable=True)  # JSONB for flexible mailer tracking

    # Lead classification
    lead_category = db.Column(db.String(50), nullable=False, default='residential', server_default='residential', index=True)

    # Scoring
    lead_score = db.Column(db.Float, default=0)

    # Metadata
    data_source = db.Column(db.String(100), nullable=True)
    last_import_job_id = db.Column(db.Integer, db.ForeignKey('import_jobs.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Analysis link
    analysis_session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=True)

    # Relationships
    analysis_session = db.relationship('AnalysisSession', backref=db.backref('lead', uselist=False), uselist=False, foreign_keys=[analysis_session_id])
    enrichment_records = db.relationship('EnrichmentRecord', backref='lead', lazy='dynamic')
    marketing_list_members = db.relationship('MarketingListMember', backref='lead', lazy='dynamic')
    audit_trail = db.relationship('LeadAuditTrail', backref='lead', lazy='dynamic', cascade='all, delete-orphan')
    last_import_job = db.relationship('ImportJob', backref='leads', foreign_keys=[last_import_job_id])

    def __repr__(self):
        return f'<Lead {self.property_street}>'


class LeadAuditTrail(db.Model):
    """Audit trail for tracking changes to lead records."""
    __tablename__ = 'lead_audit_trail'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.String(100), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<LeadAuditTrail lead_id={self.lead_id} field={self.field_name}>'
