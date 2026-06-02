# Requirements Document

## Introduction

This feature is a **platform enhancement**, not a DuPage County silo. It extends the platform's general lead data model and scoring engine with new capabilities — `source_type` tagging, `tax_distress_data` storage, `manual_priority` scoring, GIS-based enrichment, deduplication improvements, and lead list filtering — that benefit all leads in the system, regardless of geography.

DuPage County is the **first market** to be fully loaded using these capabilities. The DuPage-specific ingestion connectors (sheriff sale, long-owned GIS query, absentee owner GIS query, tax distress source) populate leads for DuPage County single-family homes and assign them to the designated platform user. Those leads are then scored and filtered by the same platform-wide engine that applies to all leads.

The feature supports five distinct lead source types for DuPage County: foreclosure/sheriff sale, long-owned homeowner, absentee owner, tax distress, and physical distress / manual upload. The end result for the user is a well-qualified, scored list of DuPage County single-family motivated-seller leads, viewable through the existing lead list UI with `source_type` and `owner_user_id` filters applied. This is a data-ingestion-only feature; caller assignment, outreach workflows, and skip-trace execution are out of scope.

## Glossary

- **Lead**: A record in the `leads` table (mapped to the `Property` SQLAlchemy model) representing a property owner who is a potential motivated seller.
- **Lead_Ingestion_Service**: The backend service responsible for transforming raw data from each source type into Lead records and persisting them to the database.
- **Deduplication_Engine**: The component that prevents duplicate Lead records by matching incoming records against existing ones using property address and/or PIN.
- **Source_Type**: A platform-wide categorical tag on each Lead indicating how it was discovered (e.g., `foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, `manual_distress`). Any lead in the system may carry a `source_type` value.
- **Distress_Signal**: A non-contact metadata flag attached to a Lead that indicates a motivation type (foreclosure, tax delinquency, physical distress) used only for scoring — never surfaced in call scripts.
- **GIS_Connector**: A pluggable integration component that performs parcel lookups against a specific market's Geographic Information System dataset. The DuPage_GIS connector is the first implementation; future markets can provide their own GIS connectors using the same interface.
- **DuPage_GIS**: The DuPage County Geographic Information System parcel dataset providing authoritative property, parcel, and owner data for DuPage County, Illinois. Accessed via the DuPage_GIS GIS_Connector.
- **Sheriff_Sale_Source**: The DuPage County Sheriff's website or associated public data feed listing active foreclosure and sheriff sale cases.
- **Recorder_Source**: The DuPage County Recorder of Deeds public records system providing lis pendens, deed, lien, and ownership documents.
- **Tax_Distress_Source**: A public or third-party data source providing tax delinquency or tax sale signals for DuPage County properties.
- **CSV_Upload**: A manually prepared comma-separated file containing drive-by or field-observed distressed properties for any market, uploaded through the platform UI. DuPage County is the first market to use this general-purpose ingestion tool.
- **PIN**: The DuPage County parcel identification number uniquely identifying a parcel within the county.
- **Enrichment_Needed_Flag**: A boolean flag on a Lead record (`needs_skip_trace = true`) indicating that the record lacks sufficient contact data and requires further enrichment before outreach.
- **userx**: The designated platform user profile that owns all DuPage County leads ingested through this feature.
- **Import_Job**: An existing platform record that tracks the status, row counts, and error log for a single batch ingestion run.
- **Celery_Worker**: The existing asynchronous task processing system (Celery + Redis) used for background ingestion runs.

## Requirements

### Requirement 1: Lead Source Type Tagging

**User Story:** As a real estate investor, I want every ingested DuPage County lead tagged with its source type, so that I can filter, sort, and score leads by how they were discovered.

#### Acceptance Criteria

1. THE Lead_Ingestion_Service SHALL assign a `source_type` value to every Lead record created by this feature, drawn from the set: `foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, `manual_distress`.
2. THE Lead_Ingestion_Service SHALL set the `owner_user_id` field on every ingested Lead to the `user_id` value of the designated platform account provided in the ingestion request.
3. THE Lead_Ingestion_Service SHALL set the `lead_category` field to `residential` for all leads ingested through this feature.
4. THE Lead_Ingestion_Service SHALL set the `property_state` field to `IL` and the `county` field to `DuPage` for all ingested leads.
5. WHEN a Lead record is created and both the `phone_1` field and the `email_1` field are null or empty string, THE Lead_Ingestion_Service SHALL set `needs_skip_trace` to `true`. WHEN a Lead record is created and at least one of `phone_1` or `email_1` is a non-empty string, THE Lead_Ingestion_Service SHALL set `needs_skip_trace` to `false`. WHEN a Lead record is updated by a subsequent ingestion run, THE Lead_Ingestion_Service SHALL leave `needs_skip_trace` unchanged.
6. THE Lead_Ingestion_Service SHALL record the ingestion source name in the `data_source` field using one of the following values: `dupage_gis`, `dupage_sheriff`, `dupage_recorder`, `tax_distress_source`, `manual_csv`.
7. IF the `source_type` value provided to the Lead_Ingestion_Service is not one of `foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, or `manual_distress`, THEN THE Lead_Ingestion_Service SHALL reject the record without persisting it and SHALL return an error response identifying the invalid `source_type` value.

### Requirement 2: Foreclosure / Sheriff Sale Lead Ingestion

**User Story:** As a real estate investor, I want foreclosure and sheriff sale properties from DuPage County automatically ingested as leads, so that I can target highly motivated sellers facing a court-ordered sale.

#### Acceptance Criteria

1. WHEN a foreclosure or sheriff sale record is ingested, THE Lead_Ingestion_Service SHALL create or update a Lead with the following fields populated where available: `property_street`, `property_city`, `property_state`, `property_zip`, `owner_first_name`, `owner_last_name`, `source_type` = `foreclosure`, `data_source` = `dupage_sheriff`.
2. WHEN a foreclosure or sheriff sale record contains a court case number, THE Lead_Ingestion_Service SHALL store it in the `notes` field using the format `Case: <case_number>`.
3. WHEN a foreclosure or sheriff sale record contains a scheduled sale date, THE Lead_Ingestion_Service SHALL store it in the `notes` field using the format `Sale Date: <YYYY-MM-DD>`.
4. WHEN a foreclosure or sheriff sale record contains a source URL or reference document identifier, THE Lead_Ingestion_Service SHALL store it in the `notes` field.
5. WHEN a foreclosure record's property address matches an existing Lead in the database, THE Deduplication_Engine SHALL update the existing Lead record rather than creating a duplicate, and SHALL append the new distress signal information to the existing `notes` field.
6. IF a foreclosure record's property address does not match any existing Lead, THEN THE Lead_Ingestion_Service SHALL create a new Lead record and SHALL set `needs_skip_trace` to `true`. WHEN updating an existing Lead, THE Lead_Ingestion_Service SHALL leave `needs_skip_trace` unchanged.
7. WHEN a foreclosure record is ingested, THE Lead_Ingestion_Service SHALL attempt to match the foreclosure property address against DuPage_GIS parcel data and, when a match is found, SHALL populate `county_assessor_pin`, `bedrooms`, `square_footage`, `year_built`, and `property_type` on the Lead.

### Requirement 3: Long-Owned Homeowner Lead Ingestion

**User Story:** As a real estate investor, I want single-family homeowners in DuPage County who have owned their property for 15 or more years ingested as leads, so that I can target high-equity owners who may be ready to sell.

#### Acceptance Criteria

1. WHEN a property record from DuPage_GIS or an equivalent authoritative source indicates a single-family home with a recorded acquisition date of 15 or more full calendar years before the ingestion date, THE Lead_Ingestion_Service SHALL create a new Lead with `source_type` = `long_owned` if no Lead with the same `county_assessor_pin` already exists, or update the existing Lead's fields if one does.
2. THE Lead_Ingestion_Service SHALL populate `owner_first_name`, `owner_last_name`, `property_street`, `property_city`, `property_state`, `property_zip`, and `county_assessor_pin` from the source data, leaving any field null when the corresponding source value is absent.
3. THE Lead_Ingestion_Service SHALL populate `mailing_address`, `mailing_city`, `mailing_state`, and `mailing_zip` from the source data, leaving any field null when the corresponding source value is absent.
4. WHEN a property record contains a deed or transfer date, THE Lead_Ingestion_Service SHALL set the `acquisition_date` field to that date. IF a property record does not contain a deed or transfer date, THE Lead_Ingestion_Service SHALL skip that record without creating or updating a Lead and SHALL log the skipped record with the reason `missing acquisition_date` and the record's PIN.
5. WHEN a property has been owned for 20 or more full calendar years (inclusive) as of the ingestion date, THE Lead_Ingestion_Service SHALL write `Owned 20+ years` to the `notes` field if it is empty, or append `; Owned 20+ years` to the existing `notes` value if that exact text is not already present.
6. IF a property record's assessor classification is not in the list of single-family residential codes explicitly enumerated in the ingestion service configuration (e.g., DuPage County class code 202), THEN THE Lead_Ingestion_Service SHALL skip that record without creating or updating a Lead and SHALL log the exclusion with the reason `non-SFR assessor classification` and the record's PIN.

### Requirement 4: Absentee Owner Lead Ingestion

**User Story:** As a real estate investor, I want single-family homes in DuPage County where the owner's mailing address differs from the property address ingested as leads, so that I can target non-occupant owners who may be more willing to sell.

#### Acceptance Criteria

1. WHEN a property record's owner mailing address differs from the property address (compared after normalizing both to uppercase, trimming whitespace, and removing punctuation), THE Lead_Ingestion_Service SHALL create a new Lead with `source_type` = `absentee_owner` if no Lead with the same `county_assessor_pin` already exists, or update the existing Lead's fields if one does.
2. THE Lead_Ingestion_Service SHALL set the `mailing_address`, `mailing_city`, `mailing_state`, and `mailing_zip` fields from the owner's mailing address data.
3. THE Lead_Ingestion_Service SHALL populate `owner_first_name`, `owner_last_name`, `property_street`, `property_city`, `property_state`, `property_zip`, and `county_assessor_pin` from the source data, leaving any field null when the corresponding source value is absent.
4. WHEN an absentee owner property also qualifies as a long-owned lead (owned 15+ full calendar years), THE Lead_Ingestion_Service SHALL set `source_type` to `absentee_owner` and append the text `Long-owned absentee` to the `notes` field, separated from any existing notes content by `; `, rather than creating a second duplicate Lead record.
5. IF a property record's assessor classification does not indicate single-family residential use, THEN THE Lead_Ingestion_Service SHALL skip that record without creating or updating a Lead and SHALL record a log entry indicating the record was excluded due to classification.

### Requirement 5: Tax Distress Lead Ingestion

**User Story:** As a real estate investor, I want properties with tax delinquency or tax sale signals in DuPage County ingested as leads with a scoring-only distress flag, so that I can prioritize financially distressed sellers without surfacing sensitive language in outreach materials.

#### Acceptance Criteria

1. WHEN a tax delinquency or tax sale record is ingested, THE Lead_Ingestion_Service SHALL create or update a Lead with `source_type` = `tax_distress` and `data_source` = `tax_distress_source`.
2. WHEN a tax delinquency or tax sale record is ingested, THE Lead_Ingestion_Service SHALL populate `county_assessor_pin`, `owner_first_name`, `owner_last_name`, `property_street`, `property_city`, `property_state`, and `property_zip` from the source data for each field present in the source record, and SHALL leave any field absent from the source record as null on the Lead.
3. WHEN a tax delinquency or tax sale record is ingested, THE Lead_Ingestion_Service SHALL store a `tax_distress_data` entry on the Lead record containing at minimum: a `signal_type` field set to either `tax_delinquency` or `tax_sale`, a `delinquent_amount` field set to the source value if available or null if absent, and a `tax_year` field set to the source value if available or null if absent.
4. THE Lead_Ingestion_Service SHALL NOT populate the `notes` field with any tax delinquency or financial distress language, such that the `notes` field contains no reference to tax delinquency, tax sale, delinquent amounts, or tax years originating from a `tax_distress` source record.
5. WHEN a tax distress record is ingested, IF the record's PIN matches an existing Lead's `county_assessor_pin` AND the record's `property_street` and `property_zip` both match the existing Lead's corresponding fields (case-insensitive), THEN THE Deduplication_Engine SHALL update the existing Lead by merging the tax distress signal into its `tax_distress_data`. IF the PIN matches but the `property_street` or `property_zip` does not match, or the `property_street` and `property_zip` match but the PIN does not match, THEN THE Lead_Ingestion_Service SHALL append a conflict entry to the Import_Job error log containing the incoming PIN, incoming address, and the ID of the conflicting existing Lead, and SHALL skip the record without creating or updating a Lead.
6. WHEN a tax distress record is ingested, THE Lead_Ingestion_Service SHALL store the `tax_distress_data` entry such that the Lead_Scoring_Engine can read the `signal_type`, `delinquent_amount`, and `tax_year` fields from the Lead record without additional transformation.

### Requirement 6: Manual Lead Upload via CSV

**User Story:** As a real estate investor, I want to upload a CSV file of properties observed in the field as physically distressed, so that I can add drive-by findings directly to the lead database for any market.

#### Acceptance Criteria

1. THE Platform SHALL provide a general-purpose CSV upload endpoint that accepts a file containing manually observed distressed properties for any geography and creates or updates Lead records with `source_type` = `manual_distress`. DuPage County is the first market to use this endpoint, but the endpoint is not restricted to DuPage County properties.
2. THE Platform SHALL accept CSV files with the following columns: `property_address` (required), `condition_notes` (optional), `distress_reason` (optional), `manual_priority` (optional, integer 1–5).
3. IF the uploaded file is not a valid CSV or exceeds 10 MB, THEN THE Platform SHALL reject the request with a 400 error before processing any rows.
4. WHEN a CSV row contains a valid `property_address` and no Lead with a matching normalized address already exists, THE Lead_Ingestion_Service SHALL create a new Lead record and store `condition_notes` and `distress_reason` in the `notes` field, truncated to 2000 characters each.
5. WHEN a CSV row contains a valid `property_address` and a Lead with a matching normalized address already exists, THE Lead_Ingestion_Service SHALL update that existing Lead and append `condition_notes` and `distress_reason` to the existing `notes` field, separated by `; `.
6. WHEN a CSV row contains a `manual_priority` value that is an integer between 1 and 5 inclusive, THE Lead_Ingestion_Service SHALL store it in the `manual_priority` column on the Lead record. IF the `manual_priority` value is present but not an integer between 1 and 5, THE Lead_Ingestion_Service SHALL skip the `manual_priority` field for that row and log a warning without failing the row.
7. IF a CSV row is missing `property_address` or contains a `property_address` value that cannot be parsed as a street address, THEN THE Lead_Ingestion_Service SHALL skip that row, log the row number and a descriptive error, and continue processing remaining rows.
8. WHEN the CSV upload completes, THE Platform SHALL return a summary including total rows processed, leads created, leads updated, and rows skipped with reasons.
9. THE Platform SHALL process CSV uploads synchronously for files up to 500 rows and SHALL dispatch to the Celery_Worker for files exceeding 500 rows, returning a 202 Accepted response with the Import_Job id.

### Requirement 7: Deduplication and Address Matching

**User Story:** As a real estate investor, I want the ingestion process to detect duplicate properties and merge signals rather than creating separate records, so that each property has one canonical Lead record that aggregates all distress signals.

> **Platform scope:** The Deduplication_Engine improvements in this requirement apply to all ingestion runs across the platform, not only to DuPage County leads.

#### Acceptance Criteria

1. WHEN ingesting any lead, THE Deduplication_Engine SHALL check for an existing Lead with a matching `property_street` value using case-insensitive comparison after trimming leading/trailing whitespace and collapsing internal whitespace runs to a single space.
2. WHEN a PIN is available on the incoming record, THE Deduplication_Engine SHALL also check for an existing Lead with a matching `county_assessor_pin` as a secondary deduplication key.
3. WHEN a duplicate is confirmed (both `property_street` and `county_assessor_pin` match when a PIN is present; address alone when no PIN is available), THE Deduplication_Engine SHALL update the existing Lead record with any new non-null field values from the incoming record.
4. WHEN a duplicate is confirmed, THE Deduplication_Engine SHALL NOT create a new Lead record.
5. WHEN an incoming record provides a non-null value for a field already populated on the existing Lead, THE Deduplication_Engine SHALL preserve the existing value, and SHALL log a conflict entry in the Import_Job error log recording the field name, the existing value, and the rejected incoming value.
6. WHEN an incoming record's `property_street` matches an existing Lead but the incoming PIN differs from the existing Lead's `county_assessor_pin`, THE Deduplication_Engine SHALL preserve the existing Lead without modification and SHALL log a conflict entry recording the conflicting PIN value and the existing Lead's id.
7. IF no existing Lead matches the incoming record by address or PIN, THEN THE Lead_Ingestion_Service SHALL create a new Lead record.
8. WHEN an ingestion record is processed, THE Lead_Ingestion_Service SHALL record the deduplication outcome in the Import_Job record's row-level log using one of the values: `created`, `updated`, or `conflict`.

### Requirement 8: Property Enrichment via GIS Connector

**User Story:** As a real estate investor, I want leads created from non-GIS sources (foreclosure, tax distress, manual) automatically enriched with parcel data from a GIS connector, so that as much property detail as possible is filled in at ingestion time.

> **Platform scope:** GIS enrichment is a general platform capability. Any lead can be enriched if a GIS connector exists for that market. The DuPage_GIS connector is the **first implementation** of this pattern; future markets can add their own GIS connectors using the same interface. Acceptance criteria below use the DuPage_GIS connector as the concrete example.

#### Acceptance Criteria

1. WHEN a Lead is created from the `foreclosure`, `tax_distress`, or `manual_distress` source types and a GIS connector is configured for the Lead's market, THE Lead_Ingestion_Service SHALL attempt a lookup against the configured GIS parcel dataset, using the property address as the primary lookup key and falling back to PIN when the address lookup yields no result, with a timeout of 10 seconds per lookup. For DuPage County leads, THE Lead_Ingestion_Service SHALL use the DuPage_GIS connector.
2. WHEN a GIS connector match is found, THE Lead_Ingestion_Service SHALL populate the following Lead fields if they are currently null: `county_assessor_pin`, `property_type`, `year_built`, `square_footage`, `bedrooms`, `bathrooms`, `lot_size`, `owner_first_name`, `owner_last_name`, `mailing_address`, `mailing_city`, `mailing_state`, `mailing_zip`.
3. WHEN a GIS connector match is found, THE Lead_Ingestion_Service SHALL set `has_property_match` to `true` on the Lead record.
4. WHEN a GIS connector lookup is attempted and returns no matching parcel, THE Lead_Ingestion_Service SHALL set `needs_skip_trace` to `true` and append the note `GIS match not found` to the Lead's `notes` field.
5. IF a GIS connector lookup is never attempted due to service unavailability or configuration, THE Lead_Ingestion_Service SHALL NOT modify `needs_skip_trace` based on that non-attempt.
6. WHEN a GIS connector lookup attempt raises an error or times out, THE Lead_Ingestion_Service SHALL log the error with the Lead's property address and source type, leave the Lead's GIS-enrichable fields unchanged, and continue ingestion without failing the entire batch.
7. THE Lead_Ingestion_Service SHALL record the GIS enrichment outcome in the Import_Job log, including: the connector name, the source type, whether a match was found, the count of fields populated from GIS, and any error reason if the lookup failed.

### Requirement 9: Import Job Tracking

**User Story:** As a real estate investor, I want every ingestion run tracked as an Import Job, so that I can audit what was loaded, when, and how many records were affected.

#### Acceptance Criteria

1. WHEN an ingestion run is initiated, THE Lead_Ingestion_Service SHALL create an Import_Job record recording the `user_id` from the request, the `source_type` being ingested, the timestamp, and setting `status` to `in_progress`, `rows_processed` to 0, `rows_imported` to 0, and `rows_skipped` to 0.
2. IF the Import_Job record cannot be created at the start of an ingestion run, THEN THE Lead_Ingestion_Service SHALL abort the run without processing any records and SHALL return an error response.
3. WHEN an ingestion run completes successfully, THE Lead_Ingestion_Service SHALL update the Import_Job record with `status` = `completed`, the final values of `rows_processed`, `rows_imported`, and `rows_skipped`, and an `error_log` that is an empty list if no rows were skipped.
4. WHEN an ingestion run fails before completion, THE Lead_Ingestion_Service SHALL update the Import_Job `status` to `failed` and record the failure reason in `error_log`.
5. THE Lead_Ingestion_Service SHALL set `status` to `completed` only after both the data processing and the Import_Job status update have succeeded without error; if the status update itself fails, the Import_Job SHALL remain in `failed` state.
6. WHILE an ingestion run is in progress, THE Platform SHALL allow retrieval of the Import_Job record returning at minimum: `id`, `status`, `source_type`, `rows_processed`, `rows_imported`, `rows_skipped`, and `created_at`.
7. WHEN a Lead is created or updated by an ingestion run, THE Lead_Ingestion_Service SHALL set the Lead's `last_import_job_id` foreign key to the id of the current Import_Job, overwriting any previously stored value.

### Requirement 10: New Lead Schema Columns

**User Story:** As a developer, I want the leads table extended with general-purpose lead tracking columns, so that all distress signals, source categorization, and manual priority data can be stored for any lead in the platform without overloading the existing `notes` field.

> **Platform scope:** `source_type`, `tax_distress_data`, and `manual_priority` are platform-wide columns. Any lead in the system — not just DuPage County leads — can have a `source_type`, a `tax_distress_data` payload, or a `manual_priority` value. DuPage County leads are the first to populate these columns at scale.

#### Acceptance Criteria

1. THE Platform SHALL add a `source_type` VARCHAR(50) nullable column to the `leads` table using an idempotent `ALTER TABLE leads ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)` migration.
2. THE Platform SHALL add a `tax_distress_data` JSONB nullable column to the `leads` table using an idempotent `ALTER TABLE leads ADD COLUMN IF NOT EXISTS tax_distress_data JSONB` migration.
3. THE Platform SHALL add a `manual_priority` INTEGER nullable column to the `leads` table using an idempotent `ALTER TABLE leads ADD COLUMN IF NOT EXISTS manual_priority INTEGER` migration.
4. THE Platform SHALL add an index named `ix_leads_source_type` on the `source_type` column using an idempotent `CREATE INDEX IF NOT EXISTS ix_leads_source_type ON leads(source_type)` migration, and that index SHALL exist in the database after the migration runs.
5. THE Platform SHALL add an index named `ix_leads_owner_user_id_source_type` on `(owner_user_id, source_type)` using an idempotent `CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id_source_type ON leads(owner_user_id, source_type)` migration, and that index SHALL exist in the database after the migration runs.
6. ALL new migrations SHALL implement a `downgrade()` function that drops `source_type`, `tax_distress_data`, and `manual_priority` columns and drops the `ix_leads_source_type` and `ix_leads_owner_user_id_source_type` indexes, each using the corresponding `IF EXISTS` variant.

### Requirement 11: Lead List Filtering by Source Type and Owner

**User Story:** As a real estate investor, I want to filter the lead list by source type and owner, so that I can review any subset of leads — such as DuPage foreclosure leads assigned to me — using the standard lead list UI.

> **Platform scope:** The `source_type` and `owner_user_id` filter parameters apply to all leads in the system. While these filters were introduced to support the DuPage lead workflow, they are general-purpose query parameters available for any market or user.

#### Acceptance Criteria

1. THE Platform SHALL extend the existing lead list API endpoint to accept a `source_type` query parameter and, when provided, return only leads whose `source_type` column matches that value exactly.
2. THE Platform SHALL extend the existing lead list API endpoint to accept an `owner_user_id` query parameter and, when provided, return only leads whose `owner_user_id` column matches that value.
3. WHEN `source_type` is provided, THE Platform SHALL validate it against the allowed set (`foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, `manual_distress`) and return a 400 error with a descriptive message for any value not in that set.
4. THE LeadListQuerySchema SHALL be updated to declare `source_type` and `owner_user_id` as optional string fields with a validator that rejects `source_type` values outside the allowed set.

### Requirement 12: Distress Signal Scoring Integration

**User Story:** As a real estate investor, I want distress signals from ingested leads to be available as scoring inputs for the lead scoring engine, so that foreclosure, tax distress, and long ownership status influence lead scores appropriately.

> **Platform scope:** All scoring changes in this requirement apply to **every residential lead in the system**, not only DuPage County leads. Any lead — regardless of geography — that has `source_type` set to `foreclosure`, `tax_distress`, `long_owned`, or `absentee_owner` will receive the corresponding scoring benefit. The `manual_priority` scoring and `tax_distress_data` bonus likewise apply to any lead in the platform that has those fields populated.

#### Acceptance Criteria

1. WHEN the Lead_Scoring_Engine scores a residential lead whose `source_type` is `foreclosure`, `tax_distress`, or `long_owned`, THE Lead_Scoring_Engine SHALL award 10 points in a `source_type_distress` scoring dimension, capped at 10 points regardless of how many qualifying `source_type` values apply.
2. WHEN the Lead_Scoring_Engine scores a lead whose `tax_distress_data` field is non-null, THE Lead_Scoring_Engine SHALL award 5 additional points in the `source_type_distress` dimension.
3. THE Lead_Scoring_Engine SHALL NOT include tax distress language (including the terms `tax delinquency`, `tax sale`, `delinquent`, or any value from `tax_distress_data`) in the `top_signals` array or the `recommended_action` text of any LeadScore record.
4. WHEN the Lead_Scoring_Engine scores a lead with a non-null `manual_priority` field, THE Lead_Scoring_Engine SHALL pass the `manual_priority` value to the `_manual_priority_score` method per the existing residential scoring logic.
5. WHEN the Lead_Scoring_Engine scores a lead with `source_type` = `absentee_owner`, THE Lead_Scoring_Engine SHALL award the full 10 points for the `absentee_owner` scoring dimension without re-evaluating whether the mailing address differs from the property address.
6. WHEN the Lead_Scoring_Engine scores a lead whose `source_type` is not one of `foreclosure`, `tax_distress`, `long_owned`, or `absentee_owner`, THE Lead_Scoring_Engine SHALL award 0 points in the `source_type_distress` dimension for that field.
7. WHEN a lead qualifies for both the `absentee_owner` dimension (via `source_type` = `absentee_owner`) and the `source_type_distress` dimension (via `source_type` = `foreclosure`, `tax_distress`, or `long_owned`), THE Lead_Scoring_Engine SHALL award points for each applicable dimension independently without reducing either dimension's score.

### Requirement 13: Ingestion API Endpoints

**User Story:** As a developer, I want REST API endpoints to trigger each source type ingestion and monitor progress, so that ingestion runs can be initiated programmatically or from an admin UI.

#### Acceptance Criteria

1. WHEN a valid POST request is received at `/api/leads/ingest/foreclosure`, THE Platform SHALL trigger a DuPage County sheriff sale ingestion run and return a 202 Accepted response containing the created Import_Job id.
2. WHEN a valid POST request is received at `/api/leads/ingest/long-owned`, THE Platform SHALL accept optional integer parameters `min_years_owned` (default 15) and `max_results` (default 5000), trigger a long-owned homeowner ingestion run, and return a 202 Accepted response containing the created Import_Job id.
3. WHEN a valid POST request is received at `/api/leads/ingest/absentee-owner`, THE Platform SHALL accept an optional integer `max_results` parameter (default 5000), trigger an absentee owner ingestion run, and return a 202 Accepted response containing the created Import_Job id.
4. WHEN a valid POST request is received at `/api/leads/ingest/tax-distress`, THE Platform SHALL trigger a DuPage County tax distress ingestion run and return a 202 Accepted response containing the created Import_Job id.
5. WHEN a valid POST request is received at `/api/leads/ingest/manual-csv`, THE Platform SHALL accept a multipart/form-data file upload, trigger the CSV ingestion process, and return either a 200 response with results (≤500 rows) or a 202 Accepted response with Import_Job id (>500 rows).
6. IF the `min_years_owned` parameter is not an integer between 1 and 100 inclusive, or `max_results` is not an integer between 1 and 10000 inclusive, THEN THE Platform SHALL return a 400 error with a message identifying the invalid parameter.
7. ALL ingestion endpoints SHALL require a `user_id` in the request body, validate that a user with that id exists in the platform, and assign ingested leads to that user. IF the `user_id` is missing or does not correspond to an existing user, THE Platform SHALL return a 422 Unprocessable Entity response.
8. IF an ingestion endpoint is called while a previous run of the same source type has a status of `pending` or `running`, THEN THE Platform SHALL return a 409 Conflict response with a message identifying the active Import_Job id.

### Requirement 14: Scope Exclusions

**User Story:** As a developer, I want clear boundaries on what this feature does NOT include, so that implementation stays focused on data ingestion.

#### Acceptance Criteria

1. THE Lead_Ingestion_Service SHALL NOT create, update, or query any caller assignment records, call queue entries, or caller-to-lead mapping tables. Any request or data path that would require writing to caller assignment structures SHALL be rejected or omitted.
2. THE Lead_Ingestion_Service SHALL NOT call any skip-trace API or external enrichment service. The only skip-trace action permitted is setting `needs_skip_trace = true` on a Lead record to signal that skip tracing is required.
3. IF a Lead record is flagged with `needs_skip_trace = true` by the ingestion service, THE Lead_Ingestion_Service SHALL NOT subsequently invoke any skip-trace service as part of the same ingestion run.
4. THE Lead_Ingestion_Service SHALL NOT write to any outreach script, mailer template, campaign, or marketing list table or record. IF an ingestion code path would require writing to those structures, it SHALL be excluded from this feature's implementation.
5. THE Lead_Ingestion_Service SHALL NOT ingest, create, or update Lead records for properties outside DuPage County, Illinois. IF a source record contains a county or state value other than DuPage County, IL, THE Lead_Ingestion_Service SHALL skip that record and log the exclusion reason.
6. THE Lead_Ingestion_Service SHALL NOT ingest properties classified as commercial, multi-family with 5 or more units, industrial, retail, or any non-residential type. IF a source record's property type or assessor class indicates a non-single-family-residential use, THE Lead_Ingestion_Service SHALL skip that record and log the exclusion reason.

### Requirement 15: DuPage County Motivated-Seller Lead View

**User Story:** As a real estate investor, I want the existing lead list UI to surface a well-qualified, scored list of DuPage County single-family motivated-seller leads, so that I can immediately begin reviewing and acting on the best opportunities.

> **Platform scope:** This requirement describes the end-state user experience that the platform enhancements in Requirements 1–14 collectively enable. The underlying lead list UI and scoring engine are not DuPage-specific — they work for all leads — but this requirement captures the specific view a DuPage-focused investor expects to see after ingestion completes.

#### Acceptance Criteria

1. WHEN the lead list is filtered with `owner_user_id` set to the designated DuPage import user and `source_type` set to one of `foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, or `manual_distress`, THE Platform SHALL return only the matching leads without mixing in leads from other markets or users.
2. WHEN a DuPage County lead has been scored by the Lead_Scoring_Engine, THE Platform SHALL display the lead's `score_tier`, `total_score`, `recommended_action`, and `top_signals` in the existing lead list UI without requiring any UI changes beyond the filter controls added in Requirement 11.
3. THE Platform SHALL sort the filtered DuPage lead list by `total_score` descending by default, so that the highest-scored motivated-seller leads appear at the top of the list.
4. WHEN a DuPage County lead is displayed in the lead list, THE Platform SHALL show the `source_type` value as a visible label, so that the investor can distinguish foreclosure, long-owned, absentee, tax distress, and manual distress leads at a glance.
5. THE Platform SHALL make the `source_type` and `owner_user_id` filter controls available in the existing lead list UI without requiring a separate DuPage-specific view or page.
