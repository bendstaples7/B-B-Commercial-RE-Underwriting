# Implementation Plan: DuPage Lead Database

## Overview

Extend the platform's lead data model and scoring engine with source_type tagging, tax_distress_data storage, manual_priority scoring, GIS-based enrichment, deduplication improvements, and lead list filtering. DuPage County is the first market fully loaded using these capabilities. Implementation follows the platform-first principle: every new column, service, and API filter applies to all leads, not only DuPage leads.

Tech stack: Python/Flask 3.0, PostgreSQL/SQLAlchemy/Alembic, Marshmallow, Celery+Redis, pytest+Hypothesis (backend); React 18 + TypeScript, MUI v5, React Query v5, Axios, Vitest (frontend).

---

## Tasks

- [x] 1. Database migrations — add new columns and indexes to `leads` and `import_jobs`
  - Write idempotent Alembic migration `xxxx_add_dupage_lead_columns.py` using `ADD COLUMN IF NOT EXISTS` for `source_type VARCHAR(50)`, `tax_distress_data JSONB`, and `manual_priority INTEGER` on the `leads` table
  - Write `CREATE INDEX IF NOT EXISTS ix_leads_source_type ON leads(source_type)` and `CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id_source_type ON leads(owner_user_id, source_type)` in the same migration
  - Write idempotent `downgrade()` that drops indexes and columns using `IF EXISTS` variants
  - Write a second migration `xxxx_add_import_job_source_type.py` that adds `source_type VARCHAR(50)` to `import_jobs` using `ADD COLUMN IF NOT EXISTS` with a matching `downgrade()`
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 1.1 Write smoke tests for migration idempotency
    - Run both migrations twice against a SQLite/PostgreSQL test DB; assert no error and all columns/indexes exist after both runs
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 2. SQLAlchemy model updates — `Property` and `ImportJob`
  - [x] 2.1 Add three new columns to `Property` model in `backend/app/models/lead.py`
    - Add `source_type = db.Column(db.String(50), nullable=True, index=True)` after existing `data_source` column
    - Add `tax_distress_data = db.Column(db.JSON, nullable=True)`
    - Add `manual_priority = db.Column(db.Integer, nullable=True)`
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 2.2 Add `source_type` column to `ImportJob` model in `backend/app/models/import_job.py`
    - Add `source_type = db.Column(db.String(50), nullable=True)`
    - _Requirements: 9.1_

  - [x] 2.3 Write unit tests for model column presence
    - Assert `Property` instance accepts and persists `source_type`, `tax_distress_data`, `manual_priority`
    - Assert `ImportJob` instance accepts and persists `source_type`
    - _Requirements: 10.1, 10.2, 10.3, 9.1_


- [x] 3. Marshmallow schema additions in `backend/app/schemas.py`
  - [x] 3.1 Add `IngestionRequestSchema`, `CSVUploadQuerySchema`, and `ImportJobResponseSchema`
    - `IngestionRequestSchema`: `owner_user_id` (required, max 36) and `records` (required list of dicts, min 1)
    - `CSVUploadQuerySchema`: `owner_user_id` (required, max 36) query param
    - `ImportJobResponseSchema`: dump-only fields: `id`, `status`, `source_type`, `rows_processed`, `rows_imported`, `rows_skipped`, `error_log`, `created_at`, `completed_at`
    - Define `VALID_SOURCE_TYPES` list in schemas.py: `["foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"]`
    - _Requirements: 9.6, 11.4_

  - [x] 3.2 Extend `LeadListQuerySchema` and `LeadDetailResponseSchema`
    - Add optional `source_type` field to `LeadListQuerySchema` with `validate.OneOf(VALID_SOURCE_TYPES)`
    - Add optional `owner_user_id` field (max 36) to `LeadListQuerySchema`
    - Add dump fields `source_type`, `tax_distress_data`, `manual_priority` to `LeadDetailResponseSchema`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 3.3 Write unit tests for schema validation
    - Assert `IngestionRequestSchema` rejects missing `owner_user_id` and empty `records`
    - Assert `LeadListQuerySchema` rejects `source_type` not in allowed set (400)
    - Assert `LeadListQuerySchema` accepts valid `source_type` and `owner_user_id`
    - _Requirements: 11.3, 11.4_

- [x] 4. GIS connector interface and DuPage implementation
  - [x] 4.1 Create `GISConnector` abstract base class in `backend/app/services/gis/base.py`
    - Define `GISParcel` dataclass with all parcel fields from design
    - Define abstract `lookup_by_address(address: str) -> Optional[GISParcel]`
    - Define abstract `lookup_by_pin(pin: str) -> Optional[GISParcel]`
    - Define abstract properties `connector_name` and `market`
    - Create `GISConnectorRegistry` as a `dict[str, GISConnector]`
    - _Requirements: 8.1_

  - [x] 4.2 Implement `DuPageGISConnector` in `backend/app/services/gis/dupage_gis_connector.py`
    - Implement `lookup_by_address` calling DuPage GIS REST endpoint with 10-second timeout
    - Implement `lookup_by_pin` with same timeout
    - Map API response fields to `GISParcel` dataclass
    - Register connector in `GISConnectorRegistry` under key `"dupage_il"`
    - _Requirements: 8.1, 8.6_

  - [x] 4.3 Write unit tests for `DuPageGISConnector`
    - Mock HTTP responses; assert correct `GISParcel` field mapping
    - Assert timeout after 10 seconds; assert `None` returned when no match
    - _Requirements: 8.1, 8.6_


- [x] 5. Deduplication engine in `backend/app/services/deduplication_engine.py`
  - [x] 5.1 Implement `DeduplicationEngine` with address normalization and lead lookup
    - Implement `normalize_address(address: str) -> str`: uppercase, strip punctuation via regex, collapse whitespace
    - Implement `find_existing_lead(property_street, pin) -> Optional[Lead]`: check normalized address first, PIN as secondary key
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 5.2 Write property test for deduplication — same address never creates a second lead (Property 5)
    - **Property 5: Deduplication — same address never creates a second lead**
    - Use `st.text(min_size=5, max_size=200)` as address; insert lead, re-ingest with case/whitespace variants; assert count == 1
    - **Validates: Requirements 2.5, 7.1, 7.3, 7.4**

  - [x] 5.3 Implement `DeduplicationEngine.merge_lead` and `process_record`
    - `merge_lead`: apply non-null incoming fields to existing lead; preserve existing non-null values; log field conflicts to ImportJob `error_log`
    - `process_record`: full flow — `find_existing_lead` → `merge_lead` or create new; return `DeduplicationResult` with outcome `"created"`, `"updated"`, or `"conflict"`
    - Handle PIN mismatch case: preserve existing lead, log conflict entry with conflicting PIN and existing lead id
    - _Requirements: 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 5.4 Write property test for non-destructive merge (Property 6)
    - **Property 6: Existing non-null field values are never overwritten**
    - Use `st.fixed_dictionaries(...)` for existing lead fields + incoming overrides; assert existing non-null values preserved and conflict logged
    - **Validates: Requirements 7.5**

  - [x] 5.5 Write unit tests for `DeduplicationEngine`
    - Test address normalization with concrete examples (mixed case, extra spaces, punctuation)
    - Test PIN conflict detection
    - Test field merge behavior: null incoming → no change, non-null incoming over null existing → update, non-null incoming over non-null existing → preserve + log
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 6. Checkpoint — models, schemas, GIS, and deduplication complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Lead ingestion service in `backend/app/services/lead_ingestion_service.py`
  - [x] 7.1 Implement `LeadIngestionService` core: ImportJob lifecycle + GIS enrichment helpers
    - Constructor accepts `DeduplicationEngine` and `GISConnectorRegistry`
    - Implement `_set_skip_trace_flag(lead)`: set `needs_skip_trace = True` if both `phone_1` and `email_1` are null/empty on creation; leave unchanged on update
    - Implement `_enrich_with_gis(lead, connector, import_job_id)`: attempt address lookup → fallback to PIN → populate null fields → set `has_property_match = True`; on no match set `needs_skip_trace = True` and append `"GIS match not found"` to notes; on timeout/error log and continue; record outcome in ImportJob log
    - Implement ImportJob creation, status updates (`in_progress` → `completed`/`failed`), and abort-on-creation-failure
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 1.5_

  - [x] 7.2 Write property test for `needs_skip_trace` contact-presence rule (Property 4)
    - **Property 4: needs_skip_trace follows contact-presence rule**
    - Use `st.one_of(st.none(), st.just(""), st.text(min_size=1))` for `phone_1` and `email_1`; assert `needs_skip_trace` logic for creation; assert unchanged on update
    - **Validates: Requirements 1.5**

  - [x] 7.3 Implement `ForeclosureHandler` and `ingest_foreclosure`
    - Handler maps source record to Lead fields: `property_street`, `property_city`, `property_state` = `IL`, `property_zip`, `owner_first_name`, `owner_last_name`, `source_type` = `foreclosure`, `data_source` = `dupage_sheriff`, `county` = `DuPage`, `lead_category` = `residential`
    - Append case number to notes as `Case: <case_number>` when present
    - Append sale date to notes as `Sale Date: <YYYY-MM-DD>` when present
    - Append source URL/reference to notes when present
    - Pass normalized dict to `DeduplicationEngine.process_record()` then attempt GIS enrichment
    - Set `owner_user_id` from request parameter
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 7.4 Implement `LongOwnedHandler` and `ingest_long_owned`
    - Skip records missing `acquisition_date`; log `missing acquisition_date` + PIN
    - Skip non-SFR records; log `non-SFR assessor classification` + PIN
    - Calculate ownership duration; skip records < 15 full calendar years
    - Append `Owned 20+ years` to notes when ownership ≥ 20 years (idempotently)
    - Set `source_type` = `long_owned`, `data_source` = `dupage_gis`, `property_state` = `IL`, `county` = `DuPage`, `lead_category` = `residential`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 7.5 Write property test for long-owned 15-year boundary (Property 7)
    - **Property 7: long_owned threshold boundary is respected**
    - Use `st.dates(max_value=date.today())` as `acquisition_date`; assert records ≥ 15 years produce `source_type = long_owned` and records < 15 years are skipped
    - **Validates: Requirements 3.1, 3.4**


  - [x] 7.6 Implement `AbsenteeOwnerHandler` and `ingest_absentee_owner`
    - Normalize both property address and mailing address (uppercase, strip punctuation, collapse whitespace); skip records where normalized addresses are equal
    - Set `source_type` = `absentee_owner`, `data_source` = `dupage_gis`, `mailing_address`, `mailing_city`, `mailing_state`, `mailing_zip`
    - When property also qualifies as long-owned (≥ 15 years), keep `source_type = absentee_owner` and append `Long-owned absentee` to notes
    - Skip non-SFR records with a log entry
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 7.7 Write property test for absentee owner detection via normalized address (Property 8)
    - **Property 8: Absentee owner detection uses normalized address comparison**
    - Use `st.tuples(st.text(), st.text())` as `(property_address, mailing_address)`; assert absentee detection after normalization; assert equal normalized addresses are not tagged
    - **Validates: Requirements 4.1**

  - [x] 7.8 Implement `TaxDistressHandler` and `ingest_tax_distress`
    - Set `source_type` = `tax_distress`, `data_source` = `tax_distress_source`
    - Store `tax_distress_data` JSON with `signal_type`, `delinquent_amount` (null if absent), `tax_year` (null if absent)
    - Never write tax delinquency/sale language or amounts to `notes` field
    - Apply PIN+address deduplication per Requirement 5.5 (both must match; conflict if only one matches)
    - Attempt GIS enrichment after deduplication
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 7.9 Write property test for tax_distress_data field storage (Property 9)
    - **Property 9: tax_distress_data stores all required fields from source**
    - Use `st.fixed_dictionaries({"signal_type": st.sampled_from(["tax_delinquency","tax_sale"]), "delinquent_amount": st.one_of(st.none(), st.floats()), "tax_year": st.one_of(st.none(), st.integers())})`; assert stored JSON matches source
    - **Validates: Requirements 5.3, 5.6**

  - [x] 7.10 Write property test for tax distress language absent from notes (Property 10)
    - **Property 10: Tax distress language never appears in notes**
    - For any tax distress ingestion, assert `notes` contains none of: `tax delinquency`, `tax sale`, `delinquent`, or any delinquent amount/tax year value from `tax_distress_data`
    - **Validates: Requirements 5.4**

  - [x] 7.11 Implement `ManualDistressHandler` and `process_csv`
    - Parse CSV; reject files > 10 MB or invalid CSV with 400 before any row processing
    - Required column: `property_address`; optional: `condition_notes`, `distress_reason`, `manual_priority`
    - Skip rows missing or unparseable `property_address`; log row number and reason; increment `rows_skipped`
    - Store `condition_notes` and `distress_reason` in `notes` (truncated to 2000 chars each)
    - When matching lead exists, append to existing notes separated by `; `
    - Validate `manual_priority` is integer in [1,5]; store if valid; log warning and skip field if invalid
    - Set `source_type` = `manual_distress`, `data_source` = `manual_csv`
    - Count rows: ≤ 500 → run synchronously → return 200 with summary; > 500 → write to temp path → enqueue Celery task → return 202 with `import_job_id`
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [x] 7.12 Write property test for `manual_priority` bounds validation (Property 11)
    - **Property 11: manual_priority validated and stored within bounds**
    - Use `st.integers()` as `manual_priority`; assert [1,5] stored correctly; assert out-of-range values leave field null and log warning
    - **Validates: Requirements 6.6**

  - [x] 7.13 Write unit tests for `LeadIngestionService`
    - Test per-handler field mapping with concrete record examples for each source type
    - Test GIS enrichment with mocked connector: match found → fields populated; no match → `needs_skip_trace = True` + note appended; timeout → fields null, batch continues
    - Test ImportJob lifecycle: creation, in-progress updates, completed/failed states
    - Test CSV row count branching: 499 rows → 200 sync, 500 rows → 200 sync, 501 rows → 202 async
    - _Requirements: 1.1–1.7, 2.1–2.7, 3.1–3.6, 4.1–4.5, 5.1–5.6, 6.1–6.9, 8.1–8.7, 9.1–9.7_


- [x] 8. Checkpoint — ingestion service complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Property-based tests for source_type assignment and propagation
  - [x] 9.1 Write property test for valid source_type assignment (Property 1)
    - **Property 1: source_type assignment is always valid**
    - Use `st.sampled_from(VALID_SOURCE_TYPES)`; ingest via each handler; assert `lead.source_type` equals the expected value and is in `VALID_SOURCE_TYPES`
    - **Validates: Requirements 1.1, 1.6**

  - [x] 9.2 Write property test for invalid source_type rejection (Property 2)
    - **Property 2: Invalid source_type is always rejected**
    - Use `st.text().filter(lambda s: s not in VALID_SOURCE_TYPES)`; assert `LeadIngestionService` returns error response and no lead is created
    - **Validates: Requirements 1.7**

  - [x] 9.3 Write property test for owner_user_id propagation (Property 3)
    - **Property 3: owner_user_id propagates to every created lead**
    - Use `st.text(min_size=1, max_size=36)` as `user_id`; ingest batch; assert every created lead has `owner_user_id` == input `user_id`
    - **Validates: Requirements 1.2**

- [x] 10. Scoring engine extension in `backend/app/services/` (deterministic scoring)
  - [x] 10.1 Add `source_type_distress` scoring dimension to `DeterministicScoringEngine`
    - Award 10 points when `source_type` in `{"foreclosure", "tax_distress", "long_owned"}` for residential leads, capped at 10
    - Award 5 additional points when `tax_distress_data` is non-null; combined cap = 15
    - Short-circuit `absentee_owner` dimension to full 10 points when `source_type = "absentee_owner"` (skip mailing address re-evaluation)
    - Pass `manual_priority` to existing `_manual_priority_score` stub when non-null
    - Never include tax distress language (`tax_delinquency`, `tax_sale`, `delinquent`, or any `tax_distress_data` value) in `top_signals` or `recommended_action`
    - Return `source_type_distress` dimension value in `score_details`
    - Unknown `source_type` in scoring → dimension scores 0; no exception raised
    - Malformed `tax_distress_data` JSON → log warning; treat as null; no exception raised
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 10.2 Write property test for source_type_distress dimension (Properties 14 & 15)
    - **Property 14: source_type_distress dimension is exactly 10 points for qualifying source types**
    - Use `st.builds(Lead, source_type=st.sampled_from(["foreclosure","tax_distress","long_owned"]))` with mocked DB; assert `score_details["source_type_distress"]` == 10 and does not exceed 10
    - **Property 15: tax_distress_data bonus adds exactly 5 points**
    - Assert lead with non-null `tax_distress_data` scores 5 more than equivalent lead with `tax_distress_data = null`; assert combined cap of 15 enforced
    - **Validates: Requirements 12.1, 12.2**

  - [x] 10.3 Write property test for tax distress language absent from LeadScore outputs (Property 16)
    - **Property 16: Tax distress language absent from LeadScore outputs**
    - For any lead carrying `tax_distress_data`, assert `top_signals` and `recommended_action` contain none of: `tax_delinquency`, `tax_sale`, `delinquent`, or any value from `tax_distress_data`
    - **Validates: Requirements 12.3**

  - [x] 10.4 Write property test for absentee_owner full-score short-circuit (Property 17)
    - **Property 17: absentee_owner source_type always scores full 10 points in absentee dimension**
    - Use `st.builds(Lead, source_type=st.just("absentee_owner"))` with varied mailing/property address combinations; assert `absentee_owner` dimension == 10 regardless
    - **Validates: Requirements 12.5**

  - [x] 10.5 Write unit tests for scoring engine with new dimensions
    - Test `source_type_distress` dimension for each qualifying source type, each non-qualifying source type, and null source_type
    - Test `absentee_owner` short-circuit
    - Test tax distress signal absence from `top_signals` and `recommended_action`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_


- [x] 11. Ingestion controller Blueprint in `backend/app/controllers/ingestion_controller.py`
  - [x] 11.1 Create `ingestion_controller.py` Flask Blueprint with prefix `/api/ingestion`
    - Implement `POST /api/ingestion/foreclosure` → validate with `IngestionRequestSchema` → call `LeadIngestionService.ingest_foreclosure` → return ImportJob response
    - Implement `POST /api/ingestion/long-owned` → `ingest_long_owned`
    - Implement `POST /api/ingestion/absentee-owner` → `ingest_absentee_owner`
    - Implement `POST /api/ingestion/tax-distress` → `ingest_tax_distress`
    - Implement `GET /api/ingestion/jobs/<job_id>` → return ImportJob serialized with `ImportJobResponseSchema`
    - Resolve caller from `X-User-Id` header; accept `owner_user_id` from request body for the target account
    - Apply `@handle_errors` decorator; return 400 for validation errors using project error envelope
    - Register Blueprint in `backend/app/__init__.py`
    - _Requirements: 9.1, 9.2, 9.6, 1.7_

  - [x] 11.2 Implement `POST /api/ingestion/csv` endpoint
    - Accept `multipart/form-data`; reject > 10 MB with 400 before parsing
    - Stream first 501 rows to determine sync vs async path
    - ≤ 500 rows: run `LeadIngestionService.process_csv()` inline → return 200 with summary `{rows_processed, leads_created, leads_updated, rows_skipped}`
    - > 500 rows: write to temp path → `process_csv_ingestion.delay(job_id, tmp_path)` → return 202 `{import_job_id}`
    - Validate `owner_user_id` query param via `CSVUploadQuerySchema`
    - _Requirements: 6.1, 6.3, 6.8, 6.9_

  - [x] 11.3 Write unit tests for ingestion controller
    - Assert 400 returned for invalid `source_type`
    - Assert 202 returned for CSV > 500 rows (mock Celery task)
    - Assert 200 returned for CSV ≤ 500 rows with inline processing
    - Assert filter params passed correctly to service layer
    - Assert `GET /api/ingestion/jobs/<job_id>` returns correct fields
    - _Requirements: 1.7, 6.3, 6.8, 6.9, 9.6_

- [x] 12. Extend lead list controller and filters in `backend/app/controllers/lead_controller.py`
  - [x] 12.1 Add `source_type` and `owner_user_id` filter params to the lead list query
    - Deserialize both params via updated `LeadListQuerySchema`
    - Conditionally apply `.filter(Lead.source_type == source_type)` when `source_type` param is present
    - Conditionally apply `.filter(Lead.owner_user_id == owner_user_id)` when `owner_user_id` param is present
    - Return 400 with descriptive message for invalid `source_type` values
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 12.2 Write property test for source_type filter correctness (Property 12)
    - **Property 12: source_type filter returns only matching leads**
    - Use `st.builds(...)` to create leads with varied `source_type` values; assert every lead in filtered response matches filter value; assert no lead with different `source_type` (including null) appears
    - **Validates: Requirements 11.1, 11.3**

  - [x] 12.3 Write property test for owner_user_id filter correctness (Property 13)
    - **Property 13: owner_user_id filter returns only matching leads**
    - Use `st.builds(...)` to create leads owned by different users; assert every lead in filtered response matches filter `owner_user_id`
    - **Validates: Requirements 11.2**

  - [x] 12.4 Write unit tests for lead controller filter extension
    - Assert `source_type` filter applied to DB query when param present
    - Assert `owner_user_id` filter applied to DB query when param present
    - Assert invalid `source_type` returns 400 with descriptive message
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 13. Checkpoint — backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Frontend type and API service updates
  - [x] 14.1 Extend TypeScript types in `frontend/src/types/index.ts`
    - Add `source_type?: 'foreclosure' | 'long_owned' | 'absentee_owner' | 'tax_distress' | 'manual_distress'` to `PropertyListFilters`
    - Add `owner_user_id?: string` to `PropertyListFilters`
    - Add `source_type`, `tax_distress_data`, `manual_priority` to the Lead/Property response type
    - _Requirements: 11.1, 11.2_

  - [x] 14.2 Update API service in `frontend/src/services/api.ts`
    - Pass `source_type` and `owner_user_id` as query params to `GET /api/leads/` when present in filters
    - _Requirements: 11.1, 11.2_

- [x] 15. Frontend filter controls in the lead list component
  - [x] 15.1 Add `source_type` MUI Select and `owner_user_id` MUI TextField to lead list filter bar
    - `source_type`: MUI `Select` with "All Sources" as default empty option, one `MenuItem` per allowed value; placed alongside existing `property_type` and `lead_category` filters
    - `owner_user_id`: MUI `TextField` with placeholder `"Owner user ID"`; placed after `source_type` control
    - Both filter changes reset pagination to page 1
    - Wire both controls to the React Query hook via `PropertyListFilters`
    - _Requirements: 11.1, 11.2_

  - [x] 15.2 Write Vitest component tests for new filter controls
    - Assert `source_type` Select renders all 5 options plus "All Sources"
    - Assert selecting a `source_type` value passes it as query param
    - Assert entering `owner_user_id` passes it as query param
    - Assert page resets to 1 when either filter changes
    - _Requirements: 11.1, 11.2_

- [x] 16. Celery task for async CSV ingestion
  - [x] 16.1 Register `process_csv_ingestion` Celery task in `backend/celery_worker.py`
    - Task signature: `process_csv_ingestion(job_id: int, file_path: str, owner_user_id: str)`
    - Call `LeadIngestionService.process_csv(job_id, file_path, owner_user_id)`
    - Update ImportJob status to `failed` on exception; clean up temp file on completion or failure
    - _Requirements: 6.9, 9.3, 9.4, 9.5_

  - [x] 16.2 Write integration test for async CSV path
    - Upload a 501-row CSV against a test app with Celery in `task_always_eager` mode
    - Assert 202 response with `import_job_id`
    - Assert ImportJob status = `completed` after task runs
    - _Requirements: 6.9_

- [x] 17. Final checkpoint — all tests pass
  - Ensure all unit, property, and integration tests pass. Ask the user if questions arise.


---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP delivery
- All Alembic migrations must use `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and `DROP ... IF EXISTS` — never `op.add_column()` or `op.create_index()`
- The `DeduplicationEngine` and scoring engine changes are platform-wide; they affect all leads, not only DuPage County leads
- `tax_distress_data` is a scoring-only field: its contents must never appear in `notes`, `top_signals`, or `recommended_action`
- GIS enrichment is skipped (not an error) when no connector is registered for a lead's market
- Property-based tests use Hypothesis with `@settings(max_examples=100)`; test file is `tests/test_dupage_lead_database_properties.py`
- All ingestion property tests run against an in-memory SQLite test DB via the existing `conftest.py` fixtures

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["2.3", "3.1", "4.1"] },
    { "id": 2, "tasks": ["3.2", "4.2", "5.1"] },
    { "id": 3, "tasks": ["3.3", "4.3", "5.2", "5.3"] },
    { "id": 4, "tasks": ["5.4", "5.5", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 6, "tasks": ["7.5", "7.6", "7.8"] },
    { "id": 7, "tasks": ["7.7", "7.9", "7.10", "7.11"] },
    { "id": 8, "tasks": ["7.12", "7.13", "9.1", "9.2", "9.3", "10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "10.4", "10.5", "11.1"] },
    { "id": 10, "tasks": ["11.2", "11.3", "12.1"] },
    { "id": 11, "tasks": ["12.2", "12.3", "12.4", "14.1"] },
    { "id": 12, "tasks": ["14.2", "15.1", "16.1"] },
    { "id": 13, "tasks": ["15.2", "16.2"] }
  ]
}
```
