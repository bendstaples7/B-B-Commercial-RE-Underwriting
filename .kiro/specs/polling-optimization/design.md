# Polling Optimization Bugfix Design

## Overview

The frontend generates excessive, unconditional HTTP requests that cause the app to exceed
Neon's monthly data transfer quota. There are four distinct problem areas:

1. **Duplicate pipeline status polling** — `PipelineStatusContext` and `HubSpotImportArea`
   each register an independent `useQuery` for `/api/hubspot/pipeline/status` at 8-second
   intervals, doubling the request rate. Neither pauses when `pipeline_running` is `false`.

2. **Duplicate queue counts polling** — `QueueSidebar` and `App.tsx` each register an
   independent `useQuery` for `/api/queues/counts` at 60-second intervals, doubling the
   request rate.

3. **Unconditional queue page polling** — Seven individual queue components each poll their
   own endpoint every 60 seconds regardless of whether the user is viewing that page or the
   browser tab is focused.

4. **Unconditional webhook polling** — `WebhookSyncPanel` polls two endpoints every 30
   seconds regardless of recent webhook activity.

5. **Oversized list serialization** — `_serialize_property_summary` includes `notes` (Text)
   and `mailer_history` (JSON) in every row of every list response, even though the list UI
   never displays those fields.

The fix strategy is: (a) make polling conditional on active state, (b) eliminate duplicate
subscribers so exactly one component owns each query, and (c) strip bulk fields from the
list serializer. No user-visible polling behavior is removed — only made smarter.

---

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a component registers a
  `useQuery` with an unconditional `refetchInterval`, or a second component registers a
  duplicate subscriber for the same query key with its own `refetchInterval`.
- **Property (P)**: The desired behavior — polling only occurs when the relevant data is
  actively needed (pipeline running, user viewing the page, recent webhook activity), and
  each query key has exactly one polling owner.
- **Preservation**: All user-visible refresh behavior that must remain unchanged: the
  AppBar spinner updates in near-real-time when a pipeline is running, queue tables refresh
  while the user is viewing them, webhook log refreshes while the panel is open, and badge
  counts remain current in the sidebar.
- **isBugCondition**: Pseudocode function that identifies inputs (component mount events /
  query registrations) that trigger the bug.
- **PipelineStatusContext**: The context provider in
  `frontend/src/context/PipelineStatusContext.tsx` that owns the global pipeline status poll.
- **HubSpotImportArea**: The component in `frontend/src/components/HubSpotImportArea.tsx`
  that currently registers a duplicate pipeline status poll.
- **WebhookSyncPanel**: The component in `frontend/src/components/WebhookSyncPanel.tsx`
  that polls two webhook endpoints unconditionally every 30 seconds.
- **QueueSidebar**: The component in `frontend/src/components/QueueSidebar.tsx` that owns
  the `['queue-counts']` query.
- **App.tsx**: The root component that currently registers a duplicate `['queue-counts']`
  subscriber with its own `refetchInterval: 60_000`.
- **Queue page components**: `TodaysActionQueue`, `PreviouslyWarmQueue`,
  `FollowUpOverdueQueue`, `NoNextActionQueue`, `NeedsReviewQueue`, `DoNotContactQueue`,
  `MissingPropertyMatchQueue` — each polls its own endpoint unconditionally.
- **`_serialize_property_summary`**: The Python function in
  `backend/app/controllers/property_controller.py` that serializes leads for list responses.
- **`_serialize_property_detail`**: The Python function in the same file that serializes a
  single lead for the detail view.

---

## Bug Details

### Bug Condition

The bug manifests in five distinct patterns, all sharing the same root: a `useQuery`
subscriber registers a `refetchInterval` that fires unconditionally, or a second subscriber
registers the same query key with its own independent `refetchInterval`.

**Formal Specification:**

```
FUNCTION isBugCondition(registration)
  INPUT: registration — a useQuery call with { queryKey, refetchInterval }
  OUTPUT: boolean

  // Pattern A: unconditional polling when data is not actively needed
  IF registration.refetchInterval IS a fixed number (not a function)
     AND registration.queryKey IN [
       ['hubspot', 'pipeline', 'status', 'global'],  // PipelineStatusContext
       ['hubspot', 'pipeline', 'status'],             // HubSpotImportArea duplicate
       ['hubspot', 'webhook-log', ...],               // WebhookSyncPanel
       ['hubspot', 'webhook-summary'],                // WebhookSyncPanel
       ['queue-todays-action'],                       // TodaysActionQueue
       ['queue-previously-warm'],                     // PreviouslyWarmQueue
       ['queue-follow-up-overdue'],                   // FollowUpOverdueQueue
       ['queue-no-next-action'],                      // NoNextActionQueue
       ['queue-needs-review'],                        // NeedsReviewQueue
       ['queue-do-not-contact', ...],                 // DoNotContactQueue
       ['queue-missing-property-match']               // MissingPropertyMatchQueue
     ]
  THEN RETURN true

  // Pattern B: duplicate subscriber — second component registers same key with refetchInterval
  IF registration.queryKey IN [
       ['hubspot', 'pipeline', 'status'],   // HubSpotImportArea duplicates PipelineStatusContext
       ['queue-counts']                     // App.tsx duplicates QueueSidebar
     ]
     AND anotherSubscriberWithRefetchInterval(registration.queryKey) EXISTS
  THEN RETURN true

  // Pattern C: backend list serializer includes bulk fields
  IF registration IS _serialize_property_summary
     AND 'notes' IN registration.output
     AND 'mailer_history' IN registration.output
  THEN RETURN true

  RETURN false
END FUNCTION
```

### Examples

- **Pattern A — PipelineStatusContext**: `refetchInterval: 8000` fires every 8 seconds
  even when `pipeline_running` is `false` and no import has ever been triggered. With a
  browser tab open 8 hours/day, this generates ~3,600 requests/day to a Neon-backed endpoint
  for zero user benefit.

- **Pattern B — HubSpotImportArea duplicate**: When the `/import/hubspot` page is mounted,
  a second `useQuery` with `queryKey: ['hubspot', 'pipeline', 'status']` and
  `refetchInterval: 8000` fires independently of `PipelineStatusContext`, doubling the
  request rate for that endpoint.

- **Pattern B — App.tsx duplicate**: `App.tsx` registers `useQuery({ queryKey: ['queue-counts'], refetchInterval: 60_000 })` independently of `QueueSidebar`, which registers
  the same key with the same interval. React Query deduplicates the fetch but both
  subscribers keep the interval alive even when `QueueSidebar` is not rendered.

- **Pattern A — Queue pages**: `TodaysActionQueue` uses `refetchInterval: 60_000`
  unconditionally. When the user navigates to `/properties`, the component unmounts but
  the interval was already firing; if the component is kept alive by React Router's
  rendering strategy, it continues polling a queue the user is not viewing.

- **Pattern C — List serializer**: A list response for 500 leads includes `notes` (up to
  several KB of free text per lead) and `mailer_history` (JSON object) in every row.
  Neither field is displayed in the list table. This adds potentially hundreds of KB of
  unnecessary payload per page load.

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- When `pipeline_running` is `true`, the AppBar spinner and pipeline status chips SHALL
  continue to update in near-real-time (poll interval ≤ 10 seconds).
- When an import run is active (`activeRunId` is set), `HubSpotImportArea` SHALL continue
  to poll `/api/hubspot/runs` at 5-second intervals via its existing `refetchInterval:
  activeRunId ? 5000 : false` pattern — this is already conditional and must not change.
- When the user is viewing `WebhookSyncPanel`, the webhook log table and 24-hour summary
  SHALL continue to refresh automatically.
- When the user manually clicks the Refresh icon in `WebhookSyncPanel`, the system SHALL
  immediately refetch both webhook queries.
- When the user is viewing any queue page, the queue table SHALL continue to show data that
  refreshes periodically.
- When the user is viewing the navigation sidebar, the Work Queue badge counts SHALL
  continue to display current counts for all 7 queues.
- When a queue action (Log Call, Log Note, Create Task, Suppress, Reactivate) is performed,
  the system SHALL immediately invalidate and refetch the relevant queue query.
- The property list page SHALL continue to display all currently visible columns without
  any visible change — only `notes` and `mailer_history` are removed from the list payload.
- `_serialize_property_detail` SHALL continue to include `notes` and `mailer_history` so
  the full record remains accessible on the detail page.

**Scope:**
All inputs that do NOT match the bug condition should be completely unaffected by this fix.
This includes:
- The `refetchInterval: activeRunId ? 5000 : false` pattern in `HubSpotImportArea` for
  `/api/hubspot/runs` — already conditional, must not be touched.
- The `refetchInterval: (query) => data?.loading === true ? 5000 : false` pattern in
  `AnalysisRoute` — already conditional, must not be touched.
- All mutation `onSuccess` invalidations — must remain intact.
- The `_serialize_property_detail` function — must not be modified.

---

## Hypothesized Root Cause

Based on code inspection, the root causes are confirmed (not hypothesized):

1. **`PipelineStatusContext` — hardcoded interval**: `refetchInterval: 8000` is a fixed
   number, not a function. React Query fires it unconditionally regardless of the value of
   `pipeline_running` in the returned data. The fix is to change it to a function:
   `refetchInterval: (query) => query.state.data?.pipeline_running ? 8000 : false`.

2. **`HubSpotImportArea` — duplicate subscriber**: The component registers its own
   `useQuery` for `['hubspot', 'pipeline', 'status']` with `refetchInterval: 8000` instead
   of consuming the value already provided by `PipelineStatusContext` via `usePipelineStatus()`.
   The fix is to remove the `useQuery` call and replace it with `usePipelineStatus()`.

3. **`App.tsx` — duplicate subscriber**: The component registers `useQuery({ queryKey: ['queue-counts'], refetchInterval: 60_000 })` to populate nav badge counts. `QueueSidebar`
   already owns this query. The fix is to replace the `useQuery` call in `App.tsx` with
   `useQueryClient().getQueryData(['queue-counts'])` (passive read, no polling).

4. **`QueueSidebar` — interval too short**: The 60-second interval is unnecessarily
   aggressive for background badge counts. The fix is to increase it to 5 minutes
   (`refetchInterval: 5 * 60_000`) since the sidebar is always mounted and owns the query.

5. **Queue page components — unconditional interval**: Each queue component uses
   `refetchInterval: 60_000` as a fixed number. The fix is to gate polling on
   `document.visibilityState === 'visible'` using React Query's built-in
   `refetchOnWindowFocus: true` combined with `refetchIntervalInBackground: false`, which
   stops the interval when the tab is hidden or the user navigates away.

6. **`WebhookSyncPanel` — unconditional interval**: Both webhook queries use
   `refetchInterval: 30_000` as a fixed number. The fix is to make the interval conditional
   on recent webhook activity: use 30 seconds when `summary?.processed_count > 0` in the
   last 24 hours, and 5 minutes otherwise.

7. **`_serialize_property_summary` — bulk fields included**: The function explicitly
   includes `'notes': lead.notes` and `'mailer_history': lead.mailer_history` in the
   returned dict. The fix is to remove those two keys from the function.

---

## Correctness Properties

Property 1: Bug Condition — Conditional Polling

_For any_ component registration where `isBugCondition(registration)` returns `true`, the
fixed code SHALL ensure that `refetchInterval` returns `false` (no polling) when the
relevant data is not actively needed — specifically: when `pipeline_running` is `false` for
pipeline status queries; when the browser tab is hidden or the component is not the active
route for queue page queries; when no webhook activity has occurred in the last 24 hours for
webhook queries at the slow interval; and when the list serializer is called, `notes` and
`mailer_history` SHALL be absent from the response payload.

**Validates: Requirements 2.1, 2.3, 2.4, 2.6, 2.7**

Property 2: Preservation — Active Polling Continues

_For any_ component registration where `isBugCondition(registration)` returns `false` (i.e.,
the polling is already conditional or the component is the legitimate single owner), the
fixed code SHALL produce exactly the same polling behavior as the original code — preserving
near-real-time updates when `pipeline_running` is `true`, periodic queue table refreshes
while the user is viewing a queue page, webhook log refreshes while the panel is open, and
sidebar badge count updates.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

Property 3: Preservation — Single Query Owner

_For any_ query key that previously had two subscribers with independent `refetchInterval`
values (`['hubspot', 'pipeline', 'status']` and `['queue-counts']`), the fixed code SHALL
ensure exactly one component registers a `refetchInterval` for that key, and the other
component reads from the shared React Query cache without registering its own polling
interval.

**Validates: Requirements 2.2, 2.5**

---

## Fix Implementation

### Changes Required

#### File: `frontend/src/context/PipelineStatusContext.tsx`

**Function**: `PipelineStatusProvider`

**Specific Changes**:
1. **Conditional interval**: Change `refetchInterval: 8000` to a function that returns
   `false` when `pipeline_running` is `false`:
   ```ts
   refetchInterval: (query) => {
     const data = query.state.data as PipelineStatus | undefined
     return data?.pipeline_running ? 8000 : false
   },
   ```
   This means: on first load, one request fires to get the initial state. If
   `pipeline_running` is `false`, polling stops. When a pipeline-triggering action
   invalidates the query, the next fetch resumes and polling restarts if running.

2. **Resume on invalidation**: No additional change needed — `queryClient.invalidateQueries`
   in `runPipelineMutation.onSuccess` already triggers a refetch, which will restart the
   interval if the new data shows `pipeline_running: true`.

---

#### File: `frontend/src/components/HubSpotImportArea.tsx`

**Specific Changes**:
1. **Remove duplicate pipeline status query**: Delete the `useQuery` block for
   `['hubspot', 'pipeline', 'status']` with `refetchInterval: 8000`.

2. **Consume from context**: Replace the removed query with:
   ```ts
   import { usePipelineStatus } from '@/context/PipelineStatusContext'
   // ...
   const pipelineStatus = usePipelineStatus()
   ```
   The `pipelineStatus` variable is already used in the JSX for the "Run Pipeline Now"
   button disabled state and the pipeline status chips — no other changes needed.

---

#### File: `frontend/src/App.tsx`

**Specific Changes**:
1. **Remove duplicate queue counts query**: Delete the `useQuery<QueueCounts>` block with
   `queryKey: ['queue-counts']` and `refetchInterval: 60_000`.

2. **Read from shared cache**: Replace with a passive cache read:
   ```ts
   import { useQueryClient } from '@tanstack/react-query'
   // ...
   const queryClient = useQueryClient()  // already imported
   const queueCounts = queryClient.getQueryData<QueueCounts>(['queue-counts'])
   ```
   `QueueSidebar` is rendered on every page that shows the nav, so the cache will always
   be populated by the time `App.tsx` needs to render badge counts.

---

#### File: `frontend/src/components/QueueSidebar.tsx`

**Specific Changes**:
1. **Increase interval**: Change `refetchInterval: 60_000` to `refetchInterval: 5 * 60_000`
   (5 minutes). The sidebar is always mounted when the nav is visible, so it remains the
   single owner of this query. 5 minutes is sufficient for badge counts that are also
   immediately invalidated by queue actions.

2. **Disable background refetch**: Add `refetchIntervalInBackground: false` to stop the
   interval when the browser tab is hidden.

---

#### File: `frontend/src/components/WebhookSyncPanel.tsx`

**Specific Changes**:
1. **Conditional log interval**: Change `refetchInterval: 30_000` on the webhook-log query
   to a function:
   ```ts
   refetchInterval: (query) => {
     // Use short interval only when there has been recent activity
     const summaryData = queryClient.getQueryData<WebhookSummary>(['hubspot', 'webhook-summary'])
     return (summaryData?.processed_count ?? 0) > 0 ? 30_000 : 5 * 60_000
   },
   ```

2. **Conditional summary interval**: Apply the same logic to the webhook-summary query:
   ```ts
   refetchInterval: (query) => {
     const data = query.state.data as WebhookSummary | undefined
     return (data?.processed_count ?? 0) > 0 ? 30_000 : 5 * 60_000
   },
   ```

3. **Disable background refetch**: Add `refetchIntervalInBackground: false` to both queries.

---

#### Files: All seven queue page components

`TodaysActionQueue.tsx`, `PreviouslyWarmQueue.tsx`, `FollowUpOverdueQueue.tsx`,
`NoNextActionQueue.tsx`, `NeedsReviewQueue.tsx`, `DoNotContactQueue.tsx`,
`MissingPropertyMatchQueue.tsx`

**Specific Changes** (identical pattern in each):
1. **Disable background refetch**: Add `refetchIntervalInBackground: false` to the
   `useQuery` call. React Query will automatically pause the interval when the browser tab
   is hidden and resume when it becomes visible again.
2. **Keep `refetchInterval: 60_000`**: The 60-second interval is appropriate while the user
   is actively viewing the queue. With `refetchIntervalInBackground: false`, it only fires
   when the tab is focused.

---

#### File: `backend/app/controllers/property_controller.py`

**Function**: `_serialize_property_summary`

**Specific Changes**:
1. **Remove `notes`**: Delete the line `'notes': lead.notes,` from the returned dict.
2. **Remove `mailer_history`**: Delete the line `'mailer_history': lead.mailer_history,`
   from the returned dict.

`_serialize_property_detail` is not modified — it continues to include both fields.

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate the bug on unfixed code, then verify the fix works correctly and preserves
existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix.
Confirm the root cause analysis. If refuted, re-hypothesize.

**Test Plan**: Write tests that mount the affected components and assert on the
`refetchInterval` values passed to `useQuery`, or mock the query client and count how many
times the fetch function is called over a simulated time window. Run these tests on the
UNFIXED code to observe failures.

**Test Cases**:
1. **PipelineStatusContext unconditional poll**: Mount `PipelineStatusProvider` with a mock
   that returns `{ pipeline_running: false }`. Advance fake timers by 24 seconds. Assert
   that the fetch function was called 3 times (once per 8s). On unfixed code: 3 calls
   observed. On fixed code: 1 call (initial fetch only, then interval stops).

2. **HubSpotImportArea duplicate poll**: Mount `HubSpotImportArea` inside
   `PipelineStatusProvider`. Assert that only one network request is made to
   `/api/hubspot/pipeline/status` per polling cycle. On unfixed code: 2 requests per cycle.
   On fixed code: 1 request per cycle.

3. **App.tsx duplicate queue counts poll**: Mount `App` with `QueueSidebar` rendered.
   Assert that `queueService.getCounts` is called at most once per polling cycle. On unfixed
   code: 2 calls per cycle. On fixed code: 1 call per cycle.

4. **Queue page background poll**: Mount `TodaysActionQueue`, simulate tab hidden
   (`document.visibilityState = 'hidden'`), advance timers by 120 seconds. Assert that
   `queueService.getTodaysAction` is not called during the hidden period. On unfixed code:
   2 calls observed. On fixed code: 0 calls while hidden.

5. **List serializer bulk fields**: Call `_serialize_property_summary` on a lead with
   non-null `notes` and `mailer_history`. Assert that neither key appears in the result.
   On unfixed code: both keys present. On fixed code: both keys absent.

**Expected Counterexamples**:
- Fetch functions called more times than expected when `pipeline_running` is `false`
- Two distinct network requests to the same endpoint per polling cycle
- Queue fetch functions called while the browser tab is hidden

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed code produces
the expected behavior.

**Pseudocode:**
```
FOR ALL registration WHERE isBugCondition(registration) DO
  result := fixedComponent.refetchInterval(currentState)
  ASSERT result = false  // polling paused when not needed
  OR
  ASSERT result = slowInterval  // 5 minutes for low-priority background
END FOR

FOR ALL listRequest DO
  result := _serialize_property_summary_fixed(lead)
  ASSERT 'notes' NOT IN result
  ASSERT 'mailer_history' NOT IN result
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed code
produces the same behavior as the original.

**Pseudocode:**
```
FOR ALL registration WHERE NOT isBugCondition(registration) DO
  ASSERT fixedComponent.pollingBehavior = originalComponent.pollingBehavior
END FOR

FOR ALL detailRequest DO
  result := _serialize_property_detail(lead)
  ASSERT 'notes' IN result
  ASSERT 'mailer_history' IN result
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking
because it generates many combinations of component state (pipeline_running true/false,
tab visible/hidden, webhook activity counts) and verifies that polling behavior is correct
across all of them.

**Test Cases**:
1. **Pipeline running — polling continues**: When `pipeline_running` transitions to `true`,
   assert that `PipelineStatusContext` resumes polling at ≤ 10-second intervals.
2. **Queue action invalidation**: After a Log Call action, assert that the queue query is
   immediately refetched (not waiting for the next 60-second interval).
3. **Webhook manual refresh**: Clicking the Refresh icon in `WebhookSyncPanel` must
   immediately refetch both webhook queries regardless of the current interval.
4. **Detail serializer unchanged**: `_serialize_property_detail` must continue to include
   `notes` and `mailer_history` after the list serializer change.
5. **Badge counts still visible**: After removing the `useQuery` from `App.tsx`, badge
   counts in the nav must still render correctly using the shared cache.

### Unit Tests

- Test `PipelineStatusContext` `refetchInterval` function returns `false` when
  `pipeline_running` is `false` and returns `8000` when `pipeline_running` is `true`.
- Test `HubSpotImportArea` does not register a `useQuery` for pipeline status (uses context
  instead).
- Test `_serialize_property_summary` does not include `notes` or `mailer_history` keys.
- Test `_serialize_property_detail` continues to include `notes` and `mailer_history` keys.
- Test each queue component has `refetchIntervalInBackground: false` in its query options.
- Test `QueueSidebar` uses `refetchInterval: 5 * 60_000`.

### Property-Based Tests

- Generate random `PipelineStatus` objects with `pipeline_running` as a boolean. For any
  object where `pipeline_running` is `false`, assert that the `refetchInterval` function
  returns `false`. For any object where `pipeline_running` is `true`, assert it returns a
  number ≤ 10000.
- Generate random `WebhookSummary` objects with varying `processed_count` values. Assert
  that the `refetchInterval` function returns 30000 when `processed_count > 0` and
  `5 * 60_000` when `processed_count === 0`.
- Generate random lead objects with varying `notes` and `mailer_history` values. Assert
  that `_serialize_property_summary` never includes either field, and
  `_serialize_property_detail` always includes both fields.

### Integration Tests

- Mount the full `HubSpotImportArea` page and verify that exactly one request is made to
  `/api/hubspot/pipeline/status` per polling cycle when `pipeline_running` is `true`.
- Mount `App` with `QueueSidebar` and verify that exactly one request is made to
  `/api/queues/counts` per polling cycle.
- Call `GET /api/properties/` and verify the response does not include `notes` or
  `mailer_history` in any row.
- Call `GET /api/properties/:id` and verify the response includes `notes` and
  `mailer_history`.
