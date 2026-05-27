# Bugfix Requirements Document

## Introduction

The frontend makes excessive, unconditional HTTP requests to the backend database, causing the app to exceed Neon's monthly data transfer quota. The root causes are: (1) two components independently poll the same `/api/hubspot/pipeline/status` endpoint every 8 seconds regardless of whether a pipeline is running, (2) two components independently poll `/api/queues/counts` every 60 seconds, (3) six individual queue components each poll their own queue endpoints every 60 seconds unconditionally, and (4) the webhook sync panel polls two endpoints every 30 seconds unconditionally. Together these generate hundreds of unnecessary database round-trips per hour per open browser tab.

The fix must make all polling **conditional** (only poll when something is actively running or the user is actively viewing the relevant UI), eliminate **duplicate polls** so only one component owns each query, and increase intervals on low-priority background refreshes. No polling behavior that is currently visible to the user should be removed — only made smarter.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN any browser tab is open THEN `PipelineStatusContext` polls `/api/hubspot/pipeline/status` every 8 seconds unconditionally, even when `pipeline_running` is `false` and no import has ever been triggered.

1.2 WHEN the `/import/hubspot` page is mounted THEN `HubSpotImportArea` creates a second, independent `useQuery` for `/api/hubspot/pipeline/status` with `refetchInterval: 8000`, duplicating the poll already owned by `PipelineStatusContext` and doubling the request rate for that endpoint.

1.3 WHEN the `/import/hubspot` page is mounted THEN `WebhookSyncPanel` polls `/api/hubspot/webhook-log` and `/api/hubspot/webhook-summary` every 30 seconds unconditionally, even when no webhook events have been received recently and the user is not actively monitoring the panel.

1.4 WHEN any page that renders `QueueSidebar` is mounted THEN `QueueSidebar` polls `/api/queues/counts` every 60 seconds unconditionally.

1.5 WHEN the root `App` component is mounted THEN `App.tsx` creates a second, independent `useQuery` for `/api/queues/counts` with `refetchInterval: 60_000`, duplicating the poll already owned by `QueueSidebar` and doubling the request rate for that endpoint.

1.6 WHEN any of the six individual queue pages (`TodaysActionQueue`, `PreviouslyWarmQueue`, `FollowUpOverdueQueue`, `NoNextActionQueue`, `NeedsReviewQueue`, `DoNotContactQueue`, `MissingPropertyMatchQueue`) is mounted THEN each component polls its own queue endpoint every 60 seconds unconditionally, even when the user has navigated away or the queue data has not changed.

### Expected Behavior (Correct)

2.1 WHEN `pipeline_running` is `false` THEN `PipelineStatusContext` SHALL pause polling (i.e., `refetchInterval` SHALL return `false`) and only resume polling when `pipeline_running` transitions to `true` or when a pipeline-triggering action is taken.

2.2 WHEN `HubSpotImportArea` is mounted THEN it SHALL consume pipeline status from `PipelineStatusContext` via `usePipelineStatus()` instead of creating its own `useQuery` for `/api/hubspot/pipeline/status`, so that only one request is made per polling cycle regardless of how many components are mounted.

2.3 WHEN `WebhookSyncPanel` is mounted and no webhook events have been received in the last 24 hours THEN the panel SHALL use a longer polling interval (e.g., 5 minutes) instead of 30 seconds; WHEN recent webhook activity is detected THEN the panel SHALL use the shorter 30-second interval.

2.4 WHEN `QueueSidebar` is mounted THEN it SHALL be the single owner of the `['queue-counts']` query with a `refetchInterval` of no less than 5 minutes for background refreshes.

2.5 WHEN `App.tsx` renders the navigation sidebar THEN it SHALL consume queue counts from the shared `['queue-counts']` React Query cache (e.g., via `useQueryClient().getQueryData`) rather than registering a second `useQuery` subscriber with its own `refetchInterval`.

2.6 WHEN a queue page component is mounted THEN it SHALL only poll its own endpoint while the component is actively visible (i.e., the browser tab is focused and the route is active); WHEN the user navigates away from the queue page THEN polling SHALL stop.

### Additional Defect: Oversized List Serialization

1.7 WHEN the `/api/properties/` list endpoint is called THEN `_serialize_property_summary` includes `notes` (Text) and `mailer_history` (JSON) in every row, even though the list UI does not display either field — transferring potentially large per-row payloads unnecessarily.

### Additional Fix: Exclude Bulk Fields from List Serializer

2.7 WHEN `_serialize_property_summary` serializes a lead for a list response THEN it SHALL omit `notes` and `mailer_history`; those fields SHALL only be included in `_serialize_property_detail` (single-record detail view).

2.8 WHEN `_serialize_property_detail` serializes a lead for a detail response THEN it SHALL continue to include `notes` and `mailer_history` so the full record remains accessible on the detail page.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `pipeline_running` is `true` THEN the system SHALL CONTINUE TO poll `/api/hubspot/pipeline/status` at a frequent interval (≤ 10 seconds) so the AppBar spinner and pipeline status UI update in near-real-time.

3.2 WHEN an import run is actively in progress (`activeRunId` is set) THEN `HubSpotImportArea` SHALL CONTINUE TO poll `/api/hubspot/runs` at 5-second intervals to refresh the import history table.

3.3 WHEN the user is viewing the `/import/hubspot` page THEN the pipeline status chips (match counts, interaction counts, signal counts) SHALL CONTINUE TO display up-to-date data.

3.4 WHEN the user is viewing the `WebhookSyncPanel` THEN the webhook log table and 24-hour summary SHALL CONTINUE TO refresh automatically without requiring a manual page reload.

3.5 WHEN the user is viewing any queue page THEN the queue table SHALL CONTINUE TO show live badge counts and row data that refresh periodically.

3.6 WHEN the user is viewing the navigation sidebar THEN the Work Queue badge counts SHALL CONTINUE TO display the current counts for all 7 queues.

3.7 WHEN the user manually clicks the "Refresh" icon in `WebhookSyncPanel` THEN the system SHALL CONTINUE TO immediately refetch the webhook log and summary.

3.8 WHEN a queue action (Log Call, Log Note, Create Task, Suppress, Reactivate) is performed THEN the system SHALL CONTINUE TO immediately invalidate and refetch the relevant queue query so the row disappears or updates without waiting for the next poll cycle.

3.9 WHEN the property list page renders THEN it SHALL CONTINUE TO display all columns currently shown in the table (address, owner name, score, status, etc.) without any visible change — only the two hidden fields (`notes`, `mailer_history`) are removed from the list payload.
