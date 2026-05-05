# Implementation Plan: Lead Scoring Engine

## Overview

Implement a deterministic, explainable lead scoring engine that replaces the existing single-float `lead_score` with a richer, versioned scoring architecture. The engine computes separate scores for residential and commercial leads using point-based rules, stores full score breakdowns in a dedicated `lead_scores` table, tracks missing data, computes a data quality score, and recommends a next action for each lead.

## Tasks

- [x] 1. Create LeadScore model and database migration
  - [x] 1.1 Create the LeadScore SQLAlchemy model
    - Create `backend/app/models/lead_score.py` with the `LeadScore` class
    - Define all columns: id, lead_id (FK), property_id, score_version, total_score, score_tier, data_quality_score, recommended_action, top_signals (JSON), score_details (JSON), missing_data (JSON), created_at
    - Add relationship to Lead model with backref `score_records` ordered by created_at desc
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.2 Register LeadScore model in models __init__.py
    - Add import of `LeadScore` from `app.models.lead_score` in `backend/app/models/__init__.py`
    - Add `LeadScore` to the `__all__` list
    - _Requirements: 1.1_

  - [x] 1.3 Create Alembic migration for lead_scores table
    - Create `backend/alembic_migrations/versions/b2c3d4e5f6g7_add_lead_scores_table.py`
    - Define upgrade() with create_table for lead_scores including JSONB columns with server defaults
    - Add indexes on lead_id, created_at, and score_tier
    - Define downgrade() with drop_table
    - _Requirements: 1.1, 1.4_

- [x] 2. Implement DeterministicScoringEngine service
  - [x] 2.1 Create the DeterministicScoringEngine class with residential scoring
    - Create `backend/app/services/deterministic_scoring_engine.py`
    - Implement `calculate_residential_score(lead)` returning dict with total_score, score_details, score_version
    - Implement all 8 residential dimensions: property_type_fit, neighborhood_fit, unit_count_fit, absentee_owner, owner_mailing_quality, years_owned, existing_notes_motivation, manual_priority
    - Each dimension must respect its defined maximum points
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [x] 2.2 Implement commercial scoring logic
    - Add `calculate_commercial_score(lead)` returning dict with total_score, score_details, score_version
    - Implement all 9 commercial dimensions: property_type_fit, condo_clarity, building_sale_possible, neighborhood_fit, owner_concentration, absentee_owner, building_size_fit, existing_notes_motivation, manual_priority
    - Each dimension must respect its defined maximum points
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 2.3 Implement data quality scoring and missing data detection
    - Add `calculate_data_quality_score(lead)` returning tuple of (score, missing_fields_list)
    - Implement 8 field checks: has_pin, has_property_address, has_normalized_address, has_owner_name, has_owner_mailing_address, has_property_type_or_assessor_class, has_estimated_unit_count_or_building_size, has_source_reference
    - Award full points for present/non-empty fields, zero for absent/empty
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4_

  - [x] 2.4 Implement tier calculation, recommended action, and top signals
    - Add `calculate_score_tier(total_score)` returning A/B/C/D based on defined thresholds
    - Add `get_recommended_action(lead, total_score, data_quality_score, score_tier)` implementing the full decision tree (do_not_contact → condo overrides → tier-based)
    - Add `extract_top_signals(score_details)` returning sorted list of top contributing dimensions excluding zeros
    - _Requirements: 1.2, 1.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 7.1, 7.2, 7.3, 7.4_

  - [x] 2.5 Implement orchestration methods (DB-touching)
    - Add `recalculate_lead_score(lead)` that computes all scores, determines tier/action/signals, and persists a new LeadScore record
    - Add `recalculate_all_lead_scores()` that iterates all leads and creates new records (batch processing)
    - Add `recalculate_by_source_type(source_type)` that filters leads by source_type before scoring
    - Category dispatch: use residential scoring when lead_category is "residential", commercial when "commercial"
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 14.1, 14.2, 14.3, 14.4_

  - [x] 2.6 Register DeterministicScoringEngine in services __init__.py
    - Add import of `DeterministicScoringEngine` from `app.services.deterministic_scoring_engine` in `backend/app/services/__init__.py`
    - Add to `__all__` list
    - _Requirements: 8.6_

- [x] 3. Checkpoint - Verify scoring engine logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement lead score API controller
  - [x] 4.1 Create lead_score_controller blueprint
    - Create `backend/app/controllers/lead_score_controller.py`
    - Define `lead_score_bp` Blueprint registered at `/api/lead-scores`
    - Implement GET `/api/lead-scores/<lead_id>` returning latest score + history
    - Implement POST `/api/lead-scores/recalculate` accepting lead_id, source_type, or all=true
    - Include proper error handling (400 for invalid params, 404 for missing lead, 500 for DB errors)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 4.2 Register lead_score_bp in app factory
    - Add blueprint import and registration in `backend/app/__init__.py` with url_prefix `/api/lead-scores`
    - _Requirements: 9.1_

  - [ ]* 4.3 Write property test for score details sum equals total score
    - **Property 1: Score details sum equals total score**
    - **Validates: Requirements 14.4, 2.10, 3.7**

  - [ ]* 4.4 Write property test for residential scoring invariants
    - **Property 2: Residential scoring invariants**
    - **Validates: Requirements 2.1, 2.2, 2.10**

  - [ ]* 4.5 Write property test for commercial scoring invariants
    - **Property 3: Commercial scoring invariants**
    - **Validates: Requirements 3.1, 3.2, 3.7**

  - [ ]* 4.6 Write property test for data quality score correctness
    - **Property 4: Data quality score correctness**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [ ]* 4.7 Write property test for missing data detection correctness
    - **Property 5: Missing data detection correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [ ]* 4.8 Write property test for tier assignment correctness
    - **Property 6: Tier assignment correctness**
    - **Validates: Requirements 1.2**

  - [ ]* 4.9 Write property test for recommended action validity
    - **Property 7: Recommended action validity and decision tree**
    - **Validates: Requirements 1.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10**

  - [ ]* 4.10 Write property test for top signals extraction correctness
    - **Property 8: Top signals extraction correctness**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

  - [ ]* 4.11 Write property test for scoring determinism
    - **Property 9: Scoring determinism**
    - **Validates: Requirements 14.1**

  - [ ]* 4.12 Write property test for category-based algorithm dispatch
    - **Property 10: Category-based algorithm dispatch**
    - **Validates: Requirements 8.4, 8.5**

- [x] 5. Checkpoint - Verify backend is complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Add frontend types and API service methods
  - [x] 6.1 Add lead scoring TypeScript types
    - Add `LeadScoreRecord`, `RecommendedAction`, `ScoreSignal`, `LeadScoreResponse`, `RecalculateRequest`, `RecalculateResponse` interfaces/types to `frontend/src/types/index.ts`
    - _Requirements: 10.1, 11.1_

  - [x] 6.2 Add leadScoreService to API layer
    - Add `leadScoreService` object to `frontend/src/services/api.ts` with `getLeadScore(leadId)` and `recalculate(params)` methods
    - _Requirements: 9.1, 9.4_

- [x] 7. Implement frontend score display components
  - [x] 7.1 Create LeadScoreBadge component
    - Create `frontend/src/components/LeadScoreBadge.tsx`
    - Display color-coded tier badge (A=green, B=blue, C=yellow, D=red)
    - Handle "Not scored" state when no score record exists
    - _Requirements: 10.3, 10.2_

  - [x] 7.2 Create ScoreBreakdownCard component
    - Create `frontend/src/components/ScoreBreakdownCard.tsx`
    - Display full score details with dimension names and point values
    - Show total_score, score_tier, data_quality_score, recommended_action, score_version
    - Display top_signals list and missing_data list with human-readable labels
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 7.3 Create ScoreHistoryTimeline component
    - Create `frontend/src/components/ScoreHistoryTimeline.tsx`
    - Display chronological list of past LeadScoreRecords with created_at timestamps
    - Show score changes over time
    - _Requirements: 11.4_

  - [x] 7.4 Create ScoreFilterPanel component
    - Create `frontend/src/components/ScoreFilterPanel.tsx`
    - Provide filter controls for: score_tier (A/B/C/D), recommended_action, data_quality_score < 70, missing PIN, missing owner mailing address, condo_risk_status needs_review, condo_risk_status likely_condo
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 7.5 Create RecalculateButton component
    - Create `frontend/src/components/RecalculateButton.tsx`
    - Support single lead recalculation (for detail page) and bulk recalculation (for list page)
    - Show loading indicator while recalculation is in progress, disable button during operation
    - Invalidate React Query cache on success
    - _Requirements: 11.5, 12.1, 12.2, 12.3_

- [x] 8. Integrate scoring into existing Lead pages
  - [x] 8.1 Integrate LeadScoreBadge and score columns into LeadList component
    - Modify existing LeadList component to display score_tier badge, total_score, data_quality_score, recommended_action, top signal, and missing data count columns
    - Add ScoreFilterPanel to the list page
    - Add bulk "Recalculate All Scores" button using RecalculateButton
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 12.1_

  - [x] 8.2 Integrate ScoreBreakdownCard and ScoreHistoryTimeline into LeadDetail component
    - Modify existing LeadDetail component to include a Lead Score section
    - Add ScoreBreakdownCard showing full breakdown
    - Add ScoreHistoryTimeline showing score history
    - Add single-lead RecalculateButton
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [ ]* 8.3 Write unit tests for frontend scoring components
    - Test LeadScoreBadge renders correct colors for each tier
    - Test ScoreBreakdownCard displays all dimensions
    - Test ScoreFilterPanel emits correct filter values
    - Test RecalculateButton loading/disabled states
    - _Requirements: 10.3, 11.1, 13.1, 12.2_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The existing `LeadScoringEngine` and `ScoringWeights` model remain untouched for backward compatibility
- Property tests validate universal correctness properties using Hypothesis
- Unit tests validate specific examples and edge cases
- All scoring functions are pure (no DB access) making them trivially testable
