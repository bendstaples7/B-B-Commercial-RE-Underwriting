# Implementation Plan: Commercial Condo Filter

## Overview

This plan implements the Commercial Condo Filter feature as a backend analysis pipeline with a frontend review UI. The implementation proceeds bottom-up: database schema first, then pure helper functions (with property tests), then the orchestrating service, then the API controller, and finally the frontend components. Each task builds on the previous, ensuring no hanging or orphaned code.

## Tasks

- [x] 1. Database schema and model layer
  - [x] 1.1 Create the AddressGroupAnalysis model
    - Create `backend/app/models/address_group_analysis.py` with the `AddressGroupAnalysis` SQLAlchemy model
    - Include all columns: id, normalized_address (unique, indexed), source_type, property_count, pin_count, owner_count, has_unit_number, has_condo_language, missing_pin_count, missing_owner_count, condo_risk_status (indexed), building_sale_possible, analysis_details (JSON), manually_reviewed (default False), manual_override_status, manual_override_reason, analyzed_at, created_at, updated_at
    - Add the `leads` relationship with backref `condo_analysis`
    - Register the model in `backend/app/models/__init__.py`
    - _Requirements: 7.1, 7.3, 7.4_

  - [x] 1.2 Extend the Lead model with condo filter columns
    - Add three new nullable columns to `backend/app/models/lead.py`: `condo_risk_status` (String(50)), `building_sale_possible` (String(50)), `condo_analysis_id` (Integer, ForeignKey to address_group_analyses.id)
    - Add the relationship to AddressGroupAnalysis
    - _Requirements: 7.2_

  - [x] 1.3 Create Alembic migration
    - Generate a new Alembic migration in `backend/alembic_migrations/versions/` that creates the `address_group_analyses` table with indexes and adds the three new columns to the `leads` table with the foreign key constraint
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 2. Pure helper functions
  - [x] 2.1 Implement address_normalizer module
    - Create `backend/app/services/helpers/__init__.py` (empty package init)
    - Create `backend/app/services/helpers/address_normalizer.py` with `normalize_address(address: str) -> str`
    - Strip unit markers (unit, apt, apartment, suite, ste, #) and their values using regex
    - Strip alphanumeric unit suffixes (e.g., "1a", "2b", "3r")
    - Normalize to lowercase, collapse whitespace, strip leading/trailing whitespace
    - Ensure idempotence: `normalize(normalize(x)) == normalize(x)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 2.2 Write property test for address normalization correctness
    - **Property 1: Address Normalization Correctness**
    - Use Hypothesis to generate addresses with known unit markers and verify they are stripped while preserving base street content
    - Use Hypothesis to generate addresses without unit markers and verify content is preserved
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

  - [ ]* 2.3 Write property test for address normalization idempotence
    - **Property 2: Address Normalization Idempotence**
    - Use Hypothesis with `st.text(min_size=1, max_size=200)` to verify `normalize(normalize(x)) == normalize(x)` for arbitrary strings
    - **Validates: Requirements 1.5, 14.1**

  - [x] 2.4 Implement unit_detector module
    - Create `backend/app/services/helpers/unit_detector.py` with `has_unit_marker(address: str) -> bool`
    - Detect case-insensitive patterns: "unit", "apt", "apartment", "suite", "ste", "#" followed by a value
    - Detect trailing alphanumeric suffix patterns (e.g., "1a", "2b", "3n")
    - Return False for addresses with no unit marker patterns
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 2.5 Write property test for unit detector correctness
    - **Property 3: Unit Detector Correctness**
    - Use Hypothesis composite strategy to generate addresses with and without injected unit markers
    - Verify returns True if and only if a recognized pattern is present
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 2.6 Implement condo_language_detector module
    - Create `backend/app/services/helpers/condo_language_detector.py` with `has_condo_language(property_type: str | None, assessor_class: str | None) -> bool`
    - Detect case-insensitive terms: "condo", "condominium", "commercial condo", "condo unit", "unit"
    - Return False when neither field contains any condo terms
    - Handle None inputs gracefully
    - _Requirements: 4.1, 4.2_

  - [ ]* 2.7 Write property test for condo language detector correctness
    - **Property 4: Condo Language Detector Correctness**
    - Use Hypothesis to generate (property_type, assessor_class) pairs with and without injected condo terms
    - Verify returns True if and only if at least one field contains a recognized term
    - **Validates: Requirements 4.1, 4.2**

  - [x] 2.8 Implement classification_engine module
    - Create `backend/app/services/helpers/classification_engine.py` with `AddressGroupMetrics` dataclass, `ClassificationResult` dataclass, and `classify(metrics: AddressGroupMetrics) -> ClassificationResult` function
    - Implement priority-ordered rules (1-8) as specified in the design
    - Return triggered_rules list, human-readable reason, and confidence (high/medium/low)
    - Ensure determinism: identical metrics always produce identical results
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10_

  - [ ]* 2.9 Write property test for classification engine determinism and rule correctness
    - **Property 6: Classification Engine Determinism and Rule Correctness**
    - Use Hypothesis with `st.builds(AddressGroupMetrics, ...)` to generate valid metrics
    - Verify: (a) result matches exactly one rule, (b) identical input produces identical output, (c) triggered_rules, reason, and confidence are non-empty
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Backend service layer
  - [x] 4.1 Implement CondoFilterService
    - Create `backend/app/services/condo_filter_service.py` with `CondoFilterService` class
    - Implement `run_analysis()`: query commercial/mixed-use leads, normalize addresses, group by normalized address, compute metrics (property_count, pin_count, owner_count, missing_pin_count, missing_owner_count, has_unit_number, has_condo_language), classify each group, upsert AddressGroupAnalysis records, update linked Lead records, return summary counts
    - Implement `get_results(filters, page, per_page)`: paginated filtered query on AddressGroupAnalysis
    - Implement `get_detail(analysis_id)`: full record with linked leads
    - Implement `apply_override(analysis_id, status, building_sale, reason)`: update override fields, set manually_reviewed=True, cascade to linked leads
    - Implement `export_csv(filters)`: generate CSV content with all required columns, respect filters, concatenate multi-valued fields with delimiter
    - Handle batch processing for large datasets (>500 leads per batch)
    - Preserve manual_override_status and manual_override_reason during re-analysis
    - Skip leads with null property_street during grouping
    - Register in `backend/app/services/__init__.py`
    - _Requirements: 2.1, 2.2, 2.3, 3.4, 4.3, 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 14.2_

  - [ ]* 4.2 Write property test for group metric computation correctness
    - **Property 5: Group Metric Computation Correctness**
    - Use Hypothesis with `st.lists()` of lead-like dicts to verify computed metrics match expected values
    - Verify property_count, pin_count, owner_count, missing_pin_count, missing_owner_count, has_unit_number, has_condo_language
    - **Validates: Requirements 2.3, 3.4, 4.3**

  - [ ]* 4.3 Write property test for data safety invariant
    - **Property 7: Data Safety Invariant**
    - Generate lead fixtures, snapshot all fields before analysis, run analysis, verify: (a) no leads deleted, (b) only condo_risk_status, building_sale_possible, condo_analysis_id modified, (c) all other fields unchanged
    - **Validates: Requirements 13.1, 13.2, 13.3, 14.2**

  - [ ]* 4.4 Write property test for manual override preservation under re-analysis
    - **Property 9: Manual Override Preservation Under Re-Analysis**
    - Pre-set override fields on AddressGroupAnalysis records, run analysis, verify manual_override_status, manual_override_reason, and manually_reviewed are unchanged while analysis_details is updated
    - **Validates: Requirements 6.5, 9.3, 9.4**

- [x] 5. Marshmallow schemas and API controller
  - [x] 5.1 Add Marshmallow validation schemas
    - Add `CondoFilterResultsQuerySchema` and `CondoFilterOverrideSchema` to `backend/app/schemas.py`
    - CondoFilterResultsQuerySchema: condo_risk_status (OneOf valid values), building_sale_possible (OneOf valid values), manually_reviewed (Bool), page (Int, min=1), per_page (Int, min=1, max=100)
    - CondoFilterOverrideSchema: condo_risk_status (required, OneOf), building_sale_possible (required, OneOf), reason (required, Length min=1 max=1000)
    - _Requirements: 8.4, 9.1_

  - [x] 5.2 Implement condo_filter_controller blueprint
    - Create `backend/app/controllers/condo_filter_controller.py` with `condo_filter_bp` Blueprint
    - POST `/analyze` — triggers full analysis pipeline, returns summary JSON with counts by status and building_sale_possible, total groups, total properties
    - GET `/results` — paginated filtered results using CondoFilterResultsQuerySchema
    - GET `/results/<id>` — detail with linked leads (404 if not found)
    - PUT `/results/<id>/override` — apply manual override using CondoFilterOverrideSchema (404 if not found)
    - GET `/export/csv` — filtered CSV download with Content-Disposition header
    - Use `@handle_errors` decorator pattern for consistent error responses
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 12.2_

  - [x] 5.3 Register the condo_filter_bp blueprint
    - Register `condo_filter_bp` in `backend/app/__init__.py` with url_prefix `/api/condo-filter`
    - Import and add to `backend/app/controllers/__init__.py`
    - _Requirements: 8.1_

- [x] 6. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Backend unit and integration tests
  - [x]* 7.1 Write unit tests for condo filter service
    - Create `backend/tests/test_condo_filter_service.py`
    - Test API endpoint request/response validation (POST analyze, GET results, GET detail, PUT override, GET CSV)
    - Test database upsert behavior (first run creates, second run updates)
    - Test manual override end-to-end flow
    - Test pagination and filter combinations
    - Test error responses (404, 400, 500)
    - Test analyzed_at timestamp correctness
    - Test batch processing for large datasets
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4_

  - [x]* 7.2 Write integration tests for condo filter pipeline
    - Create `backend/tests/test_condo_filter_integration.py`
    - Test full pipeline: seed leads → POST analyze → verify DB state → GET results → GET detail → PUT override → verify cascade
    - Test unique constraint enforcement on normalized_address
    - Test foreign key integrity (condo_analysis_id references valid record)
    - Test re-analysis preserves overrides while updating automated fields
    - Test filter application to CSV export
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 12.2_

  - [x]* 7.3 Write property test for CSV export completeness
    - **Property 8: CSV Export Completeness**
    - Generate AddressGroupAnalysis records with linked leads, export CSV, verify all required columns present and multi-valued fields contain all values from linked leads
    - **Validates: Requirements 12.1, 12.3**

- [x] 8. Frontend types and API layer
  - [x] 8.1 Add condo filter TypeScript types
    - Add to `frontend/src/types/index.ts`: CondoRiskStatus, BuildingSalePossible type aliases, AddressGroupAnalysis, AddressGroupDetail, AddressGroupLead, CondoFilterResultsResponse, CondoAnalysisSummary, CondoFilterParams, CondoOverrideRequest interfaces
    - _Requirements: 10.1, 11.1_

  - [x] 8.2 Create condoFilterApi service
    - Create `frontend/src/services/condoFilterApi.ts` following the existing api.ts pattern
    - Implement: `runAnalysis()`, `getResults(params)`, `getDetail(id)`, `applyOverride(id, data)`, `exportCsv(params)` (returns Blob for download)
    - Use the shared axios instance from api.ts
    - _Requirements: 8.1, 8.4, 8.5, 9.1, 12.1_

- [x] 9. Frontend components
  - [x] 9.1 Create CondoResultsTable component
    - Create `frontend/src/components/CondoResultsTable.tsx`
    - Display MUI Table with columns: normalized_address, condo_risk_status, building_sale_possible, confidence, property_count, pin_count, owner_count, has_unit_number, has_condo_language, missing_pin_count, missing_owner_count, reason, analyzed_at, manually_reviewed
    - Include filter controls (Select for condo_risk_status, building_sale_possible, manually_reviewed)
    - Support pagination with MUI TablePagination
    - Row click handler to open detail view
    - Use React Query for data fetching
    - _Requirements: 10.1, 10.2, 10.4, 10.5_

  - [x] 9.2 Create CondoDetailView component
    - Create `frontend/src/components/CondoDetailView.tsx`
    - MUI Drawer showing full detail for selected address group
    - Display analysis metrics, classification details (triggered_rules, reason, confidence)
    - Table of linked Lead records (address, PIN, owners, property_type, assessor_class)
    - Manual override form: Select for condo_risk_status, Select for building_sale_possible, TextField for reason, Submit button
    - Call override API on submit and refresh detail view
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 9.3 Create CondoReviewPage component
    - Create `frontend/src/components/CondoReviewPage.tsx`
    - Top-level page managing state for filters, pagination, detail view visibility
    - Include "Run Analysis" button with loading state that triggers POST /analyze and refreshes results
    - Include CSV export button that triggers browser file download
    - Compose CondoResultsTable and CondoDetailView
    - _Requirements: 10.3, 12.1, 12.4_

  - [x] 9.4 Add routing and navigation
    - Add `/condo-filter` route to `frontend/src/App.tsx` rendering CondoReviewPage
    - Add "Condo Filter" item to the NAV_ITEMS sidebar navigation with an appropriate MUI icon (e.g., FilterAltIcon or ApartmentIcon)
    - Import CondoReviewPage component
    - _Requirements: 10.1_

- [x] 10. Checkpoint - Ensure frontend builds and all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Frontend tests
  - [x]* 11.1 Write tests for CondoReviewPage
    - Create `frontend/src/components/CondoReviewPage.test.tsx`
    - Test page renders with "Run Analysis" button
    - Test "Run Analysis" triggers API call and displays results
    - Test CSV export button triggers download
    - _Requirements: 10.3, 12.4_

  - [x]* 11.2 Write tests for CondoResultsTable
    - Create `frontend/src/components/CondoResultsTable.test.tsx`
    - Test filter controls render and filter changes trigger re-fetch
    - Test pagination controls work
    - Test row click opens detail view
    - _Requirements: 10.1, 10.2, 10.4, 10.5_

  - [x]* 11.3 Write tests for CondoDetailView
    - Create `frontend/src/components/CondoDetailView.test.tsx`
    - Test detail renders linked leads table
    - Test override form submits correctly
    - Test detail refreshes after override
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases using pytest
- Frontend tests use Vitest + React Testing Library following existing co-located test patterns
- The backend uses Python with Flask/SQLAlchemy; the frontend uses TypeScript with React/MUI
- Pure helper functions (tasks 2.x) are implemented before the service layer to enable isolated testing
