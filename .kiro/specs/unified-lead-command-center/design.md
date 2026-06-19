# Design Document

## Unified Lead Command Center

---

## Overview

The Unified Lead Command Center replaces two diverging detail views — `PropertyDetailPage` (at `/properties/:leadId`) and `LeadCommandCenter` (at `/leads/:id/command-center`) — with a single canonical component served at `/leads/:id`.

The current split forces agents to switch between contexts depending on how they navigate. The Properties list sends them to a tabbed data view; the Work Queues send them to a CRM workflow view. Both have partially overlapping features but neither is complete. The unified page merges the richest capabilities of each: the full tabbed property data from `PropertyDetailPage` and the CRM workflow tools (queue context banners, status management, recommended actions, tasks, timeline) from `LeadCommandCenter`.

Every entry point in the application — the Properties list row click, all Work Queue row/icon clicks, and the Global Search Bar — will navigate to `/leads/:id` after this feature ships. Legacy routes redirect to the canonical route so existing bookmarks and external links continue to work.

---

## Architecture

### High-Level Component Tree

```
App.tsx (React Router)
├── Route "/leads/:id"         → UnifiedLeadCommandCenter
├── Route "/properties/:leadId" → <Navigate to="/leads/:leadId" replace />
└── Route "/leads/:id/command-center" → <Navigate to="/leads/:id" replace />
```

### Data Loading Architecture

The page makes exactly two React Query fetches on mount:

1. **`commandCenter` query** — `GET /api/leads/:id/command-center` — returns `CommandCenterPayload`. Shared by: sticky header, queue context banners, status selector, recommended action panel, tasks panel, activity panel (initial timeline entries), and property sidebar.

2. **`lead` query** — `GET /api/leads/:id` — returns `PropertyDetail`. Shared by: all six Tab_Panel tabs (Info, Score, Enrichment, Marketing, Analysis, Contacts).

Both queries use `staleTime: 0` and `refetchOnMount: 'always'` so fresh data is guaranteed on each navigation to a lead. React Query's cache deduplication ensures no redundant requests within a single mount cycle.

### State Management

Local React state handles:
- Active tab index
- Pending status change and reason text
- Optimistic task list mutations (add / remove)
- Timeline entries (seeded from `commandCenter` query, appended via log note/call actions)

Cache invalidation:
- Task completion → `queryClient.invalidateQueries(['commandCenter', leadId])`
- Status change → `queryClient.invalidateQueries(['commandCenter', leadId])`

---

## Components and Interfaces

### New Component: `UnifiedLeadCommandCenter`

**File:** `frontend/src/components/UnifiedLeadCommandCenter.tsx`

**Props:**
```typescript
interface UnifiedLeadCommandCenterProps {
  leadId: number
}
```

**Internal structure:**

```
UnifiedLeadCommandCenter
├── StickyHeader          (owner name, address, score, status, back button)
├── QueueContextBanners   (zero or more Alert strips)
├── MainLayout (two-column flex)
│   ├── ActivityColumn (flex: 1)
│   │   ├── RecommendedActionPanel
│   │   ├── TasksPanel
│   │   ├── NotesConflictBanner (conditional)
│   │   ├── ActivityPanel
│   │   │   ├── LogNoteForm
│   │   │   ├── LogCallForm
│   │   │   └── LeadTimeline
│   │   └── TabPanel
│   │       ├── Tab: Info     → InfoTab
│   │       ├── Tab: Score    → ScoreTab
│   │       ├── Tab: Enrichment → EnrichmentTab
│   │       ├── Tab: Marketing  → MarketingTab
│   │       ├── Tab: Analysis   → AnalysisTab
│   │       └── Tab: Contacts   → ContactsSection
│   └── PropertySidebar (sticky, hidden on xs/sm/md)
│       ├── SidebarSection: Contact Info   (phones, emails with tel:/mailto: + copy)
│       ├── SidebarSection: Owner
│       ├── SidebarSection: Property
│       ├── SidebarSection: Owner Mailing Address
│       ├── SidebarSection: Skip Trace (conditional)
│       ├── SidebarSection: Mailer History (conditional)
│       ├── SidebarSection: Marketing Lists (conditional)
│       ├── SidebarSection: Source
│       └── SidebarSection: Scores
```

### Route Wrappers (in `App.tsx`)

**`UnifiedLeadCommandCenterRoute`** — extracts and validates `:id` param, renders `UnifiedLeadCommandCenter` or an error state.

**`LegacyPropertyDetailRedirect`** — catches `/properties/:leadId`, redirects with `<Navigate to="/leads/:leadId" replace />`.

**`LegacyCommandCenterRedirect`** — catches `/leads/:id/command-center`, redirects with `<Navigate to="/leads/:id" replace />`.

### Reused Existing Components

All of these are used as-is with no API changes:

| Component | Where used |
|---|---|
| `RecommendedActionPanel` | Activity column |
| `LeadTaskList` | Tasks panel |
| `LogNoteForm` | Activity panel |
| `LogCallForm` | Activity panel |
| `LeadTimeline` | Activity panel |
| `ScoreBreakdownCard` | Score tab |
| `ScoreHistoryTimeline` | Score tab |
| `RecalculateButton` | Score tab |
| `ScoreLegend` | Score tab |
| `ContactsSection` | Contacts tab |
| `LeadScoreBadge` | Sticky header |

### Modified Components

**`PropertyListPage`** — Row click handler changed from `setPanelLead(row); setPanelOpen(true)` to `navigate('/leads/' + row.id)`. The `Drawer` component and all associated state (`panelOpen`, `panelLead`) are removed. The `onLeadSelect` prop is removed.

**`GlobalSearchBar`** — The `nav_path` construction fallback changes from `/properties/${id}` to `/leads/${id}`. No other changes needed since `nav_path` is already returned from the backend.

**All Work Queue components** — Update any hard-coded `/leads/:id/command-center` navigation to `/leads/:id`. The row click handler and icon button `onClick` already navigate by ID; only the path template changes.

**`App.tsx`** — Add `UnifiedLeadCommandCenterRoute`, redirect routes, remove `LeadDetailRoute`, remove `LeadCommandCenterRoute`. Update the `LeadListRoute` wrapper to pass `onLeadSelect={(id) => navigate('/leads/' + id)}` temporarily until `PropertyListPage` is updated.

---

## Data Models

### `CommandCenterPayload` (existing, from `/api/leads/:id/command-center`)

Already defined in `frontend/src/types/index.ts`. Key fields used by the unified page:

```typescript
interface CommandCenterPayload {
  id: number
  owner_first_name: string | null
  owner_last_name: string | null
  property_street: string | null
  property_city: string | null
  property_state: string | null
  lead_score: number
  lead_status: LeadStatus
  recommended_action: RecommendedActionMeta
  open_tasks: LeadTask[]
  timeline: { entries: LeadTimelineEntry[]; total: number; page: number; per_page: number }
  // ... phones, emails, property fields, sidebar metadata
}
```

### `PropertyDetail` (existing, from `/api/leads/:id`)

Already defined in `frontend/src/types/index.ts`. Used exclusively by the Tab_Panel tabs. Contains `enrichment_records`, `marketing_lists`, `analysis_session`, and `contacts`.

### `QueueContext` (derived client-side)

No new backend endpoint. Queue membership is derived from `CommandCenterPayload` fields using the existing `deriveQueueContext` pure function (currently in `LeadCommandCenter.tsx`, to be moved to a shared utility).

```typescript
interface QueueContext {
  label: string    // max 200 chars per Req 5.2
  path: string
  reason: string
  color: 'error' | 'warning' | 'info' | 'success' | 'default'
}
```

### No New Database Migrations

No schema changes are needed. This feature is entirely frontend routing, layout, and component consolidation. The existing `/api/leads/:id/command-center` and `/api/leads/:id` endpoints satisfy all data requirements.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Legacy route redirect — /properties/:id → /leads/:id

*For any* positive integer `id`, navigating to `/properties/:id` SHALL result in the browser URL being `/leads/:id` and the history entry being replaced (not pushed).

**Validates: Requirements 1.2, 13.1**

---

### Property 2: Legacy route redirect — /leads/:id/command-center → /leads/:id

*For any* positive integer `id`, navigating to `/leads/:id/command-center` SHALL result in the browser URL being `/leads/:id` and the history entry being replaced (not pushed).

**Validates: Requirements 1.3, 13.1**

---

### Property 3: Invalid ID shows error state

*For any* string that is not a positive integer (empty string, `"0"`, `"-1"`, `"abc"`, `"1.5"`, `"null"`), rendering `UnifiedLeadCommandCenter` with that ID SHALL display an error message and a link whose `href` navigates to `/properties`, and SHALL NOT render any lead data panel.

**Validates: Requirements 1.4**

---

### Property 4: Properties list row click navigates to canonical route

*For any* `PropertySummary` row with a valid numeric `id`, clicking that row in `PropertyListPage` SHALL call `navigate('/leads/' + id)` and SHALL NOT open a drawer or render a `PropertyDetailPage`.

**Validates: Requirements 2.1, 2.2**

---

### Property 5: Work queue navigation always uses canonical route

*For any* `QueueRow` with a valid `id`, clicking the lead name link, the "Open lead detail" icon button, or the row body (outside action controls) in any Work Queue table component SHALL call `navigate('/leads/' + id)`.

**Validates: Requirements 3.1, 3.2, 3.3**

---

### Property 6: Global search navigation always uses canonical route

*For any* lead search result — whether its `nav_path` is in the correct `/leads/{id}` format, is absent, or is in a legacy `/properties/{id}` format — selecting that result SHALL call `navigate('/leads/' + result.id)`.

**Validates: Requirements 4.1, 4.2**

---

### Property 7: Sticky header renders all required fields for any lead

*For any* `CommandCenterPayload`, the sticky header SHALL render the lead owner name (or "Unknown Owner" if absent), the property address, the numeric lead score, and the current lead status — all simultaneously visible without scrolling.

**Validates: Requirements 5.1**

---

### Property 8: Queue context banner count matches derived queue count

*For any* `CommandCenterPayload`, the number of `Queue_Context_Banner` elements rendered SHALL equal the number of queues returned by `deriveQueueContext(payload)`. When `deriveQueueContext` returns an empty array, zero banners SHALL be rendered.

**Validates: Requirements 5.2**

---

### Property 9: Loading state hides data panels; loaded state shows them

*For any* lead ID, while the `commandCenter` or `lead` query is in `isLoading` state, the unified page SHALL render a loading indicator and SHALL NOT render the Activity_Panel, Tab_Panel, Property_Sidebar, or Tasks panel. After both queries resolve successfully, all panels SHALL be visible.

**Validates: Requirements 5.8**

---

### Property 10: Status selector excludes current status from options

*For any* `LeadStatus` value `S` that is the lead's current status, the status selector SHALL display `S` as the currently selected value AND SHALL NOT include `S` as a selectable `MenuItem` option.

**Validates: Requirements 6.1**

---

### Property 11: Open tasks list renders all tasks from payload

*For any* `CommandCenterPayload` with `N` open tasks, the Tasks panel SHALL render exactly `N` task entries after the component mounts and the query resolves.

**Validates: Requirements 7.1**

---

### Property 12: Task creation optimistically grows the task list

*For any* existing task list of length `N`, creating a new task SHALL immediately increase the rendered task count to `N + 1`, before the backend call completes.

**Validates: Requirements 7.2**

---

### Property 13: Task completion optimistically shrinks the task list

*For any* existing task list of length `N > 0`, marking any task as complete SHALL immediately decrease the rendered task count to `N - 1`, before the backend call completes.

**Validates: Requirements 7.3**

---

### Property 14: New activity entries appear at the top of the timeline

*For any* existing timeline with `N` entries, submitting a new note or call log SHALL immediately insert the new entry at index 0 of the timeline, making the previous first entry move to index 1.

**Validates: Requirements 8.1, 8.2**

---

### Property 15: Load-more appends rather than replaces timeline entries

*For any* timeline currently showing `N` entries, loading the next page with `M` new entries SHALL result in `N + M` total entries displayed, with the original `N` entries preserved in their original order.

**Validates: Requirements 8.3**

---

### Property 16: Command-center endpoint called exactly once per mount

*For any* lead ID, mounting `UnifiedLeadCommandCenter` SHALL result in exactly one HTTP request to `/api/leads/:id/command-center`, not two or more, regardless of how many child components consume the query data.

**Validates: Requirements 12.1**

---

### Property 17: Lead detail endpoint called exactly once per mount

*For any* lead ID, mounting `UnifiedLeadCommandCenter` SHALL result in exactly one HTTP request to `/api/leads/:id`, not two or more, regardless of how many Tab_Panel tabs are rendered.

**Validates: Requirements 12.2**

---

## Error Handling

### Invalid Route ID (Req 1.4)

The `UnifiedLeadCommandCenterRoute` wrapper in `App.tsx` validates the `:id` param before rendering the component:

```typescript
function UnifiedLeadCommandCenterRoute() {
  const { id } = useParams<{ id: string }>()
  const numericId = Number(id)
  if (!id || !Number.isInteger(numericId) || numericId <= 0) {
    return <InvalidLeadIdError />  // shows message + /properties link
  }
  return <UnifiedLeadCommandCenter leadId={numericId} />
}
```

### Lead Not Found (Req 1.5)

`leadService.getLeadDetail` throws an error on 404. The `useQuery` error state is checked in the component; when `leadError` is set and the data is null, a "Lead not found" alert with a `/properties` link is rendered.

### Status Change Failure (Req 6.5)

The status confirmation panel holds `statusError` local state. On failure, `setStatusError('Failed to update status')` is called, the error is displayed inline within the panel, and the submit button is re-enabled by clearing `statusChanging`. The `pendingStatus` and `statusReason` are preserved so the user can retry.

### Task Completion Failure (Req 7.4)

Optimistic removal is performed immediately. A `tasksRef` (mutable ref) holds the pre-removal snapshot. If the API call fails, `tasksRef.current` is restored to the snapshot and `setTasks(previous)` is called. `console.error` logs the failure.

### Data Fetch Failure (Req 5.9, 9.x)

If the `commandCenter` query fails, the component renders an `<Alert severity="error">` with the error message and a `<Button component={Link} to="/properties">Back to Properties</Button>`. Individual tab queries (Score, etc.) render inline error alerts within their tab panel without affecting the rest of the page.

---

## Testing Strategy

### Unit / Component Tests (Vitest + React Testing Library)

**Test files to create:**
- `UnifiedLeadCommandCenter.test.tsx` — main component tests
- `UnifiedLeadCommandCenterRoute.test.tsx` — route param validation and redirect behavior

**What unit tests cover:**
- Structural presence of all required UI sections (header, tabs, sidebar, activity panel)
- Error states: invalid ID, 404 not found, API failure
- Status selector excludes current status (covers Property 10)
- Status confirmation panel: appears on selection, disabled during submit, closes on success, shows error on failure, restores on cancel
- Back button calls `navigate(-1)`
- Sidebar is hidden at xs breakpoint (via `sx` prop inspection)
- Tab count and labels in correct order

**What unit tests explicitly avoid:**
- Re-testing React Query caching behavior (tested by React Query's own suite)
- Re-testing child components already tested in their own test files

### Property-Based Tests (Vitest + fast-check)

The project's frontend uses Vitest. The property-based testing library is **fast-check**, the standard PBT library for TypeScript.

**Install:** `npm install --save-dev fast-check` (pinned to `^3.22.0`)

**Test file:** `UnifiedLeadCommandCenter.property.test.tsx`

Each property test uses `fc.assert(fc.asyncProperty(...))` with a minimum of 100 runs. Each test is tagged with a comment in the format:

```typescript
// Feature: unified-lead-command-center, Property N: <property text>
```

**Generators needed:**

```typescript
// Arbitrary for valid lead IDs
const validLeadId = fc.integer({ min: 1, max: 999999 })

// Arbitrary for invalid ID strings
const invalidIdString = fc.oneof(
  fc.constant('0'),
  fc.constant('-1'),
  fc.constant('abc'),
  fc.constant(''),
  fc.constant('1.5'),
  fc.string().filter(s => isNaN(Number(s)) || Number(s) <= 0)
)

// Arbitrary for CommandCenterPayload
const commandCenterPayloadArb = fc.record({
  id: fc.integer({ min: 1 }),
  owner_first_name: fc.option(fc.string()),
  owner_last_name: fc.option(fc.string()),
  property_street: fc.option(fc.string()),
  property_city: fc.option(fc.string()),
  property_state: fc.option(fc.string()),
  lead_score: fc.integer({ min: 0, max: 100 }),
  lead_status: fc.constantFrom(...ALL_LEAD_STATUSES),
  recommended_action: fc.record({ value: fc.option(fc.constantFrom(...CRM_ACTIONS)), label: fc.option(fc.string()), explanation: fc.option(fc.string()), signals: fc.constant({}) }),
  open_tasks: fc.array(taskArb, { maxLength: 20 }),
  timeline: fc.record({ entries: fc.array(timelineEntryArb), total: fc.nat(), page: fc.constant(1), per_page: fc.constant(20) }),
  // ... other optional fields
})

// Arbitrary for QueueRow
const queueRowArb = fc.record({
  id: fc.integer({ min: 1, max: 999999 }),
  owner_first_name: fc.option(fc.string()),
  owner_last_name: fc.option(fc.string()),
  property_street: fc.option(fc.string()),
  // ... other fields
})
```

**Properties mapped to tests:**

| Property | Test description |
|---|---|
| P1 | `fc.assert` over `validLeadId`: render with MemoryRouter at `/properties/:id`, assert final URL is `/leads/:id`, history used `replace`. |
| P2 | Same pattern for `/leads/:id/command-center` → `/leads/:id`. |
| P3 | `fc.assert` over `invalidIdString`: render `UnifiedLeadCommandCenterRoute`, assert error message present, no data panel rendered. |
| P4 | `fc.assert` over `validLeadId` (using FC's `fc.array` for row sets): render `PropertyListPage` mock, click row, verify `navigate` called with `/leads/${id}`, no Drawer present. |
| P5 | `fc.assert` over `queueRowArb`: render each queue component, click name/icon/row, assert `navigate('/leads/' + row.id)`. |
| P6 | `fc.assert` over `fc.record({ id: validLeadId, nav_path: fc.option(fc.string()) })`: render `GlobalSearchBar` with mock result, select it, verify `navigate('/leads/' + id)`. |
| P7 | `fc.assert` over `commandCenterPayloadArb`: render header section, assert owner name, address, score, status all present in DOM. |
| P8 | `fc.assert` over `commandCenterPayloadArb`: assert banner count === `deriveQueueContext(payload).length`. (Note: `deriveQueueContext` is a pure function; this property test can be run without rendering.) |
| P9 | `fc.assert` over `validLeadId`: while query loading, assert no data panels; after mock resolve, assert panels visible. |
| P10 | `fc.assert` over `fc.constantFrom(...ALL_LEAD_STATUSES)`: render with that status, assert status shown in selector AND not present in options. |
| P11 | `fc.assert` over `fc.array(taskArb)`: render with N tasks, assert N list items rendered. |
| P12 | `fc.assert` over `fc.array(taskArb)` + `taskInputArb`: add task, assert count N+1. |
| P13 | `fc.assert` over `fc.array(taskArb, { minLength: 1 })`: complete task, assert count N-1. |
| P14 | `fc.assert` over `timelineEntryArb`: submit note or call, assert new entry at index 0. |
| P15 | `fc.assert` over `fc.tuple(fc.array(timelineEntryArb), fc.array(timelineEntryArb))`: initial N, load M more, assert total N+M, originals unchanged. |
| P16 | `fc.assert` over `validLeadId`: mount with mock interceptor, assert `/api/leads/:id/command-center` called exactly once. |
| P17 | `fc.assert` over `validLeadId`: mount with mock interceptor, assert `/api/leads/:id` called exactly once. |

### Integration Tests (Manual / E2E)

The following scenarios require a running environment and are not suitable for automated unit/property tests:

- Full page load from each entry point (Properties list, each Work Queue, Global Search) navigates to `/leads/:id` with correct data rendered
- Status change persisted end-to-end and reflected in the backend
- Task creation and completion persisted end-to-end
- Timeline entries logged via note and call forms visible on next page load
- Redirect from `/properties/:id` and `/leads/:id/command-center` via real browser navigation

### Backend API

No new backend endpoints are needed. The existing endpoints are sufficient:

| Endpoint | Purpose |
|---|---|
| `GET /api/leads/:id/command-center` | CRM data, tasks, timeline (page 1), queue signals |
| `GET /api/leads/:id` | Full property detail for Tab_Panel |
| `PATCH /api/leads/:id/status` | Status change |
| `POST /api/leads/:id/tasks` | Create task |
| `POST /api/leads/:id/tasks/:taskId/complete` | Complete task |
| `POST /api/leads/:id/notes` | Log note |
| `POST /api/leads/:id/calls` | Log call |
| `GET /api/leads/:id/timeline` | Paginated timeline (pages 2+) |

The backend search service (`GET /api/search`) should already return `nav_path` values in `/leads/{id}` format. If not, a one-line fix in the search controller serializer is all that is needed (not a schema migration).
