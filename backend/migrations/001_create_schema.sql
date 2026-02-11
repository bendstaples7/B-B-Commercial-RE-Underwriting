-- Migration 001: Create comprehensive database schema for Real Estate Analysis Platform
-- This migration creates all tables with proper relationships and indexes

-- Create ENUM types
CREATE TYPE property_type AS ENUM ('single_family', 'multi_family', 'commercial');
CREATE TYPE construction_type AS ENUM ('frame', 'brick', 'masonry');
CREATE TYPE interior_condition AS ENUM ('needs_gut', 'poor', 'average', 'new_reno', 'high_end');
CREATE TYPE workflow_step AS ENUM ('PROPERTY_FACTS', 'COMPARABLE_SEARCH', 'COMPARABLE_REVIEW', 'WEIGHTED_SCORING', 'VALUATION_MODELS', 'REPORT_GENERATION');
CREATE TYPE scenario_type AS ENUM ('wholesale', 'fix_flip', 'buy_hold');

-- Analysis Sessions table (created first due to foreign key dependencies)
CREATE TABLE IF NOT EXISTS analysis_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_step workflow_step NOT NULL DEFAULT 'PROPERTY_FACTS'
);

-- Property Facts table
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
);

-- Comparable Sales table
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
);

-- Ranked Comparables table
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
);

-- Valuation Results table
CREATE TABLE IF NOT EXISTS valuation_results (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL UNIQUE REFERENCES analysis_sessions(id),
    conservative_arv DECIMAL(12,2) NOT NULL,
    likely_arv DECIMAL(12,2) NOT NULL,
    aggressive_arv DECIMAL(12,2) NOT NULL,
    all_valuations DECIMAL(12,2)[],
    key_drivers TEXT[]
);

-- Comparable Valuations table
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
);

-- Scenarios table (base table for polymorphic scenarios)
CREATE TABLE IF NOT EXISTS scenarios (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id),
    scenario_type scenario_type NOT NULL,
    purchase_price DECIMAL(12,2) NOT NULL,
    summary JSONB NOT NULL,
    type VARCHAR(50)
);

-- Wholesale Scenarios table
CREATE TABLE IF NOT EXISTS wholesale_scenarios (
    id INTEGER PRIMARY KEY REFERENCES scenarios(id),
    mao DECIMAL(12,2) NOT NULL,
    contract_price DECIMAL(12,2) NOT NULL,
    assignment_fee_low DECIMAL(12,2) NOT NULL,
    assignment_fee_high DECIMAL(12,2) NOT NULL,
    estimated_repairs DECIMAL(12,2) NOT NULL
);

-- Fix Flip Scenarios table
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
);

-- Buy Hold Scenarios table
CREATE TABLE IF NOT EXISTS buy_hold_scenarios (
    id INTEGER PRIMARY KEY REFERENCES scenarios(id),
    market_rent DECIMAL(10,2) NOT NULL,
    capital_structures JSONB NOT NULL,
    price_points JSONB NOT NULL
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_property_facts_address ON property_facts(address);
CREATE INDEX IF NOT EXISTS idx_property_facts_session_id ON property_facts(session_id);
CREATE INDEX IF NOT EXISTS idx_comparable_sales_address ON comparable_sales(address);
CREATE INDEX IF NOT EXISTS idx_comparable_sales_session_id ON comparable_sales(session_id);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_session_id ON analysis_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user_id ON analysis_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_ranked_comparables_session_id ON ranked_comparables(session_id);
CREATE INDEX IF NOT EXISTS idx_valuation_results_session_id ON valuation_results(session_id);
CREATE INDEX IF NOT EXISTS idx_comparable_valuations_valuation_result_id ON comparable_valuations(valuation_result_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_session_id ON scenarios(session_id);
