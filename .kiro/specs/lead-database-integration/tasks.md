# Implementation Plan: Lead Database Integration

## Overview

This plan implements the lead database integration feature for the Real Estate Analysis Platform. It adds Google Sheets import, lead storage, scoring, enrichment, and marketing list management. The implementation builds incrementally: database models first, then services, then API endpoints, then frontend views — each step wiring into the previous.

## Tasks

- [x] 1. Create database migration and SQLAlchemy models for lead management
  - [x] 1.1 Create database migration file `backend/migrations/002_lead_management.sql`
    - Define all new tables: `leads`, `lead_audit_trail`, `import_jobs`, `field_mappings`, `oauth_tokens`, `scoring_weights`, `data_sources`, `enrichment_records`, `marketing_lists`, `marketing_list_members`
    - Include all indexes, constraints, and foreign keys as specified in the design
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.2 Create SQLAlchemy model for Lead (`backend/app/models/lead.py`)
    - Define `Lead` model with all field groups (property details, owner info, contact info, mailing info, scoring, metadata)
    - Add unique constraint on `property_address`
    - Add relationships to `AnalysisSession`, `EnrichmentRecord`, `MarketingListMember`, `LeadAuditTrail`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.3 Create SQLAlchemy models for import-related tables (`backend/app/models/import_job.py`)
    - Define `ImportJob` model with status tracking, row counts, error_log (JSONB)
    - Define `FieldMapping` model with JSONB mapping column, unique constraint on (user_id, spreadsheet_id, sheet_name)
    - Define `OAuthToken` model with encrypted_refresh_token (LargeBinary)
    - _Requirements: 3.1, 3.5, 2.4, 1.4_

  - [x] 1.4 Create SQLAlchemy models for scoring, enrichment, and marketing (`backend/app/models/lead_scoring.py`, `backend/app/models/enrichment.py`, `backend/app/models/marketing.py`)
    - Define `ScoringWeights` model with weight fields and user_id unique constraint
    - Define `DataSource` model and `EnrichmentRecord` model with status tracking
    - Define `MarketingList` model and `MarketingListMember` model with outreach_status
    - Define `LeadAuditTrail` model
    - _Requirements: 5.2, 5.3, 6.1, 6.3, 7.1, 7.6, 4.4_

  - [x] 1.5 Update `backend/app/models/__init__.py` to export all new models
    - Import and export all new model classes
    - Add backref from `AnalysisSession` to `Lead`
    - _Requirements: 9.2_

  - [ ]* 1.6 Write unit tests for model structure and constraints (`backend/tests/test_lead_models.py`)
    - Test Lead unique constraint on property_address
    - Test model relationships and backrefs
    - Test default values and nullable fields
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 2. Implement Google Sheets Importer service
  - [x] 2.1 Create `backend/app/services/google_sheets_importer.py`
    - Implement `GoogleSheetsImporter` class with `authenticate`, `list_sheets`, `read_headers` methods
    - Implement `auto_map_fields` with synonym matching for common column names
    - Implement `validate_row` checking required fields, data types, and length constraints
    - Implement `upsert_lead` with ON CONFLICT logic using property_address as dedup key
    - Implement `process_import` as Celery task entry point with row-by-row processing
    - Implement audit trail recording on lead field updates
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.4, 8.4_

  - [ ]* 2.2 Write property test for auto-mapping correctness
    - **Property 1: Auto-mapping correctness**
    - **Validates: Requirements 2.2, 2.5**

  - [ ]* 2.3 Write property test for field mapping validation
    - **Property 2: Field mapping validation rejects incomplete mappings**
    - **Validates: Requirements 2.3**

  - [ ]* 2.4 Write property test for row validation correctness
    - **Property 4: Row validation correctness**
    - **Validates: Requirements 3.2**

  - [ ]* 2.5 Write property test for upsert deduplication
    - **Property 5: Upsert deduplication preserves unique addresses**
    - **Validates: Requirements 3.3, 8.4**

  - [ ]* 2.6 Write property test for import job count invariant
    - **Property 6: Import job count invariant**
    - **Validates: Requirements 3.5**

  - [ ]* 2.7 Write property test for audit trail on update
    - **Property 7: Audit trail records all field changes on update**
    - **Validates: Requirements 4.4**

- [x] 3. Implement Lead Scoring Engine service
  - [x] 3.1 Create `backend/app/services/lead_scoring_engine.py`
    - Implement `LeadScoringEngine` class with `compute_score` method
    - Implement sub-score methods: `score_property_characteristics`, `score_data_completeness`, `score_owner_situation`, `score_location_desirability`
    - Implement `get_weights` and `update_weights` with validation (weights must sum to 1.0)
    - Implement `bulk_rescore` as Celery task processing leads in batches of 500
    - Integrate scoring into lead creation/update flow
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.2 Write property test for lead score bounded weighted sum
    - **Property 10: Lead score is a bounded weighted sum**
    - **Validates: Requirements 5.1, 5.2**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Data Source Connector service
  - [x] 5.1 Create `backend/app/services/data_source_connector.py`
    - Implement `DataSourcePlugin` base class with `name` attribute and `lookup` method
    - Implement `DataSourceConnector` class with plugin registry pattern
    - Implement `register_source`, `enrich_lead`, `bulk_enrich` (Celery task), `list_sources`
    - Create `EnrichmentRecord` on each enrichment attempt with appropriate status
    - Update lead fields on successful enrichment
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [ ]* 5.2 Write property test for enrichment updates lead fields
    - **Property 12: Enrichment updates lead fields correctly**
    - **Validates: Requirements 6.3**

- [x] 6. Implement Marketing Manager service
  - [x] 6.1 Create `backend/app/services/marketing_manager.py`
    - Implement `MarketingManager` class with CRUD for marketing lists
    - Implement `add_leads`, `remove_leads`, `get_list_members` with pagination
    - Implement `update_outreach_status` with valid status transitions
    - Implement `create_list_from_filters` excluding leads with "opted_out" status
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 6.2 Write property test for marketing list membership
    - **Property 13: Marketing list membership**
    - **Validates: Requirements 7.2, 7.3**

  - [ ]* 6.3 Write property test for filter-based list creation with opted-out exclusion
    - **Property 14: Filter-based list creation with opted-out exclusion**
    - **Validates: Requirements 7.4, 7.7**

  - [ ]* 6.4 Write property test for outreach status persistence
    - **Property 15: Outreach status persistence**
    - **Validates: Requirements 7.6**

- [x] 7. Implement Lead API endpoints
  - [x] 7.1 Create `backend/app/controllers/lead_controller.py`
    - Implement `GET /api/leads/` with pagination, filtering (property type, city, state, zip, owner name, score range, marketing list), and sorting
    - Implement `GET /api/leads/{lead_id}` with full detail including score, enrichment records, analysis links
    - Implement `POST /api/leads/{lead_id}/analyze` to create AnalysisSession pre-populated from lead data
    - Implement `GET /api/leads/scoring/weights` and `PUT /api/leads/scoring/weights`
    - _Requirements: 4.5, 4.6, 5.3, 5.5, 5.6, 9.1, 9.2, 9.3_

  - [ ]* 7.2 Write property test for pagination consistency
    - **Property 8: Pagination consistency**
    - **Validates: Requirements 4.5**

  - [ ]* 7.3 Write property test for filter predicate correctness
    - **Property 9: Filter predicate correctness**
    - **Validates: Requirements 4.6**

  - [ ]* 7.4 Write property test for score sorting correctness
    - **Property 11: Score sorting correctness**
    - **Validates: Requirements 5.6**

  - [ ]* 7.5 Write property test for lead-to-analysis pre-population
    - **Property 16: Lead-to-analysis pre-population**
    - **Validates: Requirements 9.1**

- [x] 8. Implement Import API endpoints
  - [x] 8.1 Create `backend/app/controllers/import_controller.py`
    - Implement `POST /api/leads/import/auth` for Google OAuth2 authentication
    - Implement `GET /api/leads/import/sheets` to list available sheets
    - Implement `GET /api/leads/import/headers` to read headers from selected sheet
    - Implement `POST /api/leads/import/mapping` to save/update field mapping
    - Implement `POST /api/leads/import/start` to create ImportJob and enqueue Celery task
    - Implement `GET /api/leads/import/jobs` and `GET /api/leads/import/jobs/{job_id}` for status/progress
    - Implement `POST /api/leads/import/jobs/{job_id}/rerun` to re-run a previous import
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3, 2.4, 3.1, 3.6, 3.7, 8.1, 8.2, 8.3, 8.4_

  - [ ]* 8.2 Write property test for field mapping persistence round-trip
    - **Property 3: Field mapping persistence round-trip**
    - **Validates: Requirements 2.4**

- [x] 9. Implement Enrichment and Marketing API endpoints
  - [x] 9.1 Create `backend/app/controllers/enrichment_controller.py`
    - Implement `GET /api/leads/enrichment/sources` to list registered data sources
    - Implement `POST /api/leads/{lead_id}/enrich` for single lead enrichment
    - Implement `POST /api/leads/enrichment/bulk` for bulk enrichment via Celery
    - _Requirements: 6.1, 6.2, 6.5, 6.6_

  - [x] 9.2 Create `backend/app/controllers/marketing_controller.py`
    - Implement `GET /api/leads/marketing/lists` and `POST /api/leads/marketing/lists`
    - Implement `PUT /api/leads/marketing/lists/{list_id}` and `DELETE /api/leads/marketing/lists/{list_id}`
    - Implement `GET /api/leads/marketing/lists/{list_id}/members` with pagination
    - Implement `POST /api/leads/marketing/lists/{list_id}/members` and `DELETE /api/leads/marketing/lists/{list_id}/members`
    - Implement `PUT /api/leads/marketing/lists/{list_id}/members/{lead_id}/status`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

- [x] 10. Register new controllers and update services __init__
  - [x] 10.1 Update `backend/app/controllers/__init__.py` to import new controllers
    - Register lead_controller, import_controller, enrichment_controller, marketing_controller blueprints
    - _Requirements: 4.5, 8.1_

  - [x] 10.2 Update `backend/app/services/__init__.py` to export new services
    - Export GoogleSheetsImporter, LeadScoringEngine, DataSourceConnector, MarketingManager
    - _Requirements: 1.1, 5.1, 6.1, 7.1_

  - [x] 10.3 Register Celery tasks in `backend/celery_worker.py`
    - Register import, scoring, and enrichment async tasks
    - _Requirements: 3.6, 5.4, 6.6_

- [x] 11. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Create Marshmallow schemas for new API endpoints
  - [x] 12.1 Add lead management schemas to `backend/app/schemas.py`
    - Create schemas for: lead list query params, lead detail response, import auth request, field mapping request, import start request, scoring weights update, marketing list CRUD, outreach status update, enrichment request
    - Add validation for filter parameters, pagination bounds, weight sum constraint
    - _Requirements: 2.3, 4.5, 4.6, 5.3_

- [x] 13. Implement frontend TypeScript types and API service
  - [x] 13.1 Add lead management types to `frontend/src/types/index.ts`
    - Define interfaces: `Lead`, `ImportJob`, `FieldMapping`, `ScoringWeights`, `MarketingList`, `MarketingListMember`, `EnrichmentRecord`, `DataSource`
    - Define enums: `ImportJobStatus`, `OutreachStatus`
    - Define pagination and filter types
    - _Requirements: 4.1, 7.6_

  - [x] 13.2 Create lead API service (`frontend/src/services/leadApi.ts`)
    - Implement API methods for all lead endpoints: list, detail, import auth, import start, import status, scoring weights, marketing lists, enrichment
    - Follow existing patterns from `frontend/src/services/api.ts`
    - _Requirements: 4.5, 3.7, 8.1_

- [x] 14. Implement frontend lead list and detail views
  - [x] 14.1 Create `LeadListPage` component (`frontend/src/components/LeadListPage.tsx`)
    - Paginated table with columns: address, owner, score, property type, status
    - Filter panel: property type, location, score range, marketing list
    - Sort by score, created date, address
    - _Requirements: 4.5, 4.6, 5.5, 5.6_

  - [x] 14.2 Create `LeadDetailPage` component (`frontend/src/components/LeadDetailPage.tsx`)
    - Tabbed view: Info, Score, Enrichment, Marketing, Analysis
    - Display all lead fields, score breakdown, enrichment status with source attribution
    - "Start Analysis" button to create AnalysisSession from lead
    - Display linked analysis results when available
    - _Requirements: 5.5, 6.5, 9.1, 9.3_

- [x] 15. Implement frontend import wizard
  - [x] 15.1 Create `ImportWizard` component (`frontend/src/components/ImportWizard.tsx`)
    - Multi-step flow: OAuth Auth → Sheet Selection → Field Mapping → Import Progress
    - Display available sheets after authentication
    - Show import progress with rows processed/remaining
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 3.7_

  - [x] 15.2 Create `FieldMappingEditor` component (`frontend/src/components/FieldMappingEditor.tsx`)
    - Display sheet columns with dropdown mapping to database fields
    - Show auto-mapped fields with ability to override
    - Validate required fields mapped before allowing import
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [x] 15.3 Create `ImportHistoryTable` component (`frontend/src/components/ImportHistoryTable.tsx`)
    - Table of past imports with status, timestamps, row counts
    - Detail view showing error log for skipped rows
    - Re-run button for completed imports
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 16. Implement frontend scoring and marketing views
  - [x] 16.1 Create `ScoringWeightsEditor` component (`frontend/src/components/ScoringWeightsEditor.tsx`)
    - Slider controls for each scoring criterion weight
    - Validation that weights sum to 1.0
    - Save button triggering bulk rescore
    - _Requirements: 5.3, 5.4_

  - [x] 16.2 Create `MarketingListManager` component (`frontend/src/components/MarketingListManager.tsx`)
    - List of marketing lists with member counts
    - Create/rename/delete list actions
    - Member table with outreach status, score, contact info
    - Status update dropdown per member
    - Create list from filter criteria
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 17. Wire frontend views into App routing
  - [x] 17.1 Update `frontend/src/App.tsx` with navigation and routing for lead management views
    - Add routes for lead list, lead detail, import wizard, marketing lists
    - Add navigation menu items for Leads, Import, Marketing
    - _Requirements: 4.5, 8.1_

- [x] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The backend uses Python (Flask/SQLAlchemy/Celery) and the frontend uses React/TypeScript, matching the existing platform stack
- Google API client libraries are already in `requirements.txt`
- Hypothesis (property-based testing) is already in `requirements.txt`
