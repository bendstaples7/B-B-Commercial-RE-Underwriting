# Implementation Plan: Commercial OM PDF Intake

## Overview

Implements an asynchronous four-stage pipeline (PDF parsing → AI field extraction → market rent research → Deal creation) driven by Celery tasks advancing an `OMIntakeJob` state machine. The backend is Python/Flask/SQLAlchemy/Celery; the frontend is React/TypeScript/MUI. The pure `ScenarioEngine` function is the primary target for Hypothesis property-based testing.

## Tasks

- [x] 1. Add new exception classes and data models
  - [x] 1.1 Add `InvalidFileError`, `ExternalServiceError`, `ResourceNotFoundError`, and `ConflictError` to `backend/app/exceptions.py`, extending `RealEstateAnalysisException` with the status codes and payloads defined in the design
    - _Requirements: 9.1, 12.6_
  - [x] 1.2 Create `backend/app/models/om_intake_job.py` with the `OMIntakeJob` SQLAlchemy model and `OMFieldOverride` model exactly as specified in the design (all columns, CHECK constraint, composite index on `user_id`/`created_at`, cascade delete on overrides)
    - _Requirements: 1.1, 1.5, 1.6, 8.3, 11.5_
  - [x] 1.3 Re-export `OMIntakeJob` and `OMFieldOverride` from `backend/app/models/__init__.py`
    - _Requirements: 1.1_
  - [x] 1.4 Create an Alembic migration in `backend/alembic_migrations/` that adds the `om_intake_jobs` and `om_field_overrides` tables with all columns, constraints, and indexes
    - _Requirements: 1.1, 8.3_

- [x] 2. Implement frozen dataclasses and ScenarioEngine
  - [x] 2.1 Create `backend/app/services/om_intake/om_intake_dataclasses.py` with all frozen dataclasses: `UnitMixRow`, `OtherIncomeItem`, `ScenarioInputs`, `ScenarioMetrics`, `UnitMixComparisonRow`, `ScenarioComparison`, `PDFExtractionResult`, and `ExtractedOMData`; use `Decimal` for all monetary and rate fields
    - _Requirements: 2.2, 3.2, 3.3, 4.2, 5.1, 5.2, 5.7_
  - [x] 2.2 Create `backend/app/services/om_intake/scenario_engine.py` with the pure `compute_scenarios(inputs: ScenarioInputs) -> ScenarioComparison` function implementing all formulas from the design: realistic GPI, EGI, NOI, cap rate, GRM, significant variance flag, and realistic cap rate below proforma flag; use `Decimal` arithmetic throughout; guard all division operations against zero/null denominators
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_
  - [ ]* 2.3 Write property tests for ScenarioEngine — Properties 3–10 — in `backend/tests/test_om_scenario_engine.py` using Hypothesis `@given` with `scenario_inputs_strategy()`; each test tagged with its property number and requirement reference
    - **Property 3: Realistic GPI formula** — **Validates: Requirements 4.4**
    - **Property 4: Realistic EGI formula** — **Validates: Requirements 4.5**
    - **Property 5: Realistic NOI formula** — **Validates: Requirements 4.6**
    - **Property 6: Cap rate zero-guard** — **Validates: Requirements 4.7, 5.8**
    - **Property 7: GRM zero-guard** — **Validates: Requirements 4.8, 5.9**
    - **Property 8: Significant variance flag correctness** — **Validates: Requirements 5.4, 5.5**
    - **Property 9: Realistic cap rate below proforma flag correctness** — **Validates: Requirements 5.6**
    - **Property 10: Unit mix comparison completeness** — **Validates: Requirements 5.7**

- [x] 3. Implement PDFParserService
  - [x] 3.1 Create `backend/app/services/om_intake/pdf_parser_service.py` with `PDFParserService.extract(pdf_bytes) -> PDFExtractionResult`; try PyMuPDF (`fitz`) first for text extraction; fall back to pdfplumber for table extraction if PyMuPDF tables are empty; raise `InvalidFileError` if PDF cannot be opened; set `table_extraction_warning` if table extraction fails but text succeeds; fail with `InvalidFileError` if extracted text is fewer than 100 characters
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7_
  - [ ]* 3.2 Write unit tests for `PDFParserService` in `backend/tests/test_pdf_parser_service.py` covering: valid PDF extracts text and tables, corrupt bytes raises `InvalidFileError`, text < 100 chars raises `InvalidFileError`, table extraction failure stores warning and returns text, page-count timing boundary
    - _Requirements: 2.1, 2.3, 2.4, 2.7_

- [x] 4. Implement GeminiOMExtractorService
  - [x] 4.1 Create `backend/app/services/om_intake/gemini_om_extractor_service.py` with `GeminiOMExtractorService`; constructor reads `GOOGLE_AI_API_KEY` and raises `GeminiConfigurationError` (subclass of `ExternalServiceError`) if missing; `extract(raw_text, tables) -> ExtractedOMData` builds the structured Gemini prompt, calls the API with a 60-second timeout, parses and validates the JSON response, assigns confidence scores (defaulting absent fields to `{"value": null, "confidence": 0.0}`), and validates that `unit_mix` and `asking_price` are present; raise `GeminiAPIError` on network/HTTP errors, `GeminiParseError` on invalid JSON, `GeminiResponseError` on missing required fields
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9, 3.10_
  - [ ]* 4.2 Write property tests for confidence score invariants in `backend/tests/test_om_scenario_engine.py`
    - **Property 1: Confidence scores are always in [0.0, 1.0]** — **Validates: Requirements 3.3**
    - **Property 2: Absent fields have null value and zero confidence** — **Validates: Requirements 3.4**
  - [ ]* 4.3 Write unit tests for `GeminiOMExtractorService` in `backend/tests/test_gemini_om_extractor_service.py` covering: missing API key raises config error, valid response parses to `ExtractedOMData`, invalid JSON transitions to FAILED, missing `unit_mix` transitions to FAILED, missing `asking_price` transitions to FAILED, empty raw_text raises without calling Gemini
    - _Requirements: 3.5, 3.6, 3.9, 3.10_

- [x] 5. Implement consistency checks and OMIntakeService core
  - [x] 5.1 Create `backend/app/services/om_intake/__init__.py` and `backend/app/services/om_intake/om_intake_service.py` with `OMIntakeService`; implement `create_job` (MIME/size validation, `OMIntakeJob` creation with `expires_at = created_at + 90 days`, enqueue `parse_om_pdf_task`), `get_job` (ownership check → `ResourceNotFoundError` on mismatch), `list_jobs` (paginated, `page_size` clamped to [1, 100], ordered by `created_at DESC`), `get_scenario_comparison`, `retry_failed_job`, and all internal state-transition helpers (`transition_to_parsing`, `store_parsed_text`, `transition_to_extracting`, `store_extracted_data`, `store_market_rent`, `store_scenario_comparison`, `transition_to_review`, `transition_to_failed`)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 8.1, 8.3, 9.3_
  - [x] 5.2 Add consistency-check logic inside `store_extracted_data`: validate unit_count sum, NOI consistency (2% tolerance), cap rate consistency (0.5 pp tolerance), GRM consistency (2% tolerance); skip checks with `insufficient_data_warning` when any operand is null/zero; set `asking_price_missing_error` and `unit_count_missing_error` flags
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.7, 10.8_
  - [ ]* 5.3 Write property tests for consistency checks in `backend/tests/test_om_scenario_engine.py`
    - **Property 18: NOI consistency check correctness** — **Validates: Requirements 10.2**
    - **Property 19: Cap rate consistency check correctness** — **Validates: Requirements 10.3**
    - **Property 20: GRM consistency check correctness** — **Validates: Requirements 10.4**
  - [ ]* 5.4 Write unit tests for `OMIntakeService` in `backend/tests/test_om_intake_service.py` covering: valid upload creates PENDING job, non-PDF MIME raises `InvalidFileError`, file > 50 MB raises `InvalidFileError`, get_job for wrong user raises `ResourceNotFoundError`, list_jobs pagination and ordering, retry_failed_job creates new job and leaves original FAILED, expired job returns 410, re-confirm CONFIRMED job raises `ConflictError`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 8.1, 8.3, 8.4, 9.3_

- [x] 6. Checkpoint — Ensure all backend service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Celery tasks
  - [x] 7.1 Create `backend/app/tasks/om_intake_tasks.py` with three Celery tasks registered in `celery_worker.py`: `parse_om_pdf_task` (no auto-retry, calls `PDFParserService.extract`, stores result via `OMIntakeService`, enqueues `extract_om_fields_task`), `extract_om_fields_task` (`autoretry_for=(GeminiAPIError,)`, `retry_backoff=2`, `max_retries=3`, calls `GeminiOMExtractorService.extract`, stores `ExtractedOMData`, runs consistency checks, enqueues `research_market_rents_task`), and `research_market_rents_task` (`autoretry_for=(GeminiAPIError,)`, `retry_backoff=2`, `max_retries=3`, calls `GeminiComparableSearchService` once per distinct unit type, stores market rent results, calls `compute_scenarios`, stores `ScenarioComparison`, transitions to REVIEW); each task calls `transition_to_failed` in its `on_failure` handler
    - _Requirements: 2.5, 3.7, 4.1, 4.2, 4.9, 4.10, 9.1, 9.2, 9.4, 9.5_
  - [ ]* 7.2 Write property test for Gemini call count in `backend/tests/test_om_scenario_engine.py`
    - **Property 11: Gemini call count equals distinct unit type count** — **Validates: Requirements 4.1**
  - [ ]* 7.3 Write unit tests for Celery tasks in `backend/tests/test_om_intake_service.py` covering: parse task transitions job to PARSING then EXTRACTING, extract task retries on `GeminiAPIError` up to 3 times with backoff, research task stores per-unit-type warnings on failure and transitions to REVIEW, unhandled exception triggers `transition_to_failed`
    - _Requirements: 2.5, 3.7, 4.9, 9.1, 9.5_

- [x] 8. Implement OMIntakeService.confirm_job and Deal creation
  - [x] 8.1 Implement `OMIntakeService.confirm_job(user_id, job_id, confirmed_data) -> Deal` inside a single SQLAlchemy transaction: validate job is in REVIEW, apply user overrides (storing `OMFieldOverride` records with `original_value`, `overridden_value`, `overridden_at`), map `ExtractedOMData` fields to `DealService.create_deal` payload (field mapping per Req 7.2), create one `Unit` record per `Unit_Mix_Row` (reject rows with `unit_count <= 0`), create `Rent_Roll_Entry` records using `current_avg_rent`, create `Market_Rent_Assumption` records using `proforma_rent` and `market_rent_estimate`, map expense labels to Deal OpEx fields (case-insensitive substring matching per design table), store unrecognized labels as `unmatched_expense_items`, set `other_income_monthly` from sum of `other_income_items / 12`, store financing fields as Scenario_B defaults, transition job to CONFIRMED, store `deal_id`; roll back entire transaction on any failure and leave job in REVIEW
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.11, 7.12, 12.4_
  - [x] 8.2 Add post-confirmation integrity checks inside `confirm_job`: verify `deal.purchase_price == confirmed asking_price`, verify unit record count equals `unit_count`, verify rent roll sum equals unit mix sum within $0.01
    - _Requirements: 11.1, 11.2, 11.3_
  - [ ]* 8.3 Write property tests for Deal creation round-trip in `backend/tests/test_om_scenario_engine.py`
    - **Property 12: Deal field mapping round-trip** — **Validates: Requirements 7.2, 11.1**
    - **Property 13: Unit record count equals unit_count** — **Validates: Requirements 7.3, 11.3**
    - **Property 14: Rent roll sum matches unit mix sum** — **Validates: Requirements 7.4, 11.2**
    - **Property 15: Other income monthly formula** — **Validates: Requirements 7.7**
    - **Property 16: User override is applied to Deal** — **Validates: Requirements 11.4**
    - **Property 17: Override audit trail completeness** — **Validates: Requirements 11.5**
  - [ ]* 8.4 Write unit tests for `confirm_job` in `backend/tests/test_om_intake_service.py` covering: successful confirmation creates Deal and transitions to CONFIRMED, DB failure mid-transaction rolls back and leaves job in REVIEW, `asking_price` null/zero returns 422, `unit_count` null/< 1 returns 422, unit_mix row with `unit_count <= 0` returns validation error, re-confirm CONFIRMED job returns 409 with `deal_id`, user override value applied to Deal, unrecognized expense label stored as `unmatched_expense_items`
    - _Requirements: 7.1, 7.3, 7.6, 7.11, 7.12, 8.4, 10.6, 10.7, 11.4_

- [x] 9. Implement Flask Blueprint and Marshmallow schemas
  - [x] 9.1 Append OM intake Marshmallow schemas to `backend/app/schemas.py`: `OMIntakeJobSchema`, `OMIntakeJobListSchema`, `OMIntakeJobStatusSchema`, `OMIntakeReviewSchema`, `OMIntakeConfirmRequestSchema`, `ScenarioComparisonSchema`, `ScenarioMetricsSchema`, `UnitMixComparisonRowSchema`, `ExtractedOMDataSchema`
    - _Requirements: 1.7, 5.1, 5.2, 5.7, 8.1, 8.2_
  - [x] 9.2 Create `backend/app/controllers/om_intake_controller.py` with `om_intake_bp = Blueprint('om_intake', __name__)` at prefix `/api/om-intake`; implement all six routes: `POST /jobs` (multipart upload, calls `OMIntakeService.create_job`, returns 201), `GET /jobs` (paginated list), `GET /jobs/<id>` (status + metadata), `GET /jobs/<id>/review` (full review data for REVIEW/CONFIRMED only), `POST /jobs/<id>/confirm` (calls `confirm_job`, returns `deal_id`), `POST /jobs/<id>/retry` (calls `retry_failed_job`); apply `@handle_errors` decorator to all routes; return HTTP 410 for expired jobs
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 1.8, 5.1, 7.9, 8.1, 8.2, 8.3, 8.4, 8.5, 9.3_
  - [x] 9.3 Register `om_intake_bp` in `backend/app/__init__.py` (or `backend/app/controllers/__init__.py`) with the `/api/om-intake` URL prefix
    - _Requirements: 1.1_
  - [ ]* 9.4 Write unit tests for the controller in `backend/tests/test_om_intake_controller.py` covering: POST /jobs with valid PDF returns 201 with `intake_job_id`, POST /jobs with non-PDF returns 422, POST /jobs with file > 50 MB returns 422, GET /jobs/<id> for another user's job returns 404, GET /jobs/<id>/review for PARSING job returns job status without review data, POST /jobs/<id>/confirm on CONFIRMED job returns 409, POST /jobs/<id>/retry on FAILED job returns 201 new job, GET /jobs pagination defaults and clamping, expired job returns 410
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 1.8, 8.1, 8.3, 8.4, 8.5, 9.3_

- [x] 10. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement frontend TypeScript types and API service
  - [x] 11.1 Append OM intake TypeScript interfaces and enums to `frontend/src/types/index.ts`: `IntakeStatus` enum, `OMIntakeJob`, `ExtractedOMData`, `UnitMixRow`, `ScenarioMetrics`, `ScenarioComparison`, `UnitMixComparisonRow`, `OMIntakeJobListItem`, `OMIntakeConfirmRequest`, `OMIntakeReviewData`
    - _Requirements: 1.7, 5.1, 5.2, 6.1, 6.6_
  - [x] 11.2 Append OM intake API methods to `frontend/src/services/api.ts`: `uploadOMPDF(file: File)`, `getOMJobStatus(jobId: number)`, `getOMJobReview(jobId: number)`, `confirmOMJob(jobId: number, confirmedData: OMIntakeConfirmRequest)`, `retryOMJob(jobId: number)`, `listOMJobs(page: number, pageSize: number)`
    - _Requirements: 1.1, 1.7, 5.1, 7.9, 8.1, 9.3_

- [x] 12. Implement omScenarioEngine.ts (TypeScript mirror)
  - [x] 12.1 Create `frontend/src/components/multifamily/omScenarioEngine.ts` mirroring all `ScenarioEngine` formulas in TypeScript: `computeRealisticGPI`, `computeRealisticEGI`, `computeRealisticNOI`, `computeCapRate`, `computeGRM`, `computeSignificantVarianceFlag`, `computeRealisticCapRateBelowProforma`; use `number | null` arithmetic with explicit null-guards matching the Python zero-guard rules
    - _Requirements: 6.3, 6.4, 6.5_
  - [ ]* 12.2 Write unit tests for `omScenarioEngine.ts` in `frontend/src/components/multifamily/omScenarioEngine.test.ts` covering each formula function with null inputs, zero denominators, and representative numeric cases
    - _Requirements: 6.3, 6.4, 6.5_

- [x] 13. Implement OMUploadForm and OMStatusPoller components
  - [x] 13.1 Create `frontend/src/components/multifamily/OMUploadForm.tsx` with drag-and-drop PDF upload using MUI; validate client-side that the selected file is `application/pdf` and ≤ 50 MB before submitting; call `uploadOMPDF` on submit; display upload progress; navigate to the new job's review page on success
    - _Requirements: 1.1, 1.2, 1.3, 6.1_
  - [x] 13.2 Create `frontend/src/components/multifamily/OMStatusPoller.tsx` that polls `getOMJobStatus` every 3 seconds while job is in `PENDING`, `PARSING`, `EXTRACTING`, or `RESEARCHING` status; displays "Reading PDF…" for PARSING, "Extracting deal data with AI…" for EXTRACTING, "Researching market rents…" for RESEARCHING; stops polling and calls `onReady` callback when status transitions to `REVIEW`; displays `error_message` and "Try Again" button when status is `FAILED`
    - _Requirements: 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_
  - [ ]* 13.3 Write component tests for `OMUploadForm` and `OMStatusPoller` in their respective `.test.tsx` files covering: upload form rejects non-PDF, upload form rejects file > 50 MB, status poller shows correct message per status, poller stops on REVIEW, poller shows error and retry button on FAILED
    - _Requirements: 1.2, 1.3, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_

- [x] 14. Implement OMScenarioTable, OMUnitMixComparison, and OMDataWarnings components
  - [x] 14.1 Create `frontend/src/components/multifamily/OMScenarioTable.tsx` rendering the three-scenario side-by-side metrics table (broker current, broker pro forma, realistic) with all `ScenarioMetrics` fields; show `significant_variance_flag` and `realistic_cap_rate_below_proforma` indicators; show `null` fields as "—"
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_
  - [x] 14.2 Create `frontend/src/components/multifamily/OMUnitMixComparison.tsx` rendering the per-unit-type comparison rows with `unit_type_label`, `unit_count`, `sqft`, `current_avg_rent`, `proforma_rent`, `market_rent_estimate` (with low/high range); make rent fields editable inline; call `omScenarioEngine` to recalculate affected metrics within 300 ms on edit; mark edited fields as `user_overridden`
    - _Requirements: 5.7, 6.3, 6.4, 6.5_
  - [x] 14.3 Create `frontend/src/components/multifamily/OMDataWarnings.tsx` rendering the "Data Warnings" section; display each consistency warning with label, field name, computed value, stated value, and delta; warnings do not block confirmation
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 15. Implement OMReviewPanel and OMIntakePage
  - [x] 15.1 Create `frontend/src/components/multifamily/OMReviewPanel.tsx` composing `OMScenarioTable`, `OMUnitMixComparison`, and `OMDataWarnings`; display all extracted property fields with their confidence scores; mark fields with confidence < 0.7 with a warning icon and amber MUI background; display `Intake_Status` at all times; show links to up to 5 existing Deals whose normalized address matches `property_address`; include "Confirm" button that submits confirmed data to `confirmOMJob` and navigates to the created Deal's detail page on success; keep job in REVIEW and show validation error if confirmation fails
    - _Requirements: 6.1, 6.2, 6.3, 6.6, 6.13, 7.10, 7.11, 12.3_
  - [x] 15.2 Create `frontend/src/pages/multifamily/OMIntakePage.tsx` composing `OMUploadForm` and `OMStatusPoller`; when job reaches REVIEW render `OMReviewPanel` without page reload; display current `Intake_Status` throughout
    - _Requirements: 6.1, 6.6, 6.11_
  - [ ]* 15.3 Write component tests for `OMReviewPanel` in `frontend/src/components/multifamily/OMReviewPanel.test.tsx` covering: renders three-scenario table, marks low-confidence fields with amber background, field edit triggers recalculation within 300 ms, Confirm button calls `confirmOMJob` and navigates to Deal page, validation error on confirm keeps job in REVIEW
    - _Requirements: 6.1, 6.2, 6.3, 6.13, 7.10, 7.11_

- [x] 16. Wire frontend routing and navigation
  - [x] 16.1 Add a route for `OMIntakePage` in `frontend/src/App.tsx` under the Multifamily section (e.g., `/multifamily/om-intake` and `/multifamily/om-intake/:jobId`)
    - _Requirements: 12.1, 12.2_
  - [x] 16.2 Add an "Upload OM" button to the Multifamily section of the sidebar in `frontend/src/App.tsx` that is visible without scrolling and labeled exactly "Upload OM"; add an "Upload OM" button to the Deal list page
    - _Requirements: 12.1, 12.2_

- [x] 17. Checkpoint — Ensure all frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 18. Write integration tests
  - [x] 18.1 Write an end-to-end integration test in `backend/tests/test_om_intake_service.py` that runs the full pipeline with a fixture PDF and mocked Gemini responses, verifying the job progresses through all statuses to REVIEW and the `ScenarioComparison` is populated
    - _Requirements: 2.5, 3.7, 4.10_
  - [x] 18.2 Write an atomic transaction rollback integration test: inject a DB failure mid-Deal-creation in `confirm_job`, verify the job remains in REVIEW status and no partial Deal record exists
    - _Requirements: 7.12_
  - [x] 18.3 Write a Celery retry integration test: mock `GeminiOMExtractorService.extract` to raise `GeminiAPIError` twice then succeed; verify the job reaches REVIEW status after the third attempt
    - _Requirements: 9.1_
  - [ ]* 18.4 Write a property test for history list ordering in `backend/tests/test_om_scenario_engine.py`
    - **Property 21: History list ordering** — **Validates: Requirements 8.1**

- [x] 19. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- **Integration tests 18.1–18.3 are required** — they verify the async pipeline, atomic transactions, and retry logic that cannot be caught by static analysis or unit tests alone. A feature with Celery tasks, rate-limited endpoints, or external API calls must have integration tests before being declared ready.
- Run `python backend/tests/smoke_test_om_intake.py` against a live local server as a final readiness check before declaring the feature complete.
- Each task references specific requirements for traceability
- The `ScenarioEngine` (Task 2) is the highest-priority property-test target — Properties 3–10 cover all its formulas
- Properties 12–17 require a test database; use SQLite in-memory (per `conftest.py`) with mocked `DealService`
- Properties 18–20 (consistency checks) are pure arithmetic and can be tested without a database
- The TypeScript `omScenarioEngine.ts` (Task 12) must mirror the Python `ScenarioEngine` exactly — any divergence will cause the 300 ms recalculation to disagree with the backend
- Celery tasks require Redis; use `unittest.mock` to mock `celery.task` in unit tests so they run without infrastructure
- The `expires_at` column is set to `created_at + 90 days` at job creation; the controller returns HTTP 410 when `expires_at < utcnow()`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.3", "3.2", "4.2", "4.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 8, "tasks": ["9.1"] },
    { "id": 9, "tasks": ["9.2"] },
    { "id": 10, "tasks": ["9.3", "9.4", "11.1", "11.2"] },
    { "id": 11, "tasks": ["12.1"] },
    { "id": 12, "tasks": ["12.2", "13.1", "13.2"] },
    { "id": 13, "tasks": ["13.3", "14.1", "14.2", "14.3"] },
    { "id": 14, "tasks": ["15.1", "15.2"] },
    { "id": 15, "tasks": ["15.3", "16.1", "16.2"] },
    { "id": 16, "tasks": ["18.1", "18.2", "18.3", "18.4"] }
  ]
}
```
