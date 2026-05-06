# Requirements Document

## Introduction

A deterministic lead scoring engine for the real estate deal sourcing platform that ranks properties/leads so the user knows which targets to review, enrich, mail, call, or suppress first. The engine uses separate scoring logic for residential and commercial leads, stores versioned score records with full breakdowns, tracks missing data, computes a separate data quality score, and recommends a next action for each lead. No AI or machine learning is used. This feature replaces the existing single-float `lead_score` with a richer, explainable scoring system and serves as the foundation for future Chicago public data enrichment.

## Glossary

- **Scoring_Engine**: The backend service that computes lead scores deterministically based on property and owner data
- **Lead_Score_Record**: A persisted record in the `lead_scores` table containing the full score breakdown for a single lead at a point in time
- **Score_Version**: A string identifier for the scoring algorithm variant used (e.g., `residential_v1_internal_data`, `commercial_v1_internal_data`)
- **Score_Tier**: A letter grade (A, B, C, D) derived from the total score indicating lead attractiveness
- **Data_Quality_Score**: A separate 0-100 score measuring how complete and reliable the underlying data is for a lead
- **Recommended_Action**: A suggested next step for the user based on score tier, data quality, and lead attributes
- **Missing_Data**: A structured list of data fields that are absent for a given lead but would improve scoring accuracy
- **Score_Details**: A JSONB object containing the point breakdown for every scoring dimension
- **Top_Signals**: A JSONB array of the highest-contributing scoring dimensions for a lead
- **Lead_List_Page**: The frontend page displaying all leads in a paginated table
- **Lead_Detail_Page**: The frontend page displaying full information for a single lead
- **Recalculation**: The process of computing a new score for one or more leads and storing the result as a new record

## Requirements

### Requirement 1: Lead Scores Database Schema

**User Story:** As a developer, I want a dedicated `lead_scores` table that stores versioned score records with full breakdowns, so that score history is preserved and every score is explainable.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL persist Lead_Score_Records in a `lead_scores` table with columns: id (primary key), lead_id (foreign key to leads), property_id (nullable integer), score_version (string), total_score (float), score_tier (string), data_quality_score (float), recommended_action (string), top_signals (JSONB), score_details (JSONB), missing_data (JSONB), created_at (timestamp)
2. WHEN a Lead_Score_Record is created, THE Scoring_Engine SHALL set score_tier to "A" for total_score 75-100, "B" for 60-74, "C" for 40-59, or "D" for 0-39
3. THE Scoring_Engine SHALL constrain recommended_action to one of: review_now, enrich_data, mail_ready, call_ready, valuation_needed, suppress, nurture, needs_manual_review
4. THE Scoring_Engine SHALL store lead_id as a non-null foreign key referencing the leads table
5. WHEN a new Lead_Score_Record is created, THE Scoring_Engine SHALL NOT delete or modify any existing Lead_Score_Records for the same lead

### Requirement 2: Residential Scoring Logic

**User Story:** As a real estate investor, I want residential leads scored on property fit, neighborhood, unit count, absentee ownership, mailing quality, years owned, motivation notes, and manual priority, so that I can identify the most attractive residential targets.

#### Acceptance Criteria

1. WHEN a residential lead is scored, THE Scoring_Engine SHALL use score_version "residential_v1_internal_data" with a maximum total of 100 points
2. WHEN a residential lead is scored, THE Scoring_Engine SHALL allocate points across dimensions: property_type_fit (max 20), neighborhood_fit (max 15), unit_count_fit (max 15), absentee_owner (max 10), owner_mailing_quality (max 10), years_owned (max 10), existing_notes_motivation (max 10), manual_priority (max 10)
3. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute property_type_fit based on the lead's property_type matching desirable residential types (multi-family, 2-4 unit preferred)
4. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute unit_count_fit based on the lead's estimated unit count (2-4 units scoring highest for residential)
5. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute absentee_owner as 10 points when the owner mailing address differs from the property address, and 0 otherwise
6. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute owner_mailing_quality based on whether a valid owner mailing address exists
7. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute years_owned based on the acquisition_date field, awarding more points for longer ownership duration
8. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute existing_notes_motivation by detecting motivation keywords in the lead's notes field
9. WHEN a residential lead is scored, THE Scoring_Engine SHALL compute manual_priority based on any user-assigned priority value on the lead
10. WHEN a residential lead is scored, THE Scoring_Engine SHALL store the per-dimension point values in score_details

### Requirement 3: Commercial Scoring Logic

**User Story:** As a real estate investor, I want commercial leads scored with different logic that accounts for condo risk, building sale possibility, and owner concentration, so that I can identify viable commercial acquisition targets.

#### Acceptance Criteria

1. WHEN a commercial lead is scored, THE Scoring_Engine SHALL use score_version "commercial_v1_internal_data" with a maximum total of 100 points
2. WHEN a commercial lead is scored, THE Scoring_Engine SHALL allocate points across dimensions: property_type_fit (max 20), condo_clarity (max 20), building_sale_possible (max 15), neighborhood_fit (max 10), owner_concentration (max 10), absentee_owner (max 10), building_size_fit (max 5), existing_notes_motivation (max 5), manual_priority (max 5)
3. WHEN a commercial lead is scored, THE Scoring_Engine SHALL compute condo_clarity based on the lead's condo_risk_status field, awarding maximum points when condo_risk_status is "likely_not_condo"
4. WHEN a commercial lead is scored, THE Scoring_Engine SHALL compute building_sale_possible based on the lead's building_sale_possible field, awarding maximum points when the value is "yes"
5. WHEN a commercial lead is scored, THE Scoring_Engine SHALL compute owner_concentration based on the number of distinct owners at the same normalized address (fewer owners scoring higher)
6. WHEN a commercial lead is scored, THE Scoring_Engine SHALL compute building_size_fit based on the lead's square_footage or estimated building size
7. WHEN a commercial lead is scored, THE Scoring_Engine SHALL store the per-dimension point values in score_details

### Requirement 4: Data Quality Scoring

**User Story:** As a real estate investor, I want a separate data quality score that tells me how reliable and complete the underlying data is, so that I can decide whether to enrich a lead before acting on it.

#### Acceptance Criteria

1. WHEN a lead is scored, THE Scoring_Engine SHALL compute a data_quality_score (0-100) independently from the motivation/lead score
2. THE Scoring_Engine SHALL allocate data quality points as: has_pin (20), has_property_address (15), has_normalized_address (10), has_owner_name (15), has_owner_mailing_address (15), has_property_type_or_assessor_class (10), has_estimated_unit_count_or_building_size (10), has_source_reference (5)
3. WHEN a data field is present and non-empty, THE Scoring_Engine SHALL award the full point value for that field
4. WHEN a data field is absent or empty, THE Scoring_Engine SHALL award zero points for that field
5. THE Scoring_Engine SHALL store the data_quality_score on the Lead_Score_Record

### Requirement 5: Missing Data Tracking

**User Story:** As a real estate investor, I want to see exactly which data fields are missing for each lead, so that I know what to enrich or research next.

#### Acceptance Criteria

1. WHEN a lead is scored, THE Scoring_Engine SHALL identify all missing useful fields and store them in the missing_data JSONB column
2. THE Scoring_Engine SHALL check for missing data in these fields: pin, property_address, normalized_address, owner_name, owner_mailing_address, property_type, assessor_class, estimated_units, building_sqft, years_owned, neighborhood, condo_risk_status, building_sale_possible, violation_data, permit_data, tax_data, skip_trace_data
3. WHEN a field is null or empty on the lead record, THE Scoring_Engine SHALL include that field name in the missing_data array
4. THE Scoring_Engine SHALL store missing_data as a JSONB array of field name strings

### Requirement 6: Recommended Action Logic

**User Story:** As a real estate investor, I want the system to recommend what I should do next with each lead based on its score and data quality, so that I can prioritize my workflow efficiently.

#### Acceptance Criteria

1. WHEN a lead has a do_not_contact flag, THE Scoring_Engine SHALL set recommended_action to "suppress"
2. WHEN a lead is Tier A with data_quality_score >= 70, THE Scoring_Engine SHALL set recommended_action to "mail_ready"
3. WHEN a lead is Tier A with data_quality_score < 70, THE Scoring_Engine SHALL set recommended_action to "enrich_data"
4. WHEN a lead is Tier B with data_quality_score >= 70, THE Scoring_Engine SHALL set recommended_action to "review_now"
5. WHEN a lead is Tier B with data_quality_score < 70, THE Scoring_Engine SHALL set recommended_action to "enrich_data"
6. WHEN a lead is Tier C, THE Scoring_Engine SHALL set recommended_action to "nurture"
7. WHEN a lead is Tier D, THE Scoring_Engine SHALL set recommended_action to "suppress"
8. WHEN a commercial lead has condo_risk_status "likely_condo", THE Scoring_Engine SHALL set recommended_action to "suppress"
9. WHEN a commercial lead has condo_risk_status "needs_review", THE Scoring_Engine SHALL set recommended_action to "needs_manual_review"
10. THE Scoring_Engine SHALL evaluate commercial condo/review overrides before applying tier-based action logic

### Requirement 7: Top Signals Extraction

**User Story:** As a real estate investor, I want to see the top contributing signals for each score at a glance, so that I understand why a lead is ranked the way it is.

#### Acceptance Criteria

1. WHEN a lead is scored, THE Scoring_Engine SHALL identify the scoring dimensions that contributed the most points
2. THE Scoring_Engine SHALL store the top signals as a JSONB array in the top_signals column, ordered by point contribution descending
3. WHEN a lead is scored, THE Scoring_Engine SHALL include at least the top 3 contributing dimensions in top_signals (or all dimensions if fewer than 3 have non-zero points)
4. WHEN a scoring dimension contributes zero points, THE Scoring_Engine SHALL exclude that dimension from top_signals

### Requirement 8: Score Recalculation Backend

**User Story:** As a real estate investor, I want to recalculate scores for a single lead, all leads, or leads by source type, so that scores stay current as data changes.

#### Acceptance Criteria

1. WHEN recalculation is requested for a single lead, THE Scoring_Engine SHALL compute a new score and store a new Lead_Score_Record without modifying existing records
2. WHEN recalculation is requested for all active leads, THE Scoring_Engine SHALL compute new scores for every lead and store new Lead_Score_Records
3. WHEN recalculation is requested by source_type, THE Scoring_Engine SHALL compute new scores only for leads matching that source_type
4. THE Scoring_Engine SHALL select the correct scoring algorithm (residential or commercial) based on the lead's lead_category field
5. THE Scoring_Engine SHALL preserve the score_version string on every Lead_Score_Record to identify which algorithm produced the score
6. THE Scoring_Engine SHALL expose functions: calculateResidentialLeadScore, calculateCommercialLeadScore, calculateDataQualityScore, getRecommendedAction, recalculateLeadScore, recalculateAllLeadScores

### Requirement 9: Score API Endpoints

**User Story:** As a frontend developer, I want API endpoints to trigger recalculation and retrieve score data, so that the UI can display and refresh lead scores.

#### Acceptance Criteria

1. WHEN a POST request is sent to /api/lead-scores/recalculate with a lead_id in the body, THE Scoring_Engine SHALL recalculate the score for that single lead and return the new Lead_Score_Record
2. WHEN a POST request is sent to /api/lead-scores/recalculate with source_type in the body, THE Scoring_Engine SHALL recalculate scores for all leads matching that source_type
3. WHEN a POST request is sent to /api/lead-scores/recalculate with all=true in the body, THE Scoring_Engine SHALL recalculate scores for all active leads
4. WHEN a GET request is sent to /api/lead-scores/:leadId, THE Scoring_Engine SHALL return the latest Lead_Score_Record and the full score history for that lead
5. IF a recalculation request contains invalid parameters, THEN THE Scoring_Engine SHALL return a 400 error with a descriptive message
6. IF a lead_id does not exist, THEN THE Scoring_Engine SHALL return a 404 error

### Requirement 10: Lead List Page Score Display

**User Story:** As a real estate investor, I want to see score data directly in the lead list table, so that I can quickly scan and prioritize leads without opening each one.

#### Acceptance Criteria

1. THE Lead_List_Page SHALL display columns for: latest total_score, score_tier, data_quality_score, recommended_action, top signal (first entry from top_signals), and missing data count (length of missing_data array)
2. WHEN a lead has no Lead_Score_Record, THE Lead_List_Page SHALL display empty or "Not scored" indicators in score columns
3. THE Lead_List_Page SHALL display the score_tier as a color-coded badge (A=green, B=blue, C=yellow, D=red)
4. THE Lead_List_Page SHALL display the recommended_action as a human-readable label

### Requirement 11: Lead Detail Page Score Section

**User Story:** As a real estate investor, I want a full score explanation on the lead detail page, so that I can understand exactly why a lead received its score and what data is missing.

#### Acceptance Criteria

1. THE Lead_Detail_Page SHALL display a Lead Score section containing: total_score, score_tier, data_quality_score, recommended_action, score_version, full score_details breakdown, top_signals list, missing_data list, and score history
2. THE Lead_Detail_Page SHALL display score_details as a labeled breakdown showing each dimension name and its point value
3. THE Lead_Detail_Page SHALL display missing_data as a list of human-readable field names
4. THE Lead_Detail_Page SHALL display score history as a chronological list of previous Lead_Score_Records with created_at timestamps
5. THE Lead_Detail_Page SHALL include a "Recalculate Score" button that triggers a POST to /api/lead-scores/recalculate with the current lead_id

### Requirement 12: Bulk Recalculation UI

**User Story:** As a real estate investor, I want a "Recalculate All Scores" button accessible from the lead list or admin/tools page, so that I can refresh all scores after data imports or configuration changes.

#### Acceptance Criteria

1. THE Lead_List_Page SHALL include a "Recalculate All Scores" button that triggers a POST to /api/lead-scores/recalculate with all=true
2. WHILE a bulk recalculation is in progress, THE Lead_List_Page SHALL display a loading indicator and disable the recalculate button
3. WHEN a bulk recalculation completes, THE Lead_List_Page SHALL refresh the displayed score data

### Requirement 13: Lead List Filtering by Score Data

**User Story:** As a real estate investor, I want to filter the lead list by score tier, recommended action, data quality, and specific missing data fields, so that I can focus on the leads that need my attention most.

#### Acceptance Criteria

1. THE Lead_List_Page SHALL provide a filter for score_tier allowing selection of A, B, C, or D
2. THE Lead_List_Page SHALL provide a filter for recommended_action allowing selection of any valid action value
3. THE Lead_List_Page SHALL provide a filter for data_quality_score below 70
4. THE Lead_List_Page SHALL provide a filter for leads missing PIN (pin in missing_data)
5. THE Lead_List_Page SHALL provide a filter for leads missing owner mailing address (owner_mailing_address in missing_data)
6. THE Lead_List_Page SHALL provide a filter for commercial leads with condo_risk_status "needs_review"
7. THE Lead_List_Page SHALL provide a filter for commercial leads with condo_risk_status "likely_condo" (suppressed)

### Requirement 14: Deterministic and Explainable Scoring

**User Story:** As a real estate investor, I want scoring to be fully deterministic and explainable with no AI or machine learning, so that I can trust, understand, and modify the scoring logic.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL produce identical scores when given identical input data
2. THE Scoring_Engine SHALL NOT use any machine learning models, neural networks, or probabilistic AI techniques
3. THE Scoring_Engine SHALL compute scores using only explicit point-based rules defined in code
4. FOR ALL valid lead inputs, scoring then retrieving the score_details SHALL produce a breakdown that sums to the total_score (round-trip property)

### Requirement 15: Scope Exclusions

**User Story:** As a developer, I want clear boundaries on what this feature does NOT include, so that scope remains focused on the scoring foundation.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL NOT integrate with HubSpot for syncing scores or contacts
2. THE Scoring_Engine SHALL NOT integrate with OpenLetterMarketing for export
3. THE Scoring_Engine SHALL NOT integrate with skip tracing services
4. THE Scoring_Engine SHALL NOT ingest Chicago public data (violations, permits, tax records) in this version
5. THE Scoring_Engine SHALL NOT use AI or machine learning for scoring
6. THE Scoring_Engine SHALL NOT compute property valuations as part of scoring
