# Implementation Plan

## Overview

This plan follows the exploratory bugfix workflow: write tests before the fix to understand the bug (Bug Condition), write tests for non-buggy behavior (Preservation), implement the fix, then validate. The fix addresses five distinct patterns of excessive unconditional HTTP polling and oversized list serialization.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"] },
    { "wave": 4, "tasks": ["3.8", "3.9"] },
    { "wave": 5, "tasks": ["4"] }
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Unconditional and Duplicate Polling
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists across all five patterns
  - **Scoped PBT Approach**: Scope each sub-property to the concrete failing case(s) for reproducibility
  - **Sub-property A — PipelineStatusContext unconditional poll**: Mount `PipelineStatusProvider` with a mock returning `{ pipeline_running: false }`. Advance fake timers by 24 seconds. Assert fetch is called exactly 1 time (initial fetch only). On unfixed code: 3 calls observed (once per 8s). Write as a property: for any `PipelineStatus` where `pipeline_running` is `false`, the `refetchInterval` function must return `false`.
  - **Sub-property B — HubSpotImportArea duplicate poll**: Mount `HubSpotImportArea` inside `PipelineStatusProvider`. Assert that only one network request is made to `/api/hubspot/pipeline/status` per polling cycle. On unfixed code: 2 requests per cycle observed.
  - **Sub-property C — App.tsx duplicate queue counts poll**: Mount `App` with `QueueSidebar` rendered. Assert `queueService.getCounts` is called at most once per polling cycle. On unfixed code: 2 calls per cycle observed.
  - **Sub-property D — Queue page background poll**: Mount `TodaysActionQueue`, simulate tab hidden (`document.visibilityState = 'hidden'`), advance timers 120 seconds. Assert `queueService.getTodaysAction` is not called during the hidden period. On unfixed code: 2 calls observed.
  - **Sub-property E — List serializer bulk fields**: Call `_serialize_property_summary` on a lead with non-null `notes` and `mailer_history`. Assert neither key appears in the result. On unfixed code: both keys present.
  - Run all sub-properties on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found (e.g., "PipelineStatusContext fires 3 times in 24s when pipeline_running=false", "two requests to /api/hubspot/pipeline/status per cycle", "notes key present in list serializer output")
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Active Polling and Single-Owner Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology — run UNFIXED code with non-buggy inputs and record actual outputs before writing assertions
  - **Observe on UNFIXED code**:
    - `PipelineStatusContext` with `pipeline_running: true` → polling fires at ~8s intervals (observe call count over 24s)
    - `HubSpotImportArea` with `activeRunId` set → `/api/hubspot/runs` polled at 5s intervals (already conditional, must not change)
    - `WebhookSyncPanel` with `processed_count > 0` → both webhook queries polled at 30s intervals
    - `TodaysActionQueue` with tab visible → queue endpoint polled at 60s intervals
    - `QueueSidebar` rendered → badge counts visible and populated
    - `_serialize_property_detail` on a lead with notes and mailer_history → both fields present in output
  - **Write property-based tests capturing observed behavior**:
    - For any `PipelineStatus` where `pipeline_running` is `true`, assert `refetchInterval` returns a number ≤ 10000 (from Preservation Requirements 3.1)
    - For any `WebhookSummary` where `processed_count > 0`, assert `refetchInterval` returns 30000 (from Preservation Requirements 3.4)
    - For any `WebhookSummary` where `processed_count === 0`, assert `refetchInterval` returns `5 * 60_000`
    - For any lead object with non-null `notes` and `mailer_history`, assert `_serialize_property_detail` includes both fields (from Preservation Requirements 3.9 / 2.8)
    - Assert `QueueSidebar` registers exactly one `useQuery` for `['queue-counts']` with `refetchInterval: 5 * 60_000` (single owner, from Preservation Requirements 3.6)
    - Assert queue action invalidations (`onSuccess` callbacks) remain intact — mutation success triggers immediate refetch
  - Run all preservation tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [x] 3. Fix for excessive unconditional and duplicate HTTP polling

  - [x] 3.1 Make `PipelineStatusContext` polling conditional on `pipeline_running`
    - In `frontend/src/context/PipelineStatusContext.tsx`, change `refetchInterval: 8000` to a function: `refetchInterval: (query) => { const data = query.state.data as PipelineStatus | undefined; return data?.pipeline_running ? 8000 : false }`
    - No change needed to `queryClient.invalidateQueries` in `runPipelineMutation.onSuccess` — invalidation already triggers a refetch that restarts the interval if `pipeline_running` becomes `true`
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey = ['hubspot', 'pipeline', 'status', 'global'] AND refetchInterval is a fixed number_
    - _Expected_Behavior: refetchInterval returns false when pipeline_running is false; returns 8000 when pipeline_running is true_
    - _Preservation: When pipeline_running is true, polling continues at ≤ 10s so AppBar spinner and status chips update in near-real-time (Requirement 3.1, 3.3)_
    - _Requirements: 2.1, 3.1, 3.3_

  - [x] 3.2 Remove duplicate pipeline status poll from `HubSpotImportArea`
    - In `frontend/src/components/HubSpotImportArea.tsx`, delete the `useQuery` block for `['hubspot', 'pipeline', 'status']` with `refetchInterval: 8000`
    - Add `import { usePipelineStatus } from '@/context/PipelineStatusContext'` if not already imported
    - Replace the removed query with `const pipelineStatus = usePipelineStatus()` — the returned value is already used in JSX for the "Run Pipeline Now" button disabled state and pipeline status chips; no other JSX changes needed
    - Do NOT touch the existing `refetchInterval: activeRunId ? 5000 : false` pattern for `/api/hubspot/runs` — this is already conditional and must remain unchanged
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey = ['hubspot', 'pipeline', 'status'] AND anotherSubscriberWithRefetchInterval exists (Pattern B duplicate)_
    - _Expected_Behavior: Only one request per polling cycle to /api/hubspot/pipeline/status regardless of how many components are mounted_
    - _Preservation: HubSpotImportArea continues to display pipeline status chips with up-to-date data via context (Requirement 3.3); activeRunId polling for /api/hubspot/runs is untouched (Requirement 3.2)_
    - _Requirements: 2.2, 3.2, 3.3_

  - [x] 3.3 Remove duplicate queue counts poll from `App.tsx`
    - In `frontend/src/App.tsx`, delete the `useQuery<QueueCounts>` block with `queryKey: ['queue-counts']` and `refetchInterval: 60_000`
    - Replace with a passive cache read: `const queueCounts = queryClient.getQueryData<QueueCounts>(['queue-counts'])` — `useQueryClient` is already imported; `QueueSidebar` is rendered on every page that shows the nav so the cache will always be populated
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey = ['queue-counts'] AND anotherSubscriberWithRefetchInterval exists in QueueSidebar (Pattern B duplicate)_
    - _Expected_Behavior: App.tsx reads from shared cache with no independent refetchInterval; exactly one polling owner for ['queue-counts']_
    - _Preservation: Badge counts in the nav continue to render correctly using the shared cache populated by QueueSidebar (Requirement 3.6)_
    - _Requirements: 2.5, 3.6_

  - [x] 3.4 Increase `QueueSidebar` poll interval and disable background refetch
    - In `frontend/src/components/QueueSidebar.tsx`, change `refetchInterval: 60_000` to `refetchInterval: 5 * 60_000`
    - Add `refetchIntervalInBackground: false` to the `useQuery` options to stop the interval when the browser tab is hidden
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey = ['queue-counts'] AND refetchInterval is a fixed number at 60s (Pattern A — unnecessarily aggressive for background badge counts)_
    - _Expected_Behavior: QueueSidebar is the single owner of ['queue-counts'] with a 5-minute background refresh interval; interval pauses when tab is hidden_
    - _Preservation: Badge counts remain current in the sidebar; queue action invalidations immediately refetch regardless of interval (Requirement 3.6, 3.8)_
    - _Requirements: 2.4, 3.6, 3.8_

  - [x] 3.5 Add `refetchIntervalInBackground: false` to all seven queue page components
    - In each of the following files, add `refetchIntervalInBackground: false` to the `useQuery` call — keep `refetchInterval: 60_000` unchanged:
      - `frontend/src/components/TodaysActionQueue.tsx`
      - `frontend/src/components/PreviouslyWarmQueue.tsx`
      - `frontend/src/components/FollowUpOverdueQueue.tsx`
      - `frontend/src/components/NoNextActionQueue.tsx`
      - `frontend/src/components/NeedsReviewQueue.tsx`
      - `frontend/src/components/DoNotContactQueue.tsx`
      - `frontend/src/components/MissingPropertyMatchQueue.tsx`
    - React Query will automatically pause the 60-second interval when the browser tab is hidden and resume when it becomes visible again
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey IN queue page keys AND refetchInterval is a fixed number with no background guard (Pattern A)_
    - _Expected_Behavior: Queue polling fires only while the browser tab is focused; pauses when tab is hidden or user navigates away_
    - _Preservation: When the user is viewing any queue page, the table continues to refresh every 60 seconds (Requirement 3.5); queue action invalidations remain intact (Requirement 3.8)_
    - _Requirements: 2.6, 3.5, 3.8_

  - [x] 3.6 Make `WebhookSyncPanel` polling conditional on recent webhook activity
    - In `frontend/src/components/WebhookSyncPanel.tsx`, change the webhook-log query's `refetchInterval: 30_000` to a function: `refetchInterval: (query) => { const summaryData = queryClient.getQueryData<WebhookSummary>(['hubspot', 'webhook-summary']); return (summaryData?.processed_count ?? 0) > 0 ? 30_000 : 5 * 60_000 }`
    - Change the webhook-summary query's `refetchInterval: 30_000` to a function: `refetchInterval: (query) => { const data = query.state.data as WebhookSummary | undefined; return (data?.processed_count ?? 0) > 0 ? 30_000 : 5 * 60_000 }`
    - Add `refetchIntervalInBackground: false` to both queries
    - Do NOT change the manual Refresh icon handler — `queryClient.invalidateQueries` must remain intact
    - _Bug_Condition: isBugCondition(registration) where registration.queryKey IN ['hubspot', 'webhook-log', ...] OR ['hubspot', 'webhook-summary'] AND refetchInterval is a fixed number (Pattern A)_
    - _Expected_Behavior: Webhook queries use 30s interval when processed_count > 0; use 5-minute interval when no recent activity; pause when tab is hidden_
    - _Preservation: When user is viewing WebhookSyncPanel, log table and summary continue to refresh automatically (Requirement 3.4); manual Refresh icon immediately refetches both queries (Requirement 3.7)_
    - _Requirements: 2.3, 3.4, 3.7_

  - [x] 3.7 Remove `notes` and `mailer_history` from `_serialize_property_summary`
    - In `backend/app/controllers/property_controller.py`, in the `_serialize_property_summary` function, delete the line `'notes': lead.notes,`
    - Delete the line `'mailer_history': lead.mailer_history,`
    - Do NOT modify `_serialize_property_detail` — it must continue to include both fields
    - _Bug_Condition: isBugCondition(registration) where registration IS _serialize_property_summary AND 'notes' IN output AND 'mailer_history' IN output (Pattern C)_
    - _Expected_Behavior: _serialize_property_summary never includes notes or mailer_history keys in its output_
    - _Preservation: _serialize_property_detail continues to include notes and mailer_history for the detail page (Requirement 2.8, 3.9); all list table columns continue to display correctly (Requirement 3.9)_
    - _Requirements: 2.7, 2.8, 3.9_

  - [x] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Unconditional and Duplicate Polling Eliminated
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior across all five patterns
    - When these tests pass, it confirms the expected behavior is satisfied for all bug condition patterns
    - Run all sub-properties (A through E) from task 1 on the FIXED code
    - **EXPECTED OUTCOME**: All sub-properties PASS (confirms all bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - Active Polling and Single-Owner Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all preservation property tests from task 2 on the FIXED code
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions)
    - Confirm pipeline-running polling, import run polling, webhook active polling, queue page polling, badge counts, queue action invalidations, and detail serializer all behave identically to the unfixed baseline
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run `cd frontend && npm test` and confirm all frontend tests pass
  - Run `cd backend && pytest` and confirm all backend tests pass
  - Verify no TypeScript errors: `cd frontend && npm run build`
  - Ensure all tests pass; ask the user if questions arise

## Notes

- Tasks 1 and 2 are standalone property-based tests that must be written and run on UNFIXED code before any implementation begins.
- Task 1 (Bug Condition) is expected to FAIL on unfixed code — this is correct and confirms the bugs exist.
- Task 2 (Preservation) is expected to PASS on unfixed code — this establishes the behavioral baseline.
- Tasks 3.8 and 3.9 re-run the same tests from tasks 1 and 2 respectively; do not write new tests.
- The `refetchInterval: activeRunId ? 5000 : false` pattern in `HubSpotImportArea` for `/api/hubspot/runs` is already conditional and must NOT be touched (Requirement 3.2).
- The `_serialize_property_detail` function must NOT be modified — only `_serialize_property_summary` changes (Requirement 2.8).
- Frontend tests: `cd frontend && npm test` (Vitest + React Testing Library)
- Backend tests: `cd backend && pytest` (pytest + Hypothesis for property-based tests)
