"""Initial schema — all tables from 001_create_schema.sql, 002_lead_management.sql, 003_add_lead_category.sql

Revision ID: 000000000000
Revises:
Create Date: 2026-06-09 00:00:00.000000

This migration consolidates the three raw SQL files that were applied manually
before Alembic was introduced:
  - migrations/001_create_schema.sql
  - migrations/002_lead_management.sql
  - migrations/003_add_lead_category.sql

It creates the complete pre-Alembic schema using IF NOT EXISTS / EXCEPTION WHEN
duplicate_object so it is safe to run on both fresh databases (CI, new VPS,
staging) and databases that were already seeded manually (no-op on existing
objects).

After this migration runs, every table assumed by subsequent migrations exists.
No external psql seeding step is needed.
"""
from alembic import op

revision = '000000000000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 001_create_schema.sql — analysis pipeline tables
    # ------------------------------------------------------------------

    # Enum types (with EXCEPTION WHEN duplicate_object for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE workflow_step AS ENUM (
                'PROPERTY_FACTS', 'COMPARABLE_SEARCH', 'COMPARABLE_REVIEW',
                'WEIGHTED_SCORING', 'VALUATION_MODELS', 'REPORT_GENERATION'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE property_type AS ENUM ('single_family', 'multi_family', 'commercial');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE construction_type AS ENUM ('frame', 'brick', 'masonry');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE interior_condition AS ENUM (
                'needs_gut', 'poor', 'average', 'new_reno', 'high_end'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE scenario_type AS ENUM ('wholesale', 'fix_flip', 'buy_hold');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS analysis_sessions (
            id SERIAL PRIMARY KEY,
            session_id VARCHAR(255) UNIQUE NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            current_step workflow_step NOT NULL DEFAULT 'PROPERTY_FACTS'
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS property_facts (
            id SERIAL PRIMARY KEY,
            address VARCHAR(500) NOT NULL,
            property_type property_type NOT NULL,
            units INTEGER NOT NULL,
            bedrooms INTEGER NOT NULL,
            bathrooms DECIMAL(3,1) NOT NULL,
            square_footage INTEGER NOT NULL,
            lot_size INTEGER NOT NULL,
            year_built INTEGER NOT NULL,
            construction_type construction_type NOT NULL,
            basement BOOLEAN NOT NULL DEFAULT FALSE,
            parking_spaces INTEGER NOT NULL DEFAULT 0,
            last_sale_price DECIMAL(12,2),
            last_sale_date DATE,
            assessed_value DECIMAL(12,2) NOT NULL,
            annual_taxes DECIMAL(10,2) NOT NULL,
            zoning VARCHAR(50) NOT NULL,
            interior_condition interior_condition NOT NULL,
            latitude DECIMAL(10,8),
            longitude DECIMAL(11,8),
            data_source VARCHAR(100),
            user_modified_fields TEXT[],
            session_id INTEGER REFERENCES analysis_sessions(id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS comparable_sales (
            id SERIAL PRIMARY KEY,
            address VARCHAR(500) NOT NULL,
            sale_date DATE NOT NULL,
            sale_price DECIMAL(12,2) NOT NULL,
            property_type property_type NOT NULL,
            units INTEGER NOT NULL,
            bedrooms INTEGER NOT NULL,
            bathrooms DECIMAL(3,1) NOT NULL,
            square_footage INTEGER NOT NULL,
            lot_size INTEGER NOT NULL,
            year_built INTEGER NOT NULL,
            construction_type construction_type NOT NULL,
            interior_condition interior_condition NOT NULL,
            distance_miles DECIMAL(5,2) NOT NULL,
            latitude DECIMAL(10,8),
            longitude DECIMAL(11,8),
            similarity_notes TEXT,
            session_id INTEGER NOT NULL REFERENCES analysis_sessions(id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ranked_comparables (
            id SERIAL PRIMARY KEY,
            comparable_id INTEGER NOT NULL REFERENCES comparable_sales(id),
            session_id INTEGER NOT NULL REFERENCES analysis_sessions(id),
            rank INTEGER NOT NULL,
            total_score DECIMAL(5,2) NOT NULL,
            recency_score DECIMAL(5,2) NOT NULL,
            proximity_score DECIMAL(5,2) NOT NULL,
            units_score DECIMAL(5,2) NOT NULL,
            beds_baths_score DECIMAL(5,2) NOT NULL,
            sqft_score DECIMAL(5,2) NOT NULL,
            construction_score DECIMAL(5,2) NOT NULL,
            interior_score DECIMAL(5,2) NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS valuation_results (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL UNIQUE REFERENCES analysis_sessions(id),
            conservative_arv DECIMAL(12,2) NOT NULL,
            likely_arv DECIMAL(12,2) NOT NULL,
            aggressive_arv DECIMAL(12,2) NOT NULL,
            all_valuations DECIMAL(12,2)[],
            key_drivers TEXT[]
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS comparable_valuations (
            id SERIAL PRIMARY KEY,
            valuation_result_id INTEGER NOT NULL REFERENCES valuation_results(id),
            comparable_id INTEGER NOT NULL REFERENCES comparable_sales(id),
            price_per_sqft DECIMAL(10,2) NOT NULL,
            price_per_unit DECIMAL(12,2) NOT NULL,
            price_per_bedroom DECIMAL(12,2) NOT NULL,
            adjusted_value DECIMAL(12,2) NOT NULL,
            adjustments JSONB,
            narrative TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES analysis_sessions(id),
            scenario_type scenario_type NOT NULL,
            purchase_price DECIMAL(12,2) NOT NULL,
            summary JSONB NOT NULL,
            type VARCHAR(50)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wholesale_scenarios (
            id INTEGER PRIMARY KEY REFERENCES scenarios(id),
            mao DECIMAL(12,2) NOT NULL,
            contract_price DECIMAL(12,2) NOT NULL,
            assignment_fee_low DECIMAL(12,2) NOT NULL,
            assignment_fee_high DECIMAL(12,2) NOT NULL,
            estimated_repairs DECIMAL(12,2) NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS fix_flip_scenarios (
            id INTEGER PRIMARY KEY REFERENCES scenarios(id),
            acquisition_cost DECIMAL(12,2) NOT NULL,
            renovation_cost DECIMAL(12,2) NOT NULL,
            holding_costs DECIMAL(12,2) NOT NULL,
            financing_costs DECIMAL(12,2) NOT NULL,
            closing_costs DECIMAL(12,2) NOT NULL,
            total_cost DECIMAL(12,2) NOT NULL,
            exit_value DECIMAL(12,2) NOT NULL,
            net_profit DECIMAL(12,2) NOT NULL,
            roi DECIMAL(5,2) NOT NULL,
            months_to_flip INTEGER NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS buy_hold_scenarios (
            id INTEGER PRIMARY KEY REFERENCES scenarios(id),
            market_rent DECIMAL(10,2) NOT NULL,
            capital_structures JSONB NOT NULL,
            price_points JSONB NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_address ON property_facts(address)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_property_facts_session_id ON property_facts(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_address ON comparable_sales(address)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_sales_session_id ON comparable_sales(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_session_id ON analysis_sessions(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user_id ON analysis_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ranked_comparables_session_id ON ranked_comparables(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_valuation_results_session_id ON valuation_results(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_session_id ON scenarios(session_id)")

    # ------------------------------------------------------------------
    # 002_lead_management.sql — lead management tables
    # ------------------------------------------------------------------

    op.execute("""
        CREATE TABLE IF NOT EXISTS field_mappings (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            spreadsheet_id VARCHAR(255) NOT NULL,
            sheet_name VARCHAR(255) NOT NULL,
            mapping JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_field_mapping UNIQUE (user_id, spreadsheet_id, sheet_name)
        )
    """)
    op.execute("""
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
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_import_jobs_user_id ON import_jobs(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL UNIQUE,
            encrypted_refresh_token BYTEA NOT NULL,
            token_expiry TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS scoring_weights (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL UNIQUE,
            property_characteristics_weight DECIMAL(3,2) NOT NULL DEFAULT 0.30,
            data_completeness_weight DECIMAL(3,2) NOT NULL DEFAULT 0.20,
            owner_situation_weight DECIMAL(3,2) NOT NULL DEFAULT 0.30,
            location_desirability_weight DECIMAL(3,2) NOT NULL DEFAULT 0.20,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_sources (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            endpoint_url VARCHAR(500),
            config JSONB DEFAULT '{}',
            field_mapping JSONB DEFAULT '{}',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
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
            owner_first_name VARCHAR(128) NOT NULL,
            owner_last_name VARCHAR(128),
            ownership_type VARCHAR(100),
            acquisition_date DATE,
            phone_1 TEXT,
            phone_2 TEXT,
            phone_3 TEXT,
            email_1 VARCHAR(255),
            email_2 VARCHAR(255),
            mailing_address VARCHAR(500),
            mailing_city VARCHAR(100),
            mailing_state VARCHAR(50),
            mailing_zip VARCHAR(20),
            source VARCHAR(100),
            date_identified DATE,
            notes TEXT,
            needs_skip_trace BOOLEAN DEFAULT FALSE,
            skip_tracer VARCHAR(100),
            date_skip_traced DATE,
            date_added_to_hubspot DATE,
            units INTEGER,
            units_allowed INTEGER,
            zoning VARCHAR(100),
            county_assessor_pin VARCHAR(50),
            tax_bill_2021 DECIMAL(12,2),
            most_recent_sale VARCHAR(255),
            owner_2_first_name VARCHAR(128),
            owner_2_last_name VARCHAR(128),
            address_2 VARCHAR(500),
            returned_addresses TEXT,
            phone_4 TEXT,
            phone_5 TEXT,
            phone_6 TEXT,
            phone_7 TEXT,
            email_3 VARCHAR(255),
            email_4 VARCHAR(255),
            email_5 VARCHAR(255),
            socials TEXT,
            up_next_to_mail BOOLEAN DEFAULT FALSE,
            mailer_history JSONB,
            lead_score DECIMAL(5,2) DEFAULT 0,
            data_source VARCHAR(100),
            last_import_job_id INTEGER REFERENCES import_jobs(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            analysis_session_id INTEGER REFERENCES analysis_sessions(id),
            CONSTRAINT uq_leads_property_street UNIQUE (property_street)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_owner_first_name ON leads(owner_first_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_owner_last_name ON leads(owner_last_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_mailing_state ON leads(mailing_state)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_mailing_zip ON leads(mailing_zip)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_mailing_city ON leads(mailing_city)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_lead_score ON leads(lead_score)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_property_type ON leads(property_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS lead_audit_trail (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            field_name VARCHAR(100) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            changed_by VARCHAR(100) NOT NULL,
            changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_lead_audit_trail_lead_id ON lead_audit_trail(lead_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_records (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            data_source_id INTEGER NOT NULL REFERENCES data_sources(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            retrieved_data JSONB,
            error_reason TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_enrichment_records_lead_id ON enrichment_records(lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_enrichment_records_data_source_id ON enrichment_records(data_source_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_lists (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            filter_criteria JSONB,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_marketing_lists_user_id ON marketing_lists(user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_list_members (
            id SERIAL PRIMARY KEY,
            marketing_list_id INTEGER NOT NULL REFERENCES marketing_lists(id) ON DELETE CASCADE,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            outreach_status VARCHAR(20) NOT NULL DEFAULT 'not_contacted',
            added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status_updated_at TIMESTAMP,
            CONSTRAINT uq_list_member UNIQUE (marketing_list_id, lead_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mlm_marketing_list_id ON marketing_list_members(marketing_list_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mlm_lead_id ON marketing_list_members(lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mlm_outreach_status ON marketing_list_members(outreach_status)")

    # ------------------------------------------------------------------
    # 003_add_lead_category.sql — lead_category column
    # ------------------------------------------------------------------

    op.execute("""
        ALTER TABLE leads
            ADD COLUMN IF NOT EXISTS lead_category VARCHAR(50) NOT NULL DEFAULT 'residential'
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_lead_category ON leads(lead_category)")

    # ------------------------------------------------------------------
    # users table — created outside Alembic before migrations were introduced
    # ------------------------------------------------------------------

    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL UNIQUE,
            email VARCHAR(254) NOT NULL UNIQUE,
            email_lower VARCHAR(254) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(100) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            password_set BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_user_id ON users(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users(email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users(email_lower)")


def downgrade():
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS marketing_list_members")
    op.execute("DROP TABLE IF EXISTS marketing_lists")
    op.execute("DROP TABLE IF EXISTS enrichment_records")
    op.execute("DROP TABLE IF EXISTS lead_audit_trail")
    op.execute("DROP TABLE IF EXISTS leads")
    op.execute("DROP TABLE IF EXISTS data_sources")
    op.execute("DROP TABLE IF EXISTS scoring_weights")
    op.execute("DROP TABLE IF EXISTS oauth_tokens")
    op.execute("DROP TABLE IF EXISTS import_jobs")
    op.execute("DROP TABLE IF EXISTS field_mappings")
    op.execute("DROP TABLE IF EXISTS wholesale_scenarios")
    op.execute("DROP TABLE IF EXISTS fix_flip_scenarios")
    op.execute("DROP TABLE IF EXISTS buy_hold_scenarios")
    op.execute("DROP TABLE IF EXISTS scenarios")
    op.execute("DROP TABLE IF EXISTS comparable_valuations")
    op.execute("DROP TABLE IF EXISTS valuation_results")
    op.execute("DROP TABLE IF EXISTS ranked_comparables")
    op.execute("DROP TABLE IF EXISTS comparable_sales")
    op.execute("DROP TABLE IF EXISTS property_facts")
    op.execute("DROP TABLE IF EXISTS analysis_sessions")
    op.execute("DROP TYPE IF EXISTS scenario_type")
    op.execute("DROP TYPE IF EXISTS interior_condition")
    op.execute("DROP TYPE IF EXISTS construction_type")
    op.execute("DROP TYPE IF EXISTS property_type")
    op.execute("DROP TYPE IF EXISTS workflow_step")
