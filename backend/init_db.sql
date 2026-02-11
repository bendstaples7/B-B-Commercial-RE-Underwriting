-- Initial database schema for Real Estate Analysis Platform

-- Create database (run this separately if needed)
-- CREATE DATABASE real_estate_analysis;

-- Property Facts table
CREATE TABLE IF NOT EXISTS property_facts (
    id SERIAL PRIMARY KEY,
    address VARCHAR(255) NOT NULL,
    property_type VARCHAR(50) NOT NULL,
    units INTEGER NOT NULL,
    bedrooms INTEGER NOT NULL,
    bathrooms DECIMAL(3,1) NOT NULL,
    square_footage INTEGER,
    lot_size INTEGER,
    year_built INTEGER,
    construction_type VARCHAR(50),
    basement BOOLEAN DEFAULT FALSE,
    parking_spaces INTEGER DEFAULT 0,
    last_sale_price DECIMAL(12,2),
    last_sale_date DATE,
    assessed_value DECIMAL(12,2),
    annual_taxes DECIMAL(10,2),
    zoning VARCHAR(50),
    interior_condition VARCHAR(50),
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    data_source VARCHAR(100),
    user_modified_fields TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Comparable Sales table
CREATE TABLE IF NOT EXISTS comparable_sales (
    id SERIAL PRIMARY KEY,
    address VARCHAR(255) NOT NULL,
    sale_date DATE NOT NULL,
    sale_price DECIMAL(12,2) NOT NULL,
    property_type VARCHAR(50) NOT NULL,
    units INTEGER NOT NULL,
    bedrooms INTEGER NOT NULL,
    bathrooms DECIMAL(3,1) NOT NULL,
    square_footage INTEGER,
    lot_size INTEGER,
    year_built INTEGER,
    construction_type VARCHAR(50),
    interior_condition VARCHAR(50),
    distance_miles DECIMAL(5,2),
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Analysis Sessions table
CREATE TABLE IF NOT EXISTS analysis_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 1,
    subject_property_id INTEGER REFERENCES property_facts(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Session Comparables junction table
CREATE TABLE IF NOT EXISTS session_comparables (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    comparable_id INTEGER REFERENCES comparable_sales(id) ON DELETE CASCADE,
    rank INTEGER,
    total_score DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_property_facts_address ON property_facts(address);
CREATE INDEX IF NOT EXISTS idx_comparable_sales_sale_date ON comparable_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_session_id ON analysis_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user_id ON analysis_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_session_comparables_session_id ON session_comparables(session_id);
