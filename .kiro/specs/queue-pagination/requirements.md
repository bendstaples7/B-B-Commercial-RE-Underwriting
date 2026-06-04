# Requirements Document

## Introduction

The Actionable Lead Command Center UI contains seven work queues (No Next Action, Today's Action, Previously Warm, Follow-Up Overdue, Needs Review, Do Not Contact, Missing Property Match). Each queue currently fetches only page 1 of 20 results and has no pagination UI, making the vast majority of leads inaccessible (e.g. 68,565 DuPage leads in No Next Action).

The backend already returns `{ rows, total, page, per_page }` from all queue endpoints and accepts `page` and `per_page` query parameters. This feature adds consistent pagination UI to all seven queues so users can navigate through the full result set.

## Glossary

- **Queue_Component**: One of the seven React components — `NoNextActionQueue`, `TodaysActionQueue`, `PreviouslyWarmQueue`, `FollowUpOverdueQueue`, `NeedsReviewQueue`, `DoNotContactQueue`, `MissingPropertyMatchQueue`.
- **QueueTable**: The shared `QueueTable` React component (`frontend/src/components/QueueTable.tsx`) that renders the sortable lead table used by all Queue_Components.
- **Pagination_Controls**: The UI element rendered below the table that allows the user to navigate between pages. Implemented using the MUI `Pagination` component.
- **Page**: A 1-based integer indicating the current result page requested from the backend.
- **Total_Pages**: The total number of pages, computed as `Math.ceil(total / per_page)`.
- **Queue_Service**: The `queueService` object in `frontend/src/services/api.ts` that wraps all backend queue endpoint calls.
- **React_Query**: TanStack React Query v5, used for server-state caching and background refetch in all Queue_Components.

---

## Requirements

### Requirement 1: QueueTable accepts and renders Pagination_Controls

**User Story:** As a user, I want to see page navigation controls below the lead table, so that I can browse through pages of results beyond the first 20 leads.

#### Acceptance Criteria

1. THE `QueueTable` SHALL accept `page`, `totalPages`, and `onPageChange` as optional props in addition to its existing props.
2. WHEN `totalPages` is greater than 1, THE `QueueTable` SHALL render a `Pagination_Controls` element below the table using the MUI `Pagination` component.
3. WHEN `totalPages` is 1 or less, THE `QueueTable` SHALL not render any `Pagination_Controls` element.
4. WHEN `totalPages` is greater than 1, THE `QueueTable` SHALL display the MUI `Pagination` component with `count` set to `totalPages` and `page` set to the current `page` prop.
5. WHEN the user clicks a page number or the Previous/Next arrow in the `Pagination_Controls`, THE `QueueTable` SHALL invoke the `onPageChange` callback with the newly selected page number.

---

### Requirement 2: Page state is managed in each Queue_Component

**User Story:** As a user, I want the queue to load the correct page of results when I navigate, so that I see a fresh set of 20 leads corresponding to the page I selected.

#### Acceptance Criteria

1. THE `TodaysActionQueue` SHALL maintain a `page` state variable initialized to `1`, identical to the pattern already used by the other six Queue_Components.
2. WHEN the `page` state changes in a Queue_Component, THE Queue_Component SHALL pass the new `page` value to the corresponding `Queue_Service` fetch function so the backend receives the updated `page` query parameter.
3. THE React_Query `queryKey` for each Queue_Component SHALL include the current `page` value so that a page change triggers a fresh fetch.
4. WHEN `totalPages` is greater than `1`, THE Queue_Component SHALL pass `page` and `totalPages` down to `QueueTable` via the `page` and `totalPages` props so that `Pagination_Controls` are rendered.
5. WHEN `totalPages` is `1` or less, THE Queue_Component SHALL not pass `page` or `totalPages` props to `QueueTable`, preventing unnecessary pagination UI from rendering.
6. THE Queue_Component SHALL pass a callback to `QueueTable`'s `onPageChange` prop that updates the local `page` state to the value provided by the callback, clamped to the range `[1, totalPages]`.

---

### Requirement 3: Page boundary enforcement

**User Story:** As a user, I want navigation to stay within valid page bounds, so that the app never requests a page that doesn't exist.

#### Acceptance Criteria

1. WHEN `total` is greater than `0`, THE Queue_Component SHALL compute `totalPages` using the formula `Math.ceil(total / per_page)` and treat it as the upper navigation bound.
2. WHEN `total` is `0`, THE Queue_Component SHALL set `totalPages` to `0` and render the empty/no-results state rather than showing a blank first page.
3. WHEN the `onPageChange` callback is invoked with a page number less than `1`, THE Queue_Component SHALL set `page` to `1`.
4. WHEN the `onPageChange` callback is invoked with a page number greater than `totalPages`, THE Queue_Component SHALL set `page` to `totalPages`.
5. WHEN `totalPages` is `1`, THE `QueueTable` SHALL not invoke `onPageChange` regardless of user interaction, because `Pagination_Controls` are not rendered for a single-page result set.

---

### Requirement 4: Page resets after mutating row actions

**User Story:** As a user, I want the queue to return to page 1 after I perform a row action that changes queue membership, so that I am not left on a page that may no longer exist.

#### Acceptance Criteria

1. WHEN a row action in a Queue_Component successfully completes and `queryClient.invalidateQueries` is called, THE Queue_Component SHALL also reset its `page` state to `1`.
2. IF a row action in a Queue_Component fails, THEN THE Queue_Component SHALL leave the `page` state unchanged.

---

### Requirement 5: Pagination controls are consistent across all seven queues

**User Story:** As a user, I want pagination to look and behave identically in every queue, so that I do not need to re-learn navigation when switching queues.

#### Acceptance Criteria

1. THE `NoNextActionQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
2. THE `TodaysActionQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
3. THE `PreviouslyWarmQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
4. THE `FollowUpOverdueQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
5. THE `NeedsReviewQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
6. THE `DoNotContactQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
7. THE `MissingPropertyMatchQueue` SHALL render `Pagination_Controls` via `QueueTable` when `totalPages` is greater than 1.
8. THE `Pagination_Controls` in every Queue_Component SHALL be rendered using the MUI `Pagination` component with `shape="rounded"` and `color="primary"`.

---

### Requirement 6: Page indicator informs the user of position

**User Story:** As a user, I want to know which page I am on and how many pages exist, so that I can plan my navigation through the queue.

#### Acceptance Criteria

1. WHEN `totalPages` is greater than 1, THE `QueueTable` SHALL display a text label reading "Page X of Y" where X is the current page and Y is `totalPages`, positioned above or adjacent to the `Pagination_Controls`.
2. WHEN `total` is 0, THE `QueueTable` SHALL not render the page indicator or `Pagination_Controls`.

---

### Requirement 7: Accessibility of Pagination_Controls

**User Story:** As a user relying on assistive technology, I want the pagination controls to be keyboard-navigable and screen-reader-friendly, so that I can operate all queue views without a mouse.

#### Acceptance Criteria

1. THE `Pagination_Controls` element SHALL include an `aria-label` attribute with the value `"queue pagination"` on its wrapping element so that screen readers can identify it.
2. THE MUI `Pagination` component SHALL render with `aria-label="queue pagination"` so assistive technology can announce it.
3. WHEN the Previous arrow is rendered on page 1 and `totalPages` is greater than 1, THE `Pagination_Controls` SHALL render the Previous arrow in a disabled state so keyboard users receive appropriate feedback.
4. WHEN the Next arrow is rendered on the last page and `totalPages` is greater than 1, THE `Pagination_Controls` SHALL render the Next arrow in a disabled state so keyboard users receive appropriate feedback.
5. WHEN `totalPages` is `1`, THE `Pagination_Controls` SHALL not be rendered, so both arrows are implicitly absent rather than showing disabled controls for a trivially single-page result.
