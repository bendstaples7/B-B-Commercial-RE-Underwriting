# Implementation Plan: Data Sources Panel

## Overview

Implement the Data Sources Panel as a read-only diagnostic UI in the Lead Management section. The backend exposes a single `GET /api/data-sources/status` endpoint backed by `DataSourceStatusService`. The frontend renders the response with React Query, a loading skeleton, per-source status cards, enrichment coverage bars, and stale-data warning icons.

## Tasks

- [x] 1. Add TypeScript types for Data Sources Panel
  - [x] 1.1 Add five new interfaces/types to `frontend/src/types/index.ts`
    - Add `SocrataDatasetStatusValue`, `RefreshType`, `SocrataDatasetStatus`, `EnrichmentSourceStatus`, `ImportSourceStatus`, `HubSpotSourceStatus`, and `DataSourceStatus` exactly as defined in the design
    - _Requirements: 5.1, 1.1, 1.2, 1.3, 1.4_

- [x] 2. Implement backend `DataSourceStatusService`
  - [x] 2.1 Create `backend/app/services/data_source_status_service.py`
    - Implement `DataSourceStatusService` with a single `get_all_statuses(user_id)` method
    - Delegate Socrata status to `CacheStatusService.get_status()`
    - Query `data_sources` for enrichment plugins; for each plugin count `enrichment_records` rows by status scoped to leads with `owner_user_id = user_id` using a single `GROUP BY data_source_id, status` query
    - Query `import_jobs` for most recent completed job for `user_id` (`ORDER BY completed_at DESC LIMIT 1`); return null fields if none exists
    - Check `hubspot_config` for any row; return `connected: false` if absent
    - Return zeroed counts (not an error) when user has no leads
    - Propagate `SQLAlchemyError` without catching it
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.7_

  - [x] 2.2 Write property test for `DataSourceStatusService` — partition invariant
    - **Property 2: Partition invariant — counts sum to total**
    - **Validates: Requirements 4.4, 5.7**
    - File: `backend/tests/test_data_source_status_service.py`
    - Use Hypothesis to generate arbitrary `(success, failed, pending, not_run)` integer splits; assert `success + failed + pending + not_run == total_leads`

  - [x] 2.3 Write property test for `DataSourceStatusService` — coverage percentage bounded
    - **Property 1: Coverage percentages bounded [0, 100]**
    - **Validates: Requirements 4.1**
    - File: `backend/tests/test_data_source_status_service.py`
    - Use Hypothesis to generate arbitrary lead count splits; assert `(success / total) * 100` stays in [0.0, 100.0] when `total > 0`

  - [x] 2.4 Write property test for `DataSourceStatusService` — days_since_sync non-negative
    - **Property 4: Staleness day count always >= 0**
    - **Validates: Requirements 6.1**
    - File: `backend/tests/test_data_source_status_service.py`
    - Use Hypothesis to generate past datetimes; assert `compute_days_since(dt) >= 0` always

  - [x] 2.5 Write property test for `DataSourceStatusService` — response always has four categories
    - **Property 5: API always returns all four source categories**
    - **Validates: Requirements 5.1, 1.1, 1.2, 1.3, 1.4**
    - File: `backend/tests/test_data_source_status_service.py`
    - Use Hypothesis with arbitrary DB state (mocked); assert `socrata_datasets`, `enrichment_sources`, `import_source`, `hubspot_source` are always present

  - [x] 2.6 Write unit tests for `DataSourceStatusService`
    - Test: returns zeroed counts when user has no leads
    - Test: returns null import fields when no completed `ImportJob` exists
    - Test: returns `connected: false` when no `HubSpotConfig` row exists
    - Test: counts are scoped to the requesting user (not other users' leads)
    - File: `backend/tests/test_data_source_status_service.py`
    - _Requirements: 5.2, 5.4, 5.7_

- [x] 3. Implement `DataSourcesController` and register blueprint
  - [x] 3.1 Create `backend/app/controllers/data_sources_controller.py`
    - Define `data_sources_bp` Blueprint at `/api/data-sources`
    - Implement `GET /status` route with `@require_auth` and `@handle_errors`
    - Call `DataSourceStatusService.get_all_statuses(g.user_id)`
    - Serialize response with `DataSourceStatusSchema` (Marshmallow)
    - Return 200 on success, 401 on unauthenticated (via `@require_auth`), 503 on `SQLAlchemyError` (via `@handle_errors`)
    - _Requirements: 5.1, 5.5, 5.6_

  - [x] 3.2 Add `DataSourceStatusSchema` to `backend/app/schemas.py`
    - Add Marshmallow schemas for all four source categories: `SocrataDatasetStatusSchema`, `EnrichmentSourceStatusSchema`, `ImportSourceStatusSchema`, `HubSpotSourceStatusSchema`, and a top-level `DataSourceStatusSchema`
    - _Requirements: 5.1_

  - [x] 3.3 Register blueprint in `backend/app/__init__.py`
    - Import `data_sources_bp` and register with `url_prefix='/api/data-sources'`
    - Re-export `DataSourceStatusService` from `backend/app/services/__init__.py`
    - _Requirements: 5.1_

  - [x] 3.4 Write unit tests for `DataSourcesController`
    - Test: returns 401 when no Bearer token is provided
    - Test: returns 503 when `DataSourceStatusService` raises `SQLAlchemyError`
    - File: `backend/tests/test_data_sources_controller.py`
    - _Requirements: 5.5, 5.6_

- [x] 4. Checkpoint — backend complete
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 5. Add frontend API service method
  - [x] 5.1 Add `dataSourcesService` to `frontend/src/services/api.ts`
    - Add `dataSourcesService.getStatus()` that calls `GET /data-sources/status` and returns `DataSourceStatus`
    - _Requirements: 5.1, 7.5_

- [x] 6. Implement `DataSourcesPanel` component and all sub-components
  - [x] 6.1 Create `frontend/src/components/DataSourcesPanel.tsx` with `DataSourcesSkeleton` and `DataSourcesError`
    - Implement the top-level `DataSourcesPanel` component with `useQuery` configured with `staleTime: 60_000` and `queryKey: ['dataSourceStatus']`
    - Implement `DataSourcesSkeleton` showing one MUI `Skeleton` row per expected source (3 Socrata + N enrichment + 1 import + 1 HubSpot)
    - Implement `DataSourcesError` with error message Alert and "Retry" button that calls `refetch()` with `{ cancelRefetch: true }` to bypass the stale cache
    - Render `DataSourcesSkeleton` while `isLoading`, `DataSourcesError` while `isError`
    - _Requirements: 1.6, 7.1, 7.2, 7.4, 7.5_

  - [x] 6.2 Implement `StatusChip` and `StatusSummaryBanner` sub-components
    - `StatusChip`: MUI `Chip` mapping status strings to color and icon
    - `StatusSummaryBanner`: green banner when all sources healthy (all Socrata `fresh`, all enrichment `is_active`, no failures in last 30 days); amber or red otherwise
    - Include `aria-label` on all status icons with source name and status value (e.g., `aria-label="parcel_universe: stale"`)
    - _Requirements: 6.5, 7.3_

  - [x] 6.3 Implement `SocrataSourceCard` sub-component
    - Display `Refresh_Type` label (`Periodic`), `Dataset_Status` chip, last refreshed timestamp formatted as `MM/DD/YYYY HH:MM` in local timezone
    - Display amber `WarningAmberIcon` with `aria-label="{name}: stale"` when `status === 'stale'`; include days-since-sync count
    - Display red `ErrorIcon` with `aria-label="{name}: {status}"` when `status === 'never_synced'` or `'empty'`
    - Display "No successful sync has occurred" when `last_refreshed_at` is null
    - Display `error_message` from last failed sync when present; fall back to "Sync failed — no details available."
    - Render with reduced opacity and "Inactive" label when `is_active === false`
    - _Requirements: 1.2, 1.5, 2.1, 2.2, 3.1, 3.2, 6.1, 6.2, 6.3_

  - [x] 6.4 Implement `CoverageBar` and `EnrichmentSourceCard` sub-components
    - `CoverageBar`: MUI `LinearProgress` displaying enriched percentage; value clamped to [0, 100]; legend showing "Enriched X | Failed Y | Not Run Z"; empty bar with muted text at 0%, filled green bar at 100%
    - `EnrichmentSourceCard`: display `On Demand` refresh type label, `success_count / total_leads_count` as count and percentage ("0 / 0 (N/A)" when `total === 0`), three labeled fields "Enriched" / "Failed" / "Not Run", last updated timestamp, staleness note when `dataUpdatedAt > 60s` ago, amber warning when failures exist in last 30 days
    - Render with reduced opacity and "Inactive" label when `is_active === false`
    - _Requirements: 1.1, 1.5, 2.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 6.4_

  - [x] 6.5 Implement `ImportSourceCard` and `HubSpotSourceCard` sub-components
    - `ImportSourceCard`: display `Static` refresh type label; when completed job exists, show `completed_at` formatted as `MM/DD/YYYY HH:MM` in local timezone and `rows_imported` count; otherwise display "No imports yet."
    - `HubSpotSourceCard`: display `On Demand` refresh type label; green "Connected" chip when `connected === true`; grey "Not configured" chip otherwise
    - _Requirements: 1.3, 1.4, 2.4, 3.3_

  - [x] 6.6 Wire all sub-components into `DataSourcesPanel` loaded state
    - Render `StatusSummaryBanner`, then sections for "Socrata Datasets" (`SocrataSourceCard × 3`), "Enrichment Sources" (`EnrichmentSourceCard × N`, with "No enrichment sources configured" message when array is empty), "Import Source" (`ImportSourceCard`), and HubSpot (`HubSpotSourceCard`)
    - Display "No data sources are configured" message when all source arrays are empty
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7_

- [x] 7. Write frontend tests for `DataSourcesPanel`
  - [x] 7.1 Write unit tests for `DataSourcesPanel`
    - Test: renders loading skeleton while query is loading
    - Test: renders error state + Retry button when query fails
    - Test: Retry button calls `refetch()` bypassing stale cache
    - Test: stale Socrata dataset shows amber `WarningAmberIcon` with correct `aria-label`
    - Test: never-synced/empty Socrata dataset shows red `ErrorIcon` with correct `aria-label`
    - Test: `total_leads_count === 0` renders "0 / 0 (N/A)" without a percentage
    - Test: green banner shown when all sources are healthy
    - Test: inactive enrichment source renders with reduced opacity and "Inactive" label
    - File: `frontend/src/components/DataSourcesPanel.test.tsx`
    - _Requirements: 1.5, 1.6, 4.1, 6.5, 7.1, 7.2, 7.3, 7.4_

  - [x] 7.2 Write property test for `CoverageBar` — value bounded [0, 100]
    - **Property 1: Coverage percentages bounded [0, 100]**
    - **Validates: Requirements 4.1**
    - File: `frontend/src/components/DataSourcesPanel.test.tsx`
    - Use fast-check to generate arbitrary `(enriched, failed, notRun)` integer triples; assert `LinearProgress` value stays in [0, 100]

  - [x] 7.3 Write property test for `StatusSummaryBanner` — banner color logic
    - **Property 3: Status summary banner is green iff ALL sources healthy**
    - **Validates: Requirements 6.5**
    - File: `frontend/src/components/DataSourcesPanel.test.tsx`
    - Use fast-check to generate arbitrary `DataSourceStatus` payloads; assert green banner iff all Socrata `fresh`, all enrichment `is_active`, no recent failures

- [x] 8. Add route and sidebar entry for Data Sources Panel
  - [x] 8.1 Add route and sidebar link in `frontend/src/App.tsx`
    - Add a route for the Data Sources Panel under the Lead Management section
    - Add a corresponding sidebar navigation entry
    - _Requirements: 1.1_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all backend pytest tests and frontend Vitest tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- No database migrations are required — the feature only reads from existing tables
- Backend uses pytest + Hypothesis for PBT; frontend uses Vitest + fast-check for PBT
- All user-scoped queries must filter by `owner_user_id = g.user_id` (leads) or `user_id = g.user_id` (import jobs) to prevent cross-user data leakage
- The `enrichment_records` count query should use a single `GROUP BY data_source_id, status` to avoid N+1 queries
- `days_since_sync` is always `>= 0`; use `null` when `last_refreshed_at` is null

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "3.1", "3.2"] },
    { "id": 3, "tasks": ["2.6", "3.3", "3.4"] },
    { "id": 4, "tasks": ["6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "6.4", "6.5"] },
    { "id": 6, "tasks": ["6.6"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "8.1"] }
  ]
}
```
