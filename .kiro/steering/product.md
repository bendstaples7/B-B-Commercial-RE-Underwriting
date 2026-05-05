# Product Overview

Real Estate Analysis Platform — a web application for real estate investors to analyze properties, manage leads, and run marketing campaigns.

## Core Domains

- **Property Analysis**: Multi-step workflow (property facts → comparable search → comparable review → weighted scoring → valuation → report) that produces ARV (After Repair Value) estimates with wholesale, fix-flip, and buy-hold scenario modeling.
- **Lead Management**: Import property owner leads from Google Sheets, score them with configurable weighted criteria, enrich with external data sources, and track through an audit trail.
- **Marketing**: Create marketing lists from leads, manage outreach status, and track mailer history.
- **Reporting**: Generate analysis reports exportable to Excel and Google Sheets.

## Key Concepts

- **AnalysisSession**: Stateful workflow session tied to a property address, progressing through six ordered steps.
- **Lead**: A property owner record with property details, contact info, skip-trace data, and a computed lead score (0–100).
- **ScoringWeights**: Per-user configurable weights for four scoring dimensions (property characteristics, data completeness, owner situation, location desirability) that must sum to 1.0.
- **ComparableSale / RankedComparable**: Nearby property sales ranked by a weighted scoring engine for valuation.
- **Scenario**: Investment analysis (wholesale, fix-flip, buy-hold) computed from valuation results.
