# Implementation Plan: Unified Lead Command Center

## Overview

Consolidate `PropertyDetailPage` (`/properties/:leadId`) and `LeadCommandCenter` (`/leads/:id/command-center`) into a single `UnifiedLeadCommandCenter` component served at `/leads/:id`. Update all entry points to navigate to the canonical route and register redirect rules for legacy routes. The feature is entirely frontend — no backend changes are required.

## Tasks

- [x] 1. Install fast-check and set up the property test file scaffold
  - Run `npm install --save-dev fast-check@^3.22.0` in `frontend/`
  - Create empty `frontend/src/components/UnifiedLeadCommandCenter.property.test.tsx` with the top-level `describe` block, all 17 `it.todo` stubs, and shared arbitraries (`validLeadId`, `invalidIdString`, `commandCenterPayloadArb`, `queueRowArb`, `taskArb`, `timelineEntryArb`)
  - Confirm Vitest picks up the file with `npm test -- --run UnifiedLeadCommandCenter.property`
  - _Requirements: 1.1, 12.1, 12.2_

- [x] 2. Create shared utility: `deriveQueueContext`
  - [x] 2.1 Extract `deriveQueueContext` from `LeadCommandCenter.tsx` into `frontend/src/utils/deriveQueueContext.ts`
    - Keep the function signature and logic identical; export it as a named export
    - Export the `QueueContext` interface from the same file
    - Add an index re-export from `frontend/src/utils/index.ts` (create the file if absent)
    - _Requirements: 5.2_

  - [x] 2.2 Write property test for `deriveQueueContext` (Property 8)
    - `// Feature: unified-lead-command-center, Property 8: Queue context banner count matches derived queue count`
    - `fc.assert` over `commandCenterPayloadArb`: assert `deriveQueueContext(payload).length` equals the number of banner elements rendered (pure-function variant — no render needed)
    - **Property 8: Queue context banner count matches derived queue count**
    - **Validates: Requirements 5.2**

- [x] 3. Build `UnifiedLeadCommandCenter` — core scaffold and data loading
  - [x] 3.1 Create `frontend/src/components/UnifiedLeadCommandCenter.tsx` with data-fetching skeleton
    - Define `UnifiedLeadCommandCenterProps { leadId: number }`
    - Wire two React Query hooks: `useQuery(['commandCenter', leadId], ...)` calling `leadService.getCommandCenter(leadId)` with `staleTime: 0, refetchOnMount: 'always'`; and `useQuery(['lead', leadId], ...)` calling `leadService.getLeadDetail(leadId)` with the same options
    - While either query `isLoading`, render `<CircularProgress aria-label="Loading lead" />` and nothing else
    - When `commandCenterError` is set, render `<Alert severity="error">` with the message and a `<Button component={Link} to="/properties">Back to Properties</Button>`
    - Export the component as a named export
    - _Requirements: 5.8, 5.9, 12.1, 12.2_

  - [x] 3.2 Write property test for loading / loaded state (Property 9)
    - `// Feature: unified-lead-command-center, Property 9: Loading state hides data panels; loaded state shows them`
    - `fc.assert` over `validLeadId`: mock React Query — while `isLoading` is true assert no `data-testid="activity-panel"` / `data-testid="tab-panel"` / `data-testid="property-sidebar"` / `data-testid="tasks-panel"` in DOM; after mock resolves assert all four are present
    - **Property 9: Loading state hides data panels; loaded state shows them**
    - **Validates: Requirements 5.8**

  - [x] 3.3 Write property test for single mount requests (Properties 16 and 17)
    - `// Feature: unified-lead-command-center, Property 16: Command-center endpoint called exactly once per mount`
    - `// Feature: unified-lead-command-center, Property 17: Lead detail endpoint called exactly once per mount`
    - `fc.assert` over `validLeadId` with a `vi.fn()` request interceptor: mount `UnifiedLeadCommandCenter`, assert `/api/leads/:id/command-center` called exactly once and `/api/leads/:id` called exactly once
    - **Property 16: Command-center endpoint called exactly once per mount**
    - **Property 17: Lead detail endpoint called exactly once per mount**
    - **Validates: Requirements 12.1, 12.2**

- [x] 4. Build `UnifiedLeadCommandCenter` — StickyHeader and QueueContextBanners
  - [x] 4.1 Implement `StickyHeader` sub-component (inline or separate file)
    - Render owner name (fallback `"Unknown Owner"` when both name fields are null/empty), property address, `<LeadScoreBadge>`, and current status chip — all in a `position: 'sticky', top: 0` `AppBar` or `Box`
    - Render a back `<Button>` (or `<IconButton>`) that calls `navigate(-1)` — `data-testid="back-button"`
    - _Requirements: 5.1, 10.1, 10.2_

  - [x] 4.2 Write property test for sticky header content (Property 7)
    - `// Feature: unified-lead-command-center, Property 7: Sticky header renders all required fields for any lead`
    - `fc.assert` over `commandCenterPayloadArb`: render `StickyHeader` with payload, assert owner name text present, address text present, score value present, status text present
    - **Property 7: Sticky header renders all required fields for any lead**
    - **Validates: Requirements 5.1**

  - [x] 4.3 Implement `QueueContextBanners` sub-component
    - Call `deriveQueueContext(commandCenterData)` and map results to `<Alert>` strips, each with the queue name, reason text, and a `<Link>` to the queue path
    - Render zero banners when `deriveQueueContext` returns `[]`
    - Each banner: `data-testid="queue-context-banner"`
    - _Requirements: 5.2_

- [x] 5. Build `UnifiedLeadCommandCenter` — Status Management panel
  - [x] 5.1 Implement status selector and confirmation panel
    - Render a `<Select>` whose displayed value is the current status; populate `<MenuItem>` options with every `LeadStatus` value **except** the current status
    - On selection of a new status, show an inline confirmation panel with a `<TextField multiline>` reason field (max 500 chars) and a Submit button (`data-testid="status-submit-btn"`)
    - While `statusChanging` is true, disable the Submit button
    - On success: close panel, call `queryClient.invalidateQueries(['commandCenter', leadId])`
    - On failure: set `statusError` state, render inline `<Alert severity="error">` within the panel, re-enable Submit
    - On cancel: clear `pendingStatus`, close panel
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 5.2 Write property test for status selector exclusion (Property 10)
    - `// Feature: unified-lead-command-center, Property 10: Status selector excludes current status from options`
    - `fc.assert` over `fc.constantFrom(...ALL_LEAD_STATUSES)`: render status selector with that status as current, assert status value shown in selector AND that status string does NOT appear as a `<MenuItem>` option
    - **Property 10: Status selector excludes current status from options**
    - **Validates: Requirements 6.1**

- [x] 6. Build `UnifiedLeadCommandCenter` — Tasks panel
  - [x] 6.1 Implement Tasks panel wiring `LeadTaskList`
    - Seed local `tasks` state from `commandCenterData.open_tasks` on first successful query
    - Render `<LeadTaskList>` inside a `Paper` with `data-testid="tasks-panel"`
    - Wire task-creation: optimistically `setTasks(prev => [newTask, ...prev])` before the `POST /api/leads/:id/tasks` call completes
    - Wire task-completion: optimistically `setTasks(prev => prev.filter(t => t.id !== taskId))`; on failure restore from `tasksRef.current` snapshot and `console.error`
    - On task completed or status changed: `queryClient.invalidateQueries(['commandCenter', leadId])`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 12.4_

  - [x] 6.2 Write property test for task list count (Property 11)
    - `// Feature: unified-lead-command-center, Property 11: Open tasks list renders all tasks from payload`
    - `fc.assert` over `fc.array(taskArb)`: seed Tasks panel with N tasks, assert exactly N task entries rendered
    - **Property 11: Open tasks list renders all tasks from payload**
    - **Validates: Requirements 7.1**

  - [x] 6.3 Write property test for optimistic task creation (Property 12)
    - `// Feature: unified-lead-command-center, Property 12: Task creation optimistically grows the task list`
    - `fc.assert` over `fc.tuple(fc.array(taskArb), taskInputArb)`: start with N tasks, fire create action, assert count becomes N+1 before mock backend resolves
    - **Property 12: Task creation optimistically grows the task list**
    - **Validates: Requirements 7.2**

  - [x] 6.4 Write property test for optimistic task completion (Property 13)
    - `// Feature: unified-lead-command-center, Property 13: Task completion optimistically shrinks the task list`
    - `fc.assert` over `fc.array(taskArb, { minLength: 1 })`: start with N tasks, mark first as complete, assert count becomes N-1 before mock backend resolves
    - **Property 13: Task completion optimistically shrinks the task list**
    - **Validates: Requirements 7.3**

- [x] 7. Build `UnifiedLeadCommandCenter` — Activity panel (timeline, log forms)
  - [x] 7.1 Implement `ActivityPanel` wiring `LogNoteForm`, `LogCallForm`, and `LeadTimeline`
    - Seed local `timelineEntries` state from `commandCenterData.timeline.entries`
    - Wrap everything in a scrollable `Box` with `data-testid="activity-panel"`
    - On note submit: optimistically prepend new entry to `timelineEntries` (index 0) and persist via `POST /api/leads/:id/notes`
    - On call submit: same optimistic prepend pattern and `POST /api/leads/:id/calls`
    - Render a "Load more" button; on click fetch `GET /api/leads/:id/timeline?page=N+1` and **append** results to `timelineEntries`
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 7.2 Write property test for new entries at top of timeline (Property 14)
    - `// Feature: unified-lead-command-center, Property 14: New activity entries appear at the top of the timeline`
    - `fc.assert` over `timelineEntryArb`: given existing N entries, submit note/call, assert new entry is at rendered index 0 and previous first entry is at index 1
    - **Property 14: New activity entries appear at the top of the timeline**
    - **Validates: Requirements 8.1, 8.2**

  - [x] 7.3 Write property test for load-more appends (Property 15)
    - `// Feature: unified-lead-command-center, Property 15: Load-more appends rather than replaces timeline entries`
    - `fc.assert` over `fc.tuple(fc.array(timelineEntryArb), fc.array(timelineEntryArb))`: render with initial N entries, trigger load-more returning M entries, assert total is N+M and original entries preserved in order
    - **Property 15: Load-more appends rather than replaces timeline entries**
    - **Validates: Requirements 8.3**

- [x] 8. Build `UnifiedLeadCommandCenter` — Tab panel and Property Sidebar
  - [x] 8.1 Implement `TabPanel` with all six tabs using `leadData` from the `lead` query
    - Render MUI `<Tabs>` + `<Tab>` for: Info, Score, Enrichment, Marketing, Analysis, Contacts — in that order
    - Wrap in a `Box` with `data-testid="tab-panel"`
    - Info tab: property detail fields grouped by category per Req 9.1
    - Score tab: `<ScoreBreakdownCard>`, `<ScoreHistoryTimeline>`, `<RecalculateButton>`, `<ScoreLegend>`; show "generate first score" prompt when no score exists
    - Enrichment tab: enrichment records table (source, status, date, details columns)
    - Marketing tab: marketing list memberships table (list name, outreach status, added date)
    - Analysis tab: linked session summary or buttons to start Single-Family / Multifamily analysis
    - Contacts tab: `<ContactsSection propertyId={leadId} />`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 8.2 Implement `PropertySidebar` — sticky right-column panel
    - Sections: Contact Info (phones with `tel:` + copy, emails with `mailto:` + copy), Owner, Property, Owner Mailing Address, Skip Trace (conditional), Mailer History (conditional), Marketing Lists (conditional), Source, Scores
    - Apply `sx={{ display: { xs: 'none', sm: 'none', md: 'none', lg: 'block' } }}` to hide below `lg` breakpoint
    - Wrap in a `Box` with `position: 'sticky'` and `data-testid="property-sidebar"`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 9. Checkpoint — unit tests for UnifiedLeadCommandCenter
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Add route wrappers in `App.tsx` and register redirect rules
  - [x] 10.1 Add `UnifiedLeadCommandCenterRoute` wrapper in `App.tsx`
    - Extract `:id` param, validate as positive integer using `Number.isInteger(n) && n > 0`
    - On invalid ID: render `<InvalidLeadIdError />` component (inline or separate) showing "Invalid lead ID" message and a `<Link to="/properties">Back to Properties</Link>`; `data-testid="invalid-id-error"`
    - On valid ID: render `<UnifiedLeadCommandCenter leadId={numericId} />`
    - Register route: `<Route path="/leads/:id" element={<UnifiedLeadCommandCenterRoute />} />`
    - _Requirements: 1.1, 1.4_

  - [x] 10.2 Register legacy redirect routes in `App.tsx`
    - Add `<Route path="/properties/:leadId" element={<LegacyPropertyDetailRedirect />} />` — component renders `<Navigate to={'/leads/' + leadId} replace />`
    - Add `<Route path="/leads/:id/command-center" element={<LegacyCommandCenterRedirect />} />` — component renders `<Navigate to={'/leads/' + id} replace />`
    - Both routes must be registered in the same commit as the canonical `/leads/:id` route (Req 13.1)
    - Remove the existing `<Route path="/properties/:leadId" element={<LeadDetailRoute />} />` and `<Route path="/leads/:id/command-center" element={<LeadCommandCenterRoute />} />` entries
    - _Requirements: 1.2, 1.3, 13.1_

  - [x] 10.3 Write property tests for legacy redirects (Properties 1 and 2)
    - `// Feature: unified-lead-command-center, Property 1: Legacy route redirect — /properties/:id → /leads/:id`
    - `// Feature: unified-lead-command-center, Property 2: Legacy route redirect — /leads/:id/command-center → /leads/:id`
    - `fc.assert` over `validLeadId`: render with `MemoryRouter` initialEntry at `/properties/:id`, assert final URL is `/leads/:id` and history entry was replaced (not pushed)
    - Repeat for `/leads/:id/command-center` → `/leads/:id`
    - **Property 1: Legacy route redirect — /properties/:id → /leads/:id**
    - **Property 2: Legacy route redirect — /leads/:id/command-center → /leads/:id**
    - **Validates: Requirements 1.2, 1.3, 13.1**

  - [x] 10.4 Write property test for invalid ID error state (Property 3)
    - `// Feature: unified-lead-command-center, Property 3: Invalid ID shows error state`
    - `fc.assert` over `invalidIdString`: render `UnifiedLeadCommandCenterRoute` wrapped in `MemoryRouter` with that ID, assert `data-testid="invalid-id-error"` is present, assert no `data-testid="activity-panel"` or `data-testid="tab-panel"` in DOM
    - **Property 3: Invalid ID shows error state**
    - **Validates: Requirements 1.4**

- [x] 11. Update `PropertyListPage` — remove drawer, navigate directly to `/leads/:id`
  - [x] 11.1 Modify `onRowClicked` handler in `PropertyListPage.tsx`
    - Replace `setPanelLead(e.data); setPanelOpen(true)` with `if (e.data?.id) navigate('/leads/' + e.data.id)`
    - Add `useNavigate()` import if not already present
    - Remove all drawer-related state variables: `panelOpen`, `panelLead`
    - Remove the `<Drawer>` JSX block and all its contents from the render
    - Keep the `onLeadSelect` prop in the interface for now (it will be removed in task 14)
    - _Requirements: 2.1, 2.2, 13.2_

  - [x] 11.2 Write property test for Properties list row click (Property 4)
    - `// Feature: unified-lead-command-center, Property 4: Properties list row click navigates to canonical route`
    - `fc.assert` over `validLeadId`: render a minimal `PropertyListPage` mock (or the component with mocked AG Grid), click the row, verify `navigate` was called with `'/leads/' + id` and that no `<Drawer>` is present in the DOM
    - **Property 4: Properties list row click navigates to canonical route**
    - **Validates: Requirements 2.1, 2.2**

- [x] 12. Update `QueueTable` — change all navigation from `/leads/:id/command-center` to `/leads/:id`
  - [x] 12.1 Update row click, lead-name link, and icon button navigation in `QueueTable.tsx`
    - In `onClick` on `<TableRow>`: change `navigate('/leads/${row.id}/command-center')` → `navigate('/leads/' + row.id)`
    - In the lead-name `<Link component={RouterLink}>`: change `to={'/leads/${row.id}/command-center'}` → `to={'/leads/' + row.id}`
    - In the "Open lead detail" `<IconButton component={RouterLink}>`: change `to={'/leads/${row.id}/command-center'}` → `to={'/leads/' + row.id}`
    - Search all other queue components (`TodaysActionQueue.tsx`, `PreviouslyWarmQueue.tsx`, `FollowUpOverdueQueue.tsx`, `NoNextActionQueue.tsx`, `NeedsReviewQueue.tsx`, `DoNotContactQueue.tsx`, `MissingPropertyMatchQueue.tsx`) for any hardcoded `/command-center` paths and update them
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 12.2 Write property test for Work Queue navigation (Property 5)
    - `// Feature: unified-lead-command-center, Property 5: Work queue navigation always uses canonical route`
    - `fc.assert` over `queueRowArb`: render `QueueTable` with a single row, click (a) the lead name link, (b) the "Open lead detail" icon button, (c) the row body — assert `navigate` called with `'/leads/' + row.id` in all three cases
    - **Property 5: Work queue navigation always uses canonical route**
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [x] 13. Update `GlobalSearchBar` — ensure navigation always uses `/leads/:id`
  - [x] 13.1 Patch `GlobalSearchBar.tsx` click handler and keyboard Enter handler
    - In the `onClick` of lead `<ListItemButton>`: replace `navigate(lead.nav_path)` with `navigate('/leads/' + lead.id)` — removes dependency on `nav_path` format for leads
    - In the keyboard `Enter` handler: if the focused item is a lead result, navigate using `'/leads/' + item.id`; if no result is focused, take no action (Req 4.3)
    - Analysis session results are unchanged (they still use `session.nav_path`)
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 13.2 Write property test for Global Search navigation (Property 6)
    - `// Feature: unified-lead-command-center, Property 6: Global search navigation always uses canonical route`
    - `fc.assert` over `fc.record({ id: validLeadId, nav_path: fc.option(fc.string()) })`: render `GlobalSearchBar` with a mocked lead result having that `id` and `nav_path`, click the result, assert `navigate` called with `'/leads/' + result.id` regardless of `nav_path` value
    - **Property 6: Global search navigation always uses canonical route**
    - **Validates: Requirements 4.1, 4.2**

- [x] 14. Clean up legacy routes and retire `LeadDetailRoute` / `LeadListRoute` references
  - [x] 14.1 Remove `LeadDetailRoute` and update `LeadListRoute` in `App.tsx`
    - Delete the `LeadDetailRoute` function (superseded by `UnifiedLeadCommandCenterRoute`)
    - Update `LeadListRoute` to remove the `onLeadSelect` prop: `return <PropertyListPage />`
    - Remove the `onLeadSelect` prop from `PropertyListPageProps` interface in `PropertyListPage.tsx` and the "Full Profile" button in the Drawer (already removed from step 11, confirm here)
    - Remove imports for `PropertyDetailPage` and `LeadCommandCenter` from `App.tsx`
    - _Requirements: 13.2, 13.3, 13.4_

- [x] 15. Checkpoint — run full test suite and verify all imports resolve
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Wire all components into `UnifiedLeadCommandCenter` and confirm two-column layout
  - [x] 16.1 Compose final layout in `UnifiedLeadCommandCenter.tsx`
    - Render: `StickyHeader` → `QueueContextBanners` → two-column flex `Box` with `ActivityColumn` (flex 1) and `PropertySidebar` (fixed width, hidden below `lg`)
    - `ActivityColumn` order: `RecommendedActionPanel` → `TasksPanel` → `ActivityPanel` → `TabPanel`
    - Ensure `data-testid` attributes are in place on all major sections
    - _Requirements: 5.1–5.9_

  - [x] 16.2 Write unit test `UnifiedLeadCommandCenter.test.tsx`
    - Verify structural presence: sticky header, tab panel with six tabs in order, property sidebar, activity panel, tasks panel
    - Verify error state for invalid ID renders `data-testid="invalid-id-error"`
    - Verify back button calls `navigate(-1)`
    - Verify sidebar has `sx` hiding it below `lg` breakpoint
    - _Requirements: 5.1, 5.4, 5.5, 5.6, 5.7, 10.1, 10.2, 11.5_

- [x] 17. Final checkpoint — full suite green
  - Run `npm test -- --run` in `frontend/` and confirm all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use `fast-check` v3.22.x (`fc.assert`, `fc.asyncProperty`)
- Each property test is annotated with `// Feature: unified-lead-command-center, Property N: <text>`
- Checkpoints ensure incremental validation between major phases
- The design uses TypeScript throughout — no language selection needed
- `deriveQueueContext` must be extracted before building `UnifiedLeadCommandCenter` (task 2 before task 4)
- Legacy route redirects must be registered atomically with the canonical route (task 10.1 + 10.2 together)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1", "4.3"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["5.2", "6.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "6.4", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "8.1", "8.2"] },
    { "id": 8, "tasks": ["10.1", "10.2", "11.1", "12.1", "13.1"] },
    { "id": 9, "tasks": ["10.3", "10.4", "11.2", "12.2", "13.2", "14.1"] },
    { "id": 10, "tasks": ["16.1"] },
    { "id": 11, "tasks": ["16.2"] }
  ]
}
```
