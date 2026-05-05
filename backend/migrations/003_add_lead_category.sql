-- Migration: Add lead_category column to leads table
-- Differentiates residential vs commercial leads
-- All existing leads are backfilled as 'residential'

ALTER TABLE leads
    ADD COLUMN lead_category VARCHAR(50) NOT NULL DEFAULT 'residential';

-- Explicitly backfill any rows that might have been inserted without the default
UPDATE leads SET lead_category = 'residential' WHERE lead_category IS NULL;

-- Index for filtering by category
CREATE INDEX idx_leads_lead_category ON leads(lead_category);
