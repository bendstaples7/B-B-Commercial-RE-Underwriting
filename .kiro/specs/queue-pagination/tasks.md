# Implementation Plan: Queue Pagination

## Overview

Add consistent MUI-based pagination to all seven Actionable Lead Command Center work queues. The implementation proceeds in layers: pure utility functions first, then the shared `QueueTable` UI, then wiring each Queue_Component. Property-based tests validate the pure functions and React component behavior against all valid inputs. All work is confined to the frontend — no backend or API changes are required.

## Tasks

- [x] 1. Create pagination utility module
  - [x] 1.1 Create `frontend/src/utils/pagination.ts` with `computeTotalPages` and `clampPage`
    - Export `computeTotalPages(total: number, perPage: number): number` — returns `Math.ceil(total / perPage)` when `total > 0`, else `0`
    - Export `clampPage(page: number, totalPages: number): number` — returns `Math.min(Math.max(1, page), Math.max(1, totalPages))`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 1.2 Write property tests for `computeTotalPages` (P4)
    - **Property 4: totalPages computation is correct for all positive totals**
    - Use `fc.integer({ min: 1, max: 1_000_000 })` for `total` and `fc.integer({ min: 1, max: 100 })` for `per_page`; assert result equals `Math.ceil(total / per_page)`
    - Also assert `computeTotalPages(0, anyPerPage)` returns `0`
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 4: totalPages computation is correct for all positive totals`
    - Test file: `frontend/src/utils/pagination.test.ts`
    - _Requirements: 3.1, 3.2_

  - [x] 1.3 Write property tests for `clampPage` (P3)
    - **Property 3: Page clamping holds for all integer inputs**
    - Use `fc.integer()` for `requestedPage` and `fc.integer({ min: 1 })` for `totalPages`; assert result is always in `[1, totalPages]`
    - Assert values below 1 clamp to 1, values above `totalPages` clamp to `totalPages`, values in range are unchanged
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 3: Page clamping holds for all integer inputs`
    - Test file: `frontend/src/utils/pagination.test.ts`
    - _Requirements: 3.3, 3.4_

- [x] 2. Update `QueueTable` with pagination props and render block
  - [x] 2.1 Add `page`, `totalPages`, and `onPageChange` optional props to `QueueTableProps` interface in `frontend/src/components/QueueTable.tsx`
    - Extend `QueueTableProps` with `page?: number`, `totalPages?: number`, `onPageChange?: (page: number) => void`
    - Accept these three props in the component function signature
    - _Requirements: 1.1_

  - [x] 2.2 Add the pagination render block to `QueueTable`
    - Below the existing "Total count" caption, inside the outer `<Box>`, render the block only when `(totalPages ?? 0) > 1`
    - Wrapping `<Box>` with `sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 2 }}`, `aria-label="queue pagination"`, and `data-testid="queue-pagination"`
    - `<Typography variant="caption" color="text.secondary" data-testid="queue-page-label">Page {page} of {totalPages}</Typography>`
    - `<Pagination count={totalPages} page={page} shape="rounded" color="primary" onChange={(_event, value) => onPageChange?.(value)} aria-label="queue pagination" />`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 5.8, 6.1, 6.2, 7.1, 7.2_

  - [x] 2.3 Write unit tests for `QueueTable` pagination render block
    - Renders pagination wrapper (`data-testid="queue-pagination"`) when `totalPages > 1`
    - Does not render pagination when `totalPages = 1`
    - Does not render pagination when `totalPages` prop is not provided
    - Renders "Page X of Y" label (`data-testid="queue-page-label"`) for specific `(page, totalPages)` values
    - `aria-label="queue pagination"` present on wrapping element
    - Does not render pagination when `total = 0`
    - Test file: `frontend/src/components/QueueTable.test.tsx` (new describe block)
    - _Requirements: 1.2, 1.3, 1.4, 6.1, 6.2, 7.1, 7.2_

  - [x] 2.4 Write property test for `QueueTable` pagination content (P1)
    - **Property 1: Pagination renders with correct content for all valid page positions**
    - Use `fc.integer({ min: 2, max: 100 })` for `totalPages`, map `fc.integer({ min: 1 })` into `[1, totalPages]` for `page`
    - For each generated `(page, totalPages)`, render `QueueTable` and assert: element with `aria-label="queue pagination"` exists, text "Page {page} of {totalPages}" is present, MUI Pagination receives `count={totalPages}` and `page={page}`
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 1: Pagination renders with correct content for all valid page positions`
    - Test file: `frontend/src/components/QueueTable.test.tsx`
    - _Requirements: 1.2, 1.4, 6.1_

  - [x] 2.5 Write property test for `QueueTable` page change callback (P2)
    - **Property 2: Page change callback delivers the correct page number**
    - Use same generator as P1; simulate clicking a page button and assert `onPageChange` is called with the exact expected value
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 2: Page change callback delivers the correct page number`
    - Test file: `frontend/src/components/QueueTable.test.tsx`
    - _Requirements: 1.5_

- [x] 3. Checkpoint — Ensure all tests pass up to this point
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Wire pagination into `TodaysActionQueue`
  - [x] 4.1 Add `page` state and pagination wiring to `TodaysActionQueue`
    - Add `const [page, setPage] = useState(1)` (this component has no page state yet)
    - Add `page` to the React Query `queryKey`: `['queue-todays-action', page]`
    - Pass `page` to `queueService.getTodaysAction(page, 20)`
    - Derive `totalPages` using `computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)`
    - Add `handlePageChange` using `clampPage` from `pagination.ts`
    - Spread `{ page, totalPages, onPageChange: handlePageChange }` onto `QueueTable` conditionally when `totalPages > 1`
    - Reset `page` to `1` in every row action success path after `invalidateQueries`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.2_

  - [x] 4.2 Write unit tests for `TodaysActionQueue` pagination
    - Fetches with `page=1` on mount
    - Renders pagination controls when service returns `total > per_page`
    - Does not render pagination when `total <= per_page`
    - Successful row action resets page to 1
    - Failed row action leaves page unchanged
    - Test file: `frontend/src/components/TodaysActionQueue.test.tsx`
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 4.1, 4.2_

- [x] 5. Wire pagination into `NoNextActionQueue`
  - [x] 5.1 Expose the existing `setPage` setter and wire up pagination in `NoNextActionQueue`
    - Change `const [page] = useState(1)` to `const [page, setPage] = useState(1)`
    - Add `page` to the React Query `queryKey`: `['queue-no-next-action', page]`
    - Pass `page` to the service call
    - Derive `totalPages` using `computeTotalPages`
    - Add `handlePageChange` using `clampPage`
    - Spread pagination props onto `QueueTable` conditionally
    - Reset `page` to `1` in every row action success path after `invalidateQueries`
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.1_

  - [x] 5.2 Write unit tests for `NoNextActionQueue` pagination (representative for all 7)
    - Renders pagination controls when service returns `total > per_page`
    - Does not render pagination when `total <= per_page`
    - Page change updates the query call to the service with the new page
    - Successful row action resets page to 1
    - Failed row action leaves page unchanged
    - Test file: `frontend/src/components/NoNextActionQueue.test.tsx`
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 4.1, 4.2, 5.1_

  - [x] 5.3 Write property test for successful row action page reset (P5)
    - **Property 5: Successful row action resets page to 1**
    - Use `fc.integer({ min: 2, max: 50 })` for initial `page`; for each value, mount `NoNextActionQueue`, simulate being on that page, trigger a successful row action, and assert `page` state is reset to `1`
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 5: Successful row action resets page to 1`
    - Test file: `frontend/src/components/NoNextActionQueue.test.tsx`
    - _Requirements: 4.1_

  - [x] 5.4 Write property test for failed row action page stability (P6)
    - **Property 6: Failed row action leaves page unchanged**
    - Use `fc.integer({ min: 1, max: 50 })` for initial `page`; for each value, mount `NoNextActionQueue`, trigger a failing row action, and assert `page` state is unchanged
    - Minimum 100 iterations
    - Tag: `// Feature: queue-pagination, Property 6: Failed row action leaves page unchanged`
    - Test file: `frontend/src/components/NoNextActionQueue.test.tsx`
    - _Requirements: 4.2_

- [x] 6. Wire pagination into remaining five Queue_Components
  - [x] 6.1 Wire pagination into `PreviouslyWarmQueue`
    - Expose `setPage` setter (currently destructured without it)
    - Update `queryKey` to `['queue-previously-warm', page]` (currently has no page in key)
    - Pass `page` to service call; derive `totalPages`; add `handlePageChange`; spread conditional pagination props; reset page on row action success
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.3_

  - [x] 6.2 Wire pagination into `FollowUpOverdueQueue`
    - Expose `setPage` setter; update `queryKey` to include `page`; pass `page` to service; derive `totalPages`; add `handlePageChange`; spread conditional pagination props; reset page on row action success
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.4_

  - [x] 6.3 Wire pagination into `NeedsReviewQueue`
    - Expose `setPage` setter; update `queryKey` to include `page`; pass `page` to service; derive `totalPages`; add `handlePageChange`; spread conditional pagination props; reset page on row action success
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.5_

  - [x] 6.4 Wire pagination into `DoNotContactQueue`
    - Expose `setPage` setter; update `queryKey` to include `page`; pass `page` to service; derive `totalPages`; add `handlePageChange`; spread conditional pagination props; reset page on row action success
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.6_

  - [x] 6.5 Wire pagination into `MissingPropertyMatchQueue`
    - Expose `setPage` setter; update `queryKey` to include `page`; pass `page` to service; derive `totalPages`; add `handlePageChange`; spread conditional pagination props; reset page on row action success
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 4.2, 5.7_

- [x] 7. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- `computeTotalPages` and `clampPage` are pure functions extracted to `frontend/src/utils/pagination.ts` — import them in all Queue_Components rather than inlining the formulas
- Property-based tests use [fast-check](https://fast-check.io/) (`fc`) — confirm it is installed in `frontend/` before implementing PBT tasks (`npm install fast-check --save-dev`)
- `PreviouslyWarmQueue` currently has `queryKey: ['queue-previously-warm']` with no page — task 6.1 corrects this anomaly as part of the standard wiring
- All row action success paths (there may be multiple per component) must call `setPage(1)` after `queryClient.invalidateQueries`
- Conditionally spreading pagination props (`...( totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {} )`) satisfies requirements 2.4 and 2.5 by never passing `undefined` props to `QueueTable`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5"] },
    { "id": 4, "tasks": ["4.1", "5.1"] },
    { "id": 5, "tasks": ["4.2", "5.2", "5.3", "5.4", "6.1", "6.2", "6.3", "6.4", "6.5"] }
  ]
}
```
