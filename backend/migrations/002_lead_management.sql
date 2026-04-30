-- Migration 002: Create lead management tables for Lead Database Integration
-- This migration adds tables for lead storage, import tracking, scoring, enrichment, and marketing

-- Import-related tables (created first due to foreign key dependencies)

-- Field Mappings table
CREATE TABLE IF NOT EXISTS field_mappings (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    spreadsheet_id VARCHAR(255) NOT NULL,
    sheet_name VARCHAR(255) NOT NULL,
    mapping JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_field_mapping UNIQUE (user_id, spreadsheet_id, sheet_name)
);

-- Import Jobs table
CREATE TABLE IF NOT EXISTS import_jobs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    spreadsheet_id VARCHAR(255) NOT NULL,
    sheet_name VARCHAR(255) NOT NULL,
    field_mapping_id INTEGER REFERENCES field_mappings(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_rows INTEGER DEFAULT 0,
    rows_processed INTEGER DEFAULT 0,
    rows_imported INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    error_log JSONB DEFAULT '[]',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_user_id ON import_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);

-- OAuth Tokens table
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL UNIQUE,
    encrypted_refresh_token BYTEA NOT NULL,
    token_expiry TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Scoring Weights table
CREATE TABLE IF NOT EXISTS scoring_weights (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL UNIQUE,
    property_characteristics_weight DECIMAL(3,2) NOT NULL DEFAULT 0.30,
    data_completeness_weight DECIMAL(3,2) NOT NULL DEFAULT 0.20,
    owner_situation_weight DECIMAL(3,2) NOT NULL DEFAULT 0.30,
    location_desirability_weight DECIMAL(3,2) NOT NULL DEFAULT 0.20,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Data Sources table
CREATE TABLE IF NOT EXISTS data_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    endpoint_url VARCHAR(500),
    config JSONB DEFAULT '{}',
    field_mapping JSONB DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Leads table (depends on import_jobs and analysis_sessions)
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    -- Property details
    property_street VARCHAR(500) NOT NULL,
    property_city VARCHAR(100),
    property_state VARCHAR(50),
    property_zip VARCHAR(20),
    property_type VARCHAR(50),
    bedrooms INTEGER,
    bathrooms DECIMAL(3,1),
    square_footage INTEGER,
    lot_size INTEGER,
    year_built INTEGER,
    -- Owner information
    owner_first_name VARCHAR(128) NOT NULL,
    owner_last_name VARCHAR(128),
    ownership_type VARCHAR(100),
    acquisition_date DATE,
    -- Contact information
    phone_1 TEXT,
    phone_2 TEXT,
    phone_3 TEXT,
    email_1 VARCHAR(255),
    email_2 VARCHAR(255),
    -- Mailing information
    mailing_address VARCHAR(500),
    mailing_city VARCHAR(100),
    mailing_state VARCHAR(50),
    mailing_zip VARCHAR(20),
    -- Research tracking
    source VARCHAR(100),
    date_identified DATE,
    notes TEXT,
    -- Skip tracing
    needs_skip_trace BOOLEAN DEFAULT FALSE,
    skip_tracer VARCHAR(100),
    date_skip_traced DATE,
    -- CRM integration
    date_added_to_hubspot DATE,
    -- Additional property details
    units INTEGER,
    units_allowed INTEGER,
    zoning VARCHAR(100),
    county_assessor_pin VARCHAR(50),
    tax_bill_2021 DECIMAL(12,2),
    most_recent_sale VARCHAR(255),
    -- Second owner
    owner_2_first_name VARCHAR(128),
    owner_2_last_name VARCHAR(128),
    -- Additional address
    address_2 VARCHAR(500),
    returned_addresses TEXT,
    -- Additional phones
    phone_4 TEXT,
    phone_5 TEXT,
    phone_6 TEXT,
    phone_7 TEXT,
    -- Additional emails
    email_3 VARCHAR(255),
    email_4 VARCHAR(255),
    email_5 VARCHAR(255),
    -- Social media
    socials TEXT,
    -- Mailing tracking
    up_next_to_mail BOOLEAN DEFAULT FALSE,
    mailer_history JSONB,
    -- Scoring
    lead_score DECIMAL(5,2) DEFAULT 0,
    -- Metadata
    data_source VARCHAR(100),
    last_import_job_id INTEGER REFERENCES import_jobs(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Analysis link
    analysis_session_id INTEGER REFERENCES analysis_sessions(id),
    -- Constraints
    CONSTRAINT uq_leads_property_street UNIQUE (property_street)
);

CREATE INDEX IF NOT EXISTS idx_leads_owner_first_name ON leads(owner_first_name);
CREATE INDEX IF NOT EXISTS idx_leads_owner_last_name ON leads(owner_last_name);
CREATE INDEX IF NOT EXISTS idx_leads_mailing_state ON leads(mailing_state);
CREATE INDEX IF NOT EXISTS idx_leads_mailing_zip ON leads(mailing_zip);
CREATE INDEX IF NOT EXISTS idx_leads_mailing_city ON leads(mailing_city);
CREATE INDEX IF NOT EXISTS idx_leads_lead_score ON leads(lead_score);
CREATE INDEX IF NOT EXISTS idx_leads_property_type ON leads(property_type);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at);

-- Lead Audit Trail table
CREATE TABLE IF NOT EXISTS lead_audit_trail (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by VARCHAR(100) NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lead_audit_trail_lead_id ON lead_audit_trail(lead_id);

-- Enrichment Records table
CREATE TABLE IF NOT EXISTS enrichment_records (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    data_source_id INTEGER NOT NULL REFERENCES data_sources(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    retrieved_data JSONB,
    error_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enrichment_records_lead_id ON enrichment_records(lead_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_records_data_source_id ON enrichment_records(data_source_id);

-- Marketing Lists table
CREATE TABLE IF NOT EXISTS marketing_lists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    filter_criteria JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_marketing_lists_user_id ON marketing_lists(user_id);

-- Marketing List Members table
CREATE TABLE IF NOT EXISTS marketing_list_members (
    id SERIAL PRIMARY KEY,
    marketing_list_id INTEGER NOT NULL REFERENCES marketing_lists(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    outreach_status VARCHAR(20) NOT NULL DEFAULT 'not_contacted',
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status_updated_at TIMESTAMP,
    CONSTRAINT uq_list_member UNIQUE (marketing_list_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_mlm_marketing_list_id ON marketing_list_members(marketing_list_id);
CREATE INDEX IF NOT EXISTS idx_mlm_lead_id ON marketing_list_members(lead_id);
CREATE INDEX IF NOT EXISTS idx_mlm_outreach_status ON marketing_list_members(outreach_status);
