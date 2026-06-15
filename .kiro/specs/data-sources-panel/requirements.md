# Requirements Document

## Introduction

The Data Sources Panel is a UI feature in the Lead Management section of the Real Estate Analysis Platform. It gives users a clear, consolidated view of every data source that feeds into lead ingestion, enrichment, and scoring — including Google Sheets imports, external enrichment APIs (skip-trace providers, HubSpot), and the three cached Socrata datasets (Chicago parcel universe, parcel sales, and improvement characteristics). For each source the panel shows whether it is active or inactive, the type of data it provides, its refresh behavior (live/periodic vs. static), and when it was last updated. This lets users quickly diagnose why a lead score looks wrong or why enrichment data is missing.

## Glossary

- **Data_Sources_Panel**: The UI panel component that displays all data sources and their statuses.
- **Data_Source**: A named, registered provider of data used for lead ingestion, enrichment, or scoring. Persisted in the `data_sources` table or identified as a Socrata dataset.
- **Enrichment_Record**: A record in `enrichment_records` linking a lead to a data source enrichment result.
- **Socrata_Dataset**: One of the three cached county/city datasets: `parcel_universe`, `parcel_sales`, or `improvement_characteristics`. Refreshed on a periodic schedule.
- **Import_Source**: A Google Sheets spreadsheet configured as the origin of a lead import job. Tracked via `import_jobs`.
- **Sync_Log**: A record in `sync_log` tracking each Socrata cache sync attempt, its start/completion time, row count, status, and any error message.
- **Dataset_Status**: A computed status for a Socrata dataset — one of `never_synced`, `empty`, `fresh`, or `stale` — derived by `CacheStatusService`.
- **Enrichment_Status**: The last-known status of an enrichment data source for a lead — one of `pending`, `success`, or `failed` — stored in `EnrichmentRecord.status`.
- **Refresh_Type**: Whether a data source updates automatically on a schedule (`periodic`), is pulled on-demand per lead (`on_demand`), or is a one-time static upload (`static`).
- **API_Service**: The backend Flask service at `/api/data-sources/status` that aggregates and returns data source status.
- **User**: An authenticated user of the platform with their own lead set and import history.

## Requirements

### Requirement 1: Display All Data Sources

**User Story:** As a user, I want to see all data sources that contribute to my lead data in one panel, so that I understand where my lead information comes from.

#### Acceptance Criteria

1. THE Data_Sources_Panel SHALL display a list of all registered enrichment data sources retrieved from the backend API.
2. THE Data_Sources_Panel SHALL display the three Socrata datasets (`parcel_universe`, `parcel_sales`, `improvement_characteristics`) as distinct entries in the panel.
3. WHEN the authenticated User has at least one completed `ImportJob`, THE Data_Sources_Panel SHALL display the Google Sheets import source as a distinct entry showing the most recent import job. IF no `ImportJob` exists for the User, THEN the Google Sheets entry SHALL display "No imports yet."
4. IF the authenticated User's organization has a non-null HubSpot integration record, THEN THE Data_Sources_Panel SHALL display the HubSpot integration as a distinct entry.
5. WHEN a data source has `is_active = false`, THE Data_Sources_Panel SHALL render that entry with reduced opacity and display an "Inactive" label alongside the source name.
6. IF the backend API request fails, THEN THE Data_Sources_Panel SHALL display an error state rather than an empty list (see Requirement 7 for error handling details).
7. IF the backend returns an empty list of data sources, THEN THE Data_Sources_Panel SHALL display a message indicating no data sources are configured.

---

### Requirement 2: Show Refresh Type and Live/Static Indicator

**User Story:** As a user, I want to know whether each data source is live-refreshing or static, so that I can understand how current my lead data is.

#### Acceptance Criteria

1. THE Data_Sources_Panel SHALL display a `Refresh_Type` label for each data source: `Periodic` for Socrata datasets, `On Demand` for enrichment API sources, or `Static` for Google Sheets import sources.
2. WHEN a data source has `Refresh_Type = periodic`, THE Data_Sources_Panel SHALL display the `Dataset_Status` (`fresh`, `stale`, `empty`, or `never_synced`) alongside the source name.
3. WHEN a data source has `Refresh_Type = on_demand`, THE Data_Sources_Panel SHALL display the aggregate enrichment result counts across all of the authenticated User's leads: the number of leads with `status = 'success'`, the number with `status = 'pending'`, and the number with `status = 'failed'`.
4. WHEN a data source has `Refresh_Type = static`, THE Data_Sources_Panel SHALL display the `completed_at` date of the most recent completed `ImportJob` and the `rows_imported` count from that job.

---

### Requirement 3: Show Last Refresh Timestamp

**User Story:** As a user, I want to see when each data source was last updated, so that I can judge the freshness of the data being used for scoring.

#### Acceptance Criteria

1. WHEN a Socrata dataset has `Dataset_Status = fresh` or `stale`, THE Data_Sources_Panel SHALL display the `completed_at` timestamp of the most recent successful `Sync_Log` entry for that dataset, formatted as `YYYY-MM-DD HH:MM` in the user's local timezone.
2. WHEN a Socrata dataset has `Dataset_Status = never_synced` or `empty`, THE Data_Sources_Panel SHALL display the message "No successful sync has occurred" for the last refresh field.
3. WHEN a Google Sheets import source has a completed `ImportJob` (where `status = 'completed'`), THE Data_Sources_Panel SHALL display the `completed_at` timestamp of the most recent such job, formatted as `YYYY-MM-DD HH:MM` in the user's local timezone.
4. WHEN an enrichment data source has at least one `Enrichment_Record` for the authenticated User's leads, THE Data_Sources_Panel SHALL display the `created_at` timestamp of the most recent such record, formatted as `YYYY-MM-DD HH:MM` in the user's local timezone.
5. IF none of criteria 1–4 apply to a data source (i.e., it has never been synced, imported, or used for enrichment), THEN THE Data_Sources_Panel SHALL display "Never used" for the last refresh field.

---

### Requirement 4: Show Per-Lead Enrichment Coverage

**User Story:** As a user, I want to see which enrichment sources have been run against my leads, so that I can identify gaps in my lead data.

#### Acceptance Criteria

1. THE Data_Sources_Panel SHALL display, for each `on_demand` enrichment source, the count of leads with an `Enrichment_Record` where `status = 'success'` for that source, relative to the total number of leads owned by the authenticated User, shown as both a count (e.g., "12 / 50") and a percentage (e.g., "24%"). IF the User owns zero leads, THEN the panel SHALL display "0 / 0 (N/A)" without attempting a percentage calculation.
2. IF the enrichment coverage for a source is 0% (zero successful records and at least one lead exists), THEN THE Data_Sources_Panel SHALL render a fully empty progress bar and display the coverage text in a muted/secondary text color.
3. IF the enrichment coverage for a source is 100% (all leads have a successful record), THEN THE Data_Sources_Panel SHALL render a fully filled progress bar and display the coverage text in a success color (green).
4. THE Data_Sources_Panel SHALL display three explicitly labeled coverage fields per enrichment source: "Enriched" (count of leads with at least one `status = 'success'` record for this source), "Failed" (count of leads with at least one `status = 'failed'` record and no `status = 'success'` record for this source), and "Not Run" (count of leads with zero `Enrichment_Record` entries of any status for this source).
5. THE Data_Sources_Panel SHALL display a "Last updated" timestamp showing when the coverage counts were last fetched, and SHALL visually indicate when the displayed counts are more than 60 seconds old.

---

### Requirement 5: Backend API for Data Source Status

**User Story:** As a developer, I want a single API endpoint that returns the unified status of all data sources, so that the frontend panel can be built efficiently with a single fetch.

#### Acceptance Criteria

1. THE API_Service SHALL expose a `GET /api/data-sources/status` endpoint that returns a JSON array of data source status objects, where each object contains at minimum: `name`, `source_type`, `refresh_type`, `is_active`, `last_refreshed_at`, and `status`.
2. WHEN the authenticated User makes a request, THE API_Service SHALL include per-user enrichment coverage counts scoped to that User's leads, with the fields `success_count`, `failed_count`, `pending_count`, and `total_leads_count` for each `on_demand` source.
3. WHEN Socrata dataset statuses are retrieved, THE API_Service SHALL delegate to the existing `CacheStatusService` and include the resulting status value, which SHALL be one of `fresh`, `stale`, `empty`, or `never_synced`.
4. WHEN the authenticated User has a configured import source, THE API_Service SHALL include the most recent `ImportJob` fields `status`, `rows_imported`, and `completed_at` for that source. IF no `ImportJob` exists for the User, THEN those fields SHALL be `null`.
5. IF an unauthenticated request is made to this endpoint, THEN THE API_Service SHALL return HTTP 401.
6. IF the database is unavailable, THEN THE API_Service SHALL return HTTP 503 with an error message indicating the service is temporarily unavailable.
7. IF the authenticated User owns zero leads, THEN THE API_Service SHALL return `success_count: 0`, `failed_count: 0`, `pending_count: 0`, and `total_leads_count: 0` for all `on_demand` sources rather than omitting those fields.

---

### Requirement 6: Stale Data Warning

**User Story:** As a user, I want to be warned when a data source is stale or has errors, so that I can take action before relying on potentially outdated data for scoring.

#### Acceptance Criteria

1. WHEN a Socrata dataset has `Dataset_Status = stale`, THE Data_Sources_Panel SHALL display a warning indicator (amber/yellow icon) alongside the source name and include the number of days since the `completed_at` timestamp of the most recent successful `Sync_Log` entry.
2. WHEN a Socrata dataset has `Dataset_Status = never_synced` or `empty`, THE Data_Sources_Panel SHALL display an error indicator (red icon) alongside the source name.
3. WHEN a Socrata dataset's most recent `Sync_Log` entry has `status = failed`, THE Data_Sources_Panel SHALL display the `error_message` from that log entry. IF `error_message` is null or empty, THEN THE Data_Sources_Panel SHALL display "Sync failed — no details available." IF no `Sync_Log` entries exist for that dataset, THE Data_Sources_Panel SHALL display "No sync history available."
4. WHEN an enrichment source has `Enrichment_Record` entries with `status = 'failed'` created within the most recent 30 days for the authenticated User's leads, THE Data_Sources_Panel SHALL display a warning indicator alongside a count of those failures (e.g., "3 failures in last 30 days").
5. WHEN all data sources have `is_active = true` and all Socrata datasets have `Dataset_Status = fresh` and no enrichment sources have failures in the last 30 days, THE Data_Sources_Panel SHALL display a status summary banner with a green checkmark icon and the text "All data sources are current."

---

### Requirement 7: Panel Accessibility and Loading States

**User Story:** As a user, I want the panel to load quickly and be accessible, so that I can use it efficiently regardless of how I interact with the UI.

#### Acceptance Criteria

1. WHEN the Data_Sources_Panel is loading data from the API, THE Data_Sources_Panel SHALL display a loading skeleton (not a spinner) in place of each data source entry. WHEN the API response arrives, THE Data_Sources_Panel SHALL replace each skeleton with the corresponding data source entry.
2. IF the API_Service returns an error response, THEN THE Data_Sources_Panel SHALL display an error message indicating that data source status could not be loaded, alongside a "Retry" button, instead of a blank or partially populated panel.
3. THE Data_Sources_Panel SHALL set an `aria-label` attribute on each status indicator icon that includes both the data source name and its current status value (e.g., `aria-label="parcel_universe: stale"`).
4. WHEN a user activates the "Retry" button after an error, THE Data_Sources_Panel SHALL immediately re-fetch data source status from the API_Service, bypassing the 60-second cache, and SHALL replace the error state with either the loaded data entries or a new error message if the retry also fails.
5. THE Data_Sources_Panel SHALL configure React Query with a `staleTime` of 60 seconds for the data source status query, so that data is not re-fetched more frequently than once per 60 seconds during normal usage.
