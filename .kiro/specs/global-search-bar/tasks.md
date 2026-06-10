# Implementation Plan: Global Search Bar

## Overview

Implement a global search bar embedded in the MUI AppBar that searches across leads and analysis sessions. The work proceeds in five broad layers: database migration → backend endpoint → frontend types/service → UI component → integration into App.tsx → tests.

## Tasks

- [x] 1. Database migration — enable pg_trgm and add trigram indexes
  - [x] 1.1 Create Alembic migration file `backend/alembic_migrations/versions/<rev_id>_add_search_trigram_indexes.py`
    - Use `op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")` to enable the extension idempotently
    - Add GIN trigram indexes on `leads.owner_first_name`, `leads.owner_last_name`, `leads.property_street` using `CREATE INDEX IF NOT EXISTS ... USING gin(...gin_trgm_ops)`
    - Add GIN trigram index on `property_facts.address` using `CREATE INDEX IF NOT EXISTS`
    - Implement `downgrade()` with `DROP INDEX IF EXISTS` for each index (do NOT drop the extension)
    - Follow the idempotent migration convention — all DDL uses `IF NOT EXISTS` / `IF EXISTS`
    - _Requirements: 9.7 (pg_trgm), 9.8 (LIMIT), 9.9 (response time)_

- [x] 2. Backend search controller
  - [x] 2.1 Create `backend/app/controllers/search_controller.py` with Blueprint and GET /api/search route
    - Define `search_bp = Blueprint('search', __name__)` 
    - Apply `@handle_errors` and `@require_auth` decorators to the route
    - Read and validate `q` from `request.args`: return HTTP 400 with `{"message": "..."}` if missing, trimmed length < 2, or length > 200
    - Read `g.user_id` and `g.is_admin` for ownership scoping — no client-supplied elevation allowed
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 9.5_

  - [x] 2.2 Implement leads SQL query with ownership scoping and relevance ordering
    - Build pattern `f"%{q}%"` and prefix pattern `f"{q}%"` for ordering
    - Execute leads query: ILIKE on `owner_first_name`, `owner_last_name`, `property_street`; ownership filter `(owner_user_id = :user_id OR :is_admin = TRUE)`; exclude `NULL owner_user_id` for regular users; ORDER BY prefix-match rank then `COALESCE(owner_last_name, property_street)`; LIMIT 10
    - Implement `_supports_trgm(db_session)` helper that checks `pg_extension` table; wrap trigram path in try/except to fall back to ILIKE on failure
    - _Requirements: 3.5, 3.7, 3.8, 3.9, 9.1, 9.2, 9.3, 9.6_

  - [x] 2.3 Implement sessions SQL query with ownership scoping and relevance ordering
    - JOIN `analysis_sessions` with `property_facts` on `pf.session_id = a.id`
    - Apply ILIKE on `pf.address`; ownership filter `(a.user_id = :user_id OR :is_admin = TRUE)`; ORDER BY prefix-match rank then `pf.address`; LIMIT 5
    - _Requirements: 3.6, 3.7, 3.8, 3.9, 9.2, 9.4_

  - [x] 2.4 Implement response serialization — label computation and nav_path construction
    - Lead `label` precedence: both name parts → `"{first} {last}"`, one part → that value, neither → `property_street`, all absent → `"Unknown Lead"`
    - Lead `nav_path`: `f"/properties/{id}"`
    - Session `label`: `pf.address` or `"Unknown Address"` if absent
    - Session `nav_path`: `f"/analysis/arv/{session_id}"`
    - Session `status`: derive from `current_step` — `REPORT_GENERATION` with completed step → `"Complete"`, otherwise `"In Progress"`
    - Session `created_at`: ISO 8601 string
    - Return `{"leads": [...], "sessions": [...]}` with HTTP 200 (empty arrays when no matches)
    - _Requirements: 3.10, 3.11, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4_

  - [x] 2.5 Write property test for backend query validation (Properties 4 & 5)
    - **Property 4: Backend rejects queries shorter than 2 characters**
    - **Validates: Requirements 3.3**
    - **Property 5: Backend rejects queries longer than 200 characters**
    - **Validates: Requirements 3.4**
    - Use `@given(q=st.text(max_size=1))` for Property 4 and `@given(q=st.text(min_size=201))` for Property 5
    - Tag each test: `# Feature: global-search-bar, Property 4/5`
    - Use `@settings(max_examples=100)`

  - [x] 2.6 Write property test for search result match correctness (Property 6)
    - **Property 6: Search results match query text**
    - **Validates: Requirements 3.5, 3.6**
    - For any query q and any generated set of leads/sessions, every returned lead contains q (case-insensitive) in at least one of the three name/address fields; every returned session contains q in `pf.address`
    - Use Hypothesis `st.text` strategies to generate q values and seed DB rows

  - [x] 2.7 Write property test for result count caps (Property 7)
    - **Property 7: Result count caps are always respected**
    - **Validates: Requirements 3.8, 4.7**
    - For any query producing more than 10 matching leads and 5 matching sessions, assert `len(response["leads"]) <= 10` and `len(response["sessions"]) <= 5`

  - [x] 2.8 Write property test for response shape (Property 8)
    - **Property 8: Response shape is always valid**
    - **Validates: Requirements 3.10**
    - For any valid query returning 200, assert `leads` and `sessions` arrays present; each lead has `id` (int), `type == "lead"`, non-empty `label`, `nav_path` starting with `/properties/`; each session has `id` (int), `type == "session"`, non-empty `label`, `nav_path` starting with `/analysis/arv/`, ISO 8601 `created_at`

  - [x] 2.9 Write property test for ownership scoping (Property 9)
    - **Property 9: Ownership scoping — regular users see only their own records**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.6**
    - For any regular-user query over a multi-user seeded dataset, assert no returned lead has `owner_user_id != g.user_id` and no returned session has `user_id != g.user_id`; assert NULL `owner_user_id` leads are absent

  - [x] 2.10 Write property test for lead label computation (Property 10)
    - **Property 10: Lead label computation follows precedence**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    - Use `@given` strategies over all combinations of nullable `owner_first_name`, `owner_last_name`, `property_street` to verify label precedence rule is always followed

- [x] 3. Checkpoint — backend wired up and tests passing
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Register search blueprint in app factory
  - [x] 4.1 Register `search_bp` in `backend/app/__init__.py`
    - Add `from app.controllers.search_controller import search_bp` import
    - Call `app.register_blueprint(search_bp, url_prefix='/api')` in `create_app`
    - _Requirements: 3.1_

- [x] 5. Frontend TypeScript types
  - [x] 5.1 Add `SearchResultItem` and `SearchResponse` interfaces to `frontend/src/types/index.ts`
    - `SearchResultItem`: `id: number`, `type: 'lead' | 'session'`, `label: string`, `nav_path: string`, `lead_score?: number | null`, `created_at?: string | null`, `status?: string | null`
    - `SearchResponse`: `leads: SearchResultItem[]`, `sessions: SearchResultItem[]`
    - _Requirements: 3.10_

- [x] 6. Frontend API service method
  - [x] 6.1 Add `searchService` object with `search` method to `frontend/src/services/api.ts`
    - Implement `search(q: string, signal?: AbortSignal): Promise<SearchResponse>` using the existing `api` Axios instance
    - Call `api.get<SearchResponse>('/search', { params: { q }, signal })` and return `response.data`
    - _Requirements: 3.1_

- [x] 7. GlobalSearchBar component
  - [x] 7.1 Create `frontend/src/components/GlobalSearchBar.tsx` — component scaffold and state
    - Define component with state: `query`, `results`, `isLoading`, `error`, `isOpen`, `focusedIndex`, `mobileExpanded`
    - Import and wire `useNavigate`, `useTheme`, `useMediaQuery` (MUI `sm` breakpoint)
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 7.2 Implement debounced search trigger and AbortController request cancellation
    - Use `useRef`/`setTimeout` for 300 ms debounce; cancel previous timeout on each keystroke
    - Create an `AbortController` per request; call `.abort()` when query changes or drops below 2 chars
    - Call `searchService.search(q, signal)` only when trimmed query length ≥ 2; clear results and cancel otherwise
    - Handle `AbortError` silently; set `error` state on all other failures
    - _Requirements: 2.1, 2.2, 5.3_

  - [x] 7.3 Implement desktop input rendering with placeholder and 200-char cap
    - Render MUI `TextField` / `InputBase` with `placeholder="Search leads, addresses…"` when `!useMediaQuery(theme.breakpoints.down('sm'))`
    - Apply `inputProps={{ maxLength: 200 }}` to enforce 200-character hard cap
    - _Requirements: 1.6, 2.5_

  - [x] 7.4 Implement mobile collapsed/expanded state
    - Render icon button (magnifying glass) when below `sm` breakpoint and `!mobileExpanded`
    - On icon click: set `mobileExpanded = true`, auto-focus input
    - On blur with empty query: set `mobileExpanded = false`
    - _Requirements: 1.3, 1.4, 1.5_

  - [x] 7.5 Implement results dropdown — grouped sections, loading, empty, and error states
    - Render MUI `Paper` + `List` below the input when `isOpen`
    - Group results under "Leads" and "Analysis Sessions" `ListSubheader` items; omit a section when its array is empty
    - Show loading spinner (MUI `CircularProgress`) while `isLoading`
    - Show "No results found" when both arrays are empty and not loading
    - Show "Search failed. Please try again." when `error` is set
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 7.6 Implement lead result item rendering (label precedence + score chip)
    - Primary label: follow precedence from `label` field returned by backend (already computed)
    - Secondary text: `property_street` displayed below label (include in result item if returned)
    - Display `lead_score` in a MUI `Chip` when non-null (including 0)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.7 Implement session result item rendering (address, date, status badge)
    - Primary label: property address from `label` field; fall back to "Unknown Address"
    - Secondary text: `created_at` formatted as `MM/DD/YYYY`
    - Display `status` ("In Progress" / "Complete") as a MUI `Chip` or badge
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.8 Implement keyboard navigation (ArrowUp/ArrowDown/Enter/Escape) and click navigation
    - Track `focusedIndex` (-1 = none); ArrowDown increments, ArrowUp decrements, clamped to result list length
    - Apply distinct background style (MUI `selected` or `sx` highlight) to the focused item
    - Enter on focused item OR click on any item: call `navigate(item.nav_path)`, clear query, close dropdown; skip navigation if `nav_path` is absent/empty and show error
    - Escape: clear query, cancel in-flight request, close dropdown, remove focus
    - _Requirements: 2.3, 2.4, 4.8, 4.9, 4.10, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 7.9 Write property test for debounce contract (Property 1)
    - **Property 1: Debounce contract**
    - **Validates: Requirements 2.1**
    - Use `@fast-check/vitest` with fake timers; for any string ≥ 2 chars typed in keystrokes within 300 ms window, assert `searchService.search` called exactly once after advancing timers ≥ 300 ms
    - At least 100 runs (`numRuns: 100`)

  - [x] 7.10 Write property test for short queries never triggering search (Property 2)
    - **Property 2: Short queries never trigger search**
    - **Validates: Requirements 2.2**
    - Use `fc.string({ maxLength: 1 })` for any 0- or 1-character query; assert `searchService.search` never called

  - [x] 7.11 Write property test for input length hard cap (Property 3)
    - **Property 3: Input length hard cap**
    - **Validates: Requirements 2.5**
    - Use `fc.string({ minLength: 201 })` and simulate typing into the input; assert input value length ≤ 200 after each interaction

  - [x] 7.12 Write property test for lead navigation path (Property 11)
    - **Property 11: Lead result navigation targets correct path**
    - **Validates: Requirements 5.1**
    - Use `fc.integer({ min: 1, max: 999999 })` for lead id; render a mock result, click it, assert `navigate` called with `/properties/{id}`

  - [x] 7.13 Write property test for session navigation uses returned nav_path (Property 12)
    - **Property 12: Session result navigation uses returned nav_path**
    - **Validates: Requirements 5.2**
    - Use `fc.string()` for arbitrary `nav_path` values; render mock session result, click it, assert `navigate` called with exactly that `nav_path`

  - [x] 7.14 Write example-based unit tests for GlobalSearchBar
    - Renders icon button on mobile (`useMediaQuery` mocked to `true`); renders text input on desktop
    - Icon button click expands input and focuses it; empty blur collapses mobile input
    - Escape clears query, closes dropdown, removes focus
    - Loading spinner shown while request in flight
    - "No results found" shown on empty arrays
    - "Search failed. Please try again." shown on error
    - Clicking lead result navigates to `/properties/{id}`; clicking session result navigates to `nav_path`
    - Results grouped under "Leads" / "Analysis Sessions" headers; section omitted when empty
    - _Requirements: 1.3, 1.4, 2.3, 2.4, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2_

  - [x] 7.15 Write example-based unit tests for backend search_controller
    - `GET /api/search` with no `q` → 400 with `message`
    - `GET /api/search?q=a` (1 char) → 400
    - Unauthenticated request → 401
    - Valid query with no matching records → 200 `{"leads": [], "sessions": []}`
    - Admin user returns records from multiple users
    - Regular user returns only their own records
    - Lead with `NULL owner_user_id` excluded from regular user results
    - _Requirements: 3.2, 3.3, 3.13, 3.11, 9.1, 9.3, 9.4, 9.6_

- [x] 8. Checkpoint — component complete and all component tests passing
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Integrate GlobalSearchBar into App.tsx AppBar Toolbar
  - [x] 9.1 Insert `<GlobalSearchBar />` into the MUI Toolbar in `frontend/src/App.tsx`
    - Import `GlobalSearchBar` from `@/components/GlobalSearchBar`
    - Change the title `Typography` `sx` from `flexGrow: 1` to `flexGrow: 0, mr: 2` so the search bar can occupy a defined portion
    - Insert `<GlobalSearchBar />` after the title and before the `<Box sx={{ flexGrow: 1 }} />` spacer
    - Ensure layout remains correct at both desktop and mobile breakpoints
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 10. Final checkpoint — end-to-end integration verified
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The migration (task 1.1) is safe on SQLite test environments — `pg_trgm` creation will fail silently because the backend controller falls back to ILIKE when `pg_trgm` is unavailable
- Property-based backend tests run with `cd backend && pytest tests/test_search_controller.py -v`
- Property-based frontend tests run with `cd frontend && npm test -- GlobalSearchBar`
- The `nav_path` for analysis sessions uses `/analysis/arv/{session_id}` — note `session_id` (UUID) not `id` (integer)
- All migration DDL must follow the idempotent convention (`IF NOT EXISTS` / `IF EXISTS`) per `migrations.md`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "6.1"] },
    { "id": 3, "tasks": ["2.4"] },
    { "id": 4, "tasks": ["4.1", "7.1"] },
    { "id": 5, "tasks": ["2.5", "2.6", "2.7", "2.8", "2.9", "2.10", "7.2", "7.15"] },
    { "id": 6, "tasks": ["7.3", "7.4"] },
    { "id": 7, "tasks": ["7.5", "7.6", "7.7"] },
    { "id": 8, "tasks": ["7.8"] },
    { "id": 9, "tasks": ["7.9", "7.10", "7.11", "7.12", "7.13", "7.14"] },
    { "id": 10, "tasks": ["9.1"] }
  ]
}
```
