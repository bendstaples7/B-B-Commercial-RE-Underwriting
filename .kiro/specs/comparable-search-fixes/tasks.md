# Implementation Plan

- [x] 1. Write bug condition exploration tests (BEFORE implementing any fix)
  - **Property 1: Bug Condition** - Stale Date Cutoff Returns Zero Comparables / Step 2 Blocks and Times Out
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fixes when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate both bugs exist
  - **Scoped PBT Approach**: Scope Bug 1 to the concrete failing case — `max_age_months=12` with a real Chicago address that has known sales history between 2022–2024
  - **Bug 1 exploration** (`backend/tests/test_comparable_search_fixes.py`):
    - Call `ComparableSalesFinder.find_comparables(subject, min_count=1, max_age_months=12)` for a known Cook County address
    - Assert `len(result) > 0` — this FAILS on unfixed code because the SoQL date filter (`sale_date >= ~May 2025`) excludes all available records
    - Document counterexample: `find_comparables(..., max_age_months=12)` returns `[]`
    - Also assert that `WorkflowController._execute_comparable_search` forwards `max_age_months=12` (not `MAX_AGE_MONTHS`) — confirms the hardcoded call-site bug
  - **Bug 2 exploration** (`backend/tests/test_comparable_search_fixes.py`):
    - POST to `/api/analysis/{session_id}/step/2` via Flask test client with a mock comparable finder
    - Assert `response.status_code == 202` — this FAILS on unfixed code (returns 200 after blocking)
    - Assert `response.json['status'] == 'accepted'` — also FAILS on unfixed code
    - Document counterexample: route returns 200 and blocks for the full search duration
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — it proves both bugs exist)
  - Document all counterexamples found to confirm root cause analysis
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing any fix)
  - **Property 2: Preservation** - Arm's-Length Filters, Radius Expansion, Steps 3–6 Synchronous, Session State, App Token
  - **IMPORTANT**: Follow observation-first methodology — run UNFIXED code with non-buggy inputs and record actual outputs before writing assertions
  - **Observe on UNFIXED code** (inputs where both `isBugCondition_Bug1` and `isBugCondition_Bug2` return false):
    - Observe: `fetch_comparables` with a cutoff date well before 2024-12-31 (e.g., `max_age_months=36` against a mocked Socrata response with records dated 2022–2024) returns only records passing all arm's-length filters
    - Observe: `find_comparables` stops at the first radius in `[0.25, 0.5, 0.75, 1.0]` that yields `min_count` results
    - Observe: `POST /api/analysis/{session_id}/step/3` (and steps 4, 5, 6) returns HTTP 200 synchronously
    - Observe: `GET /api/analysis/{session_id}` returns `current_step`, `completed_steps`, `step_results`, `subject_property`, `comparables`, `ranked_comparables`, `valuation_result`, `scenarios` in its body
    - Observe: `_socrata_get` sends `X-App-Token` header when `COOK_COUNTY_APP_TOKEN` is set
  - **Write property-based tests** (`backend/tests/test_comparable_search_fixes.py`) capturing observed behavior:
    - **Arm's-length filter property**: Use Hypothesis to generate sale records with random combinations of `is_multisale`, `sale_filter_less_than_10k`, `sale_filter_deed_type` flags and random `sale_date` values between 2022-01-01 and 2024-12-31. Assert only records with all three flags false are returned, for any `max_age_months` value whose cutoff predates the dataset.
    - **Radius expansion property**: Use Hypothesis to generate `min_count` values (1–20) and mock Socrata responses that yield results at different radii. Assert `find_comparables` always stops at the first radius that satisfies `min_count` and never skips or reorders the `[0.25, 0.5, 0.75, 1.0]` sequence.
    - **Steps 3–6 synchronous property**: Use Hypothesis to generate valid session states at each step boundary. Assert `POST /api/analysis/{session_id}/step/{n}` for `n ∈ {3, 4, 5, 6}` always returns HTTP 200 and never returns 202.
    - **Session state property**: Assert `GET /api/analysis/{session_id}` always includes all required fields in its response body.
    - **App token property**: Assert `_socrata_get` includes `X-App-Token` header whenever `COOK_COUNTY_APP_TOKEN` env var is set, regardless of the query parameters.
  - Run all preservation tests on UNFIXED code
  - **EXPECTED OUTCOME**: All preservation tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix Bug 1 — Stale Date Cutoff

  - [x] 3.1 Update `MAX_AGE_MONTHS` constant in `ComparableSalesFinder`
    - In `backend/app/services/comparable_sales_finder.py`, change `MAX_AGE_MONTHS = 12` to `MAX_AGE_MONTHS = 36`
    - This extends the SoQL `sale_date >=` cutoff from ~May 2025 back to ~May 2022, covering the full available Cook County dataset range
    - _Bug_Condition: isBugCondition_Bug1(X) where X.max_age_months=12 and X.request_date is any date in 2025, causing cutoff > COOK_COUNTY_DATASET_MAX_DATE (~2024-12-31)_
    - _Expected_Behavior: fetch_comparables(max_age_months=36) returns len(results) > 0 for any Cook County address with residential sales activity between 2022 and late 2024_
    - _Preservation: All arm's-length filters (sale_type, is_multisale, sale_filter_less_than_10k, sale_filter_deed_type), radius expansion sequence [0.25, 0.5, 0.75, 1.0], and property-type filtering remain unchanged_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.5_

  - [x] 3.2 Update hardcoded call-site in `WorkflowController._execute_comparable_search`
    - In `backend/app/controllers/workflow_controller.py`, replace the literal `max_age_months=12` argument with `max_age_months=ComparableSalesFinder.MAX_AGE_MONTHS`
    - Add `from app.services.comparable_sales_finder import ComparableSalesFinder` import if not already present
    - This ensures the call-site and the class constant stay in sync — a future constant change will not be silently bypassed
    - _Bug_Condition: isBugCondition_Bug1(X) — hardcoded literal 12 at call-site bypasses the class constant_
    - _Expected_Behavior: _execute_comparable_search forwards MAX_AGE_MONTHS (36) to find_comparables_
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 Verify Bug 1 exploration test now passes
    - **Property 1: Expected Behavior** - Extended Lookback Returns Non-Empty Comparables
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - Re-run the exploration test that asserted `len(find_comparables(...)) > 0` and the unit test asserting `_execute_comparable_search` forwards `MAX_AGE_MONTHS` (not literal 12)
    - **EXPECTED OUTCOME**: Bug 1 exploration tests PASS (confirms stale date cutoff is fixed)
    - _Requirements: 2.1, 2.2_

- [x] 4. Fix Bug 2 — Frontend Axios Timeout (Async Step 2)

  - [x] 4.1 Add `loading` column to `AnalysisSession` model
    - In `backend/app/models/analysis_session.py`, add `loading = db.Column(db.Boolean, nullable=False, default=False)`
    - Generate an Alembic migration: `flask db migrate -m "add loading column to analysis_session"` in `backend/`
    - Review the generated migration in `backend/alembic_migrations/versions/` and verify it adds a non-nullable boolean column with default `False`
    - _Bug_Condition: isBugCondition_Bug2(X) where X.step_number=2 — loading field absent prevents frontend from distinguishing "task enqueued" from "task complete" during polling_
    - _Expected_Behavior: AnalysisSession.loading is False by default; set to True when task is enqueued; set back to False when task completes or errors_
    - _Requirements: 2.3, 2.4, 3.4_

  - [x] 4.2 Surface `loading` in `WorkflowController.get_session_state`
    - In `backend/app/controllers/workflow_controller.py`, add `'loading': session.loading` to the state dict returned by `get_session_state`
    - This ensures `GET /api/analysis/{session_id}` includes `loading` in its response body so the frontend polling hook can detect task completion
    - _Expected_Behavior: GET /api/analysis/{session_id} returns loading=true while Celery task is running, loading=false after completion_
    - _Preservation: All existing fields (current_step, completed_steps, step_results, subject_property, comparables, ranked_comparables, valuation_result, scenarios) remain in the response_
    - _Requirements: 2.4, 3.4_

  - [x] 4.3 Add `run_comparable_search_task` Celery task to `celery_worker.py`
    - In `backend/celery_worker.py`, add the `run_comparable_search_task` task following the existing pattern (create_app + app_context inside task body)
    - Task body: query session by `session_id`, call `controller._execute_comparable_search(session)`, update `session.current_step`, `session.step_results`, `session.completed_steps`, set `session.loading = False`, commit
    - Error path: catch all exceptions, set `session.loading = False`, record error in `session.step_results['COMPARABLE_SEARCH_ERROR']`, commit
    - Register task name as `'workflow.run_comparable_search'`
    - _Bug_Condition: isBugCondition_Bug2(X) where X.step_number=2 — no async task exists, so the route must block synchronously_
    - _Expected_Behavior: Task executes comparable search in background, sets loading=False and advances current_step to COMPARABLE_SEARCH on success_
    - _Requirements: 2.3, 2.4, 2.5_

  - [x] 4.4 Make step-2 route return HTTP 202 and enqueue the Celery task
    - In `backend/app/controllers/routes.py`, add a branch in `advance_to_step` for `target_step == WorkflowStep.COMPARABLE_SEARCH`
    - Branch: look up session, validate step 1 is complete, set `session.loading = True`, commit, call `run_comparable_search_task.delay(session_id)`, return `jsonify({'status': 'accepted', 'session_id': session_id}), 202`
    - All other steps (`n ∈ {3, 4, 5, 6}`) continue through the existing synchronous path and return HTTP 200
    - _Bug_Condition: isBugCondition_Bug2(X) where X.step_number=2 — route currently blocks for ~2 minutes, exceeding the 30-second Axios timeout_
    - _Expected_Behavior: POST /api/analysis/{session_id}/step/2 returns HTTP 202 with {"status": "accepted", "session_id": "..."} within the Axios timeout_
    - _Preservation: POST /api/analysis/{session_id}/step/{n} for n ∈ {3,4,5,6} still returns HTTP 200 synchronously_
    - _Requirements: 2.3, 3.3_

  - [x] 4.5 Update `advanceToStep` in `frontend/src/services/api.ts` to handle HTTP 202
    - Update the `advanceToStep` method to check `response.status === 202` and return a pending sentinel value (e.g., `{ status: 'accepted', sessionId }`) instead of `response.data`
    - For all other status codes the existing behavior is unchanged
    - _Expected_Behavior: Frontend receives the 202 response without triggering an Axios error, and the caller can detect the pending state_
    - _Requirements: 2.3_

  - [x] 4.6 Add `loading: boolean` to `AnalysisSession` interface in `frontend/src/types/index.ts`
    - Add `loading: boolean` to the `AnalysisSession` TypeScript interface
    - This field is required for the polling hook to determine when to stop polling
    - _Requirements: 2.4, 3.4_

  - [x] 4.7 Add polling logic to the Step 2 frontend component
    - Locate the component that triggers `advanceToStep` for step 2 (the Step 1 confirmation / "Confirm & Continue" handler)
    - After `advanceToStep` returns a 202 sentinel, enable polling on the session query using TanStack React Query v5:
      ```typescript
      refetchInterval: (query) => query.state.data?.loading ? 5000 : false
      ```
    - Add a `useEffect` that watches `session.loading` and `session.currentStep`:
      - When `!session.loading && session.currentStep === WorkflowStep.COMPARABLE_SEARCH` → call `onStepComplete(session)` to advance the UI
      - When `session.stepResults?.COMPARABLE_SEARCH_ERROR` is set → surface the error message to the user (replace the generic "Network error" with the actual error)
    - Show a loading indicator (spinner or progress message) while `session.loading === true`
    - _Expected_Behavior: Frontend polls every 5 s while loading=true, transitions to Step 2 UI automatically on completion, surfaces backend errors on failure_
    - _Requirements: 2.4, 2.5_

  - [x] 4.8 Verify Bug 2 exploration test now passes
    - **Property 1: Expected Behavior** - Step 2 Returns HTTP 202 Within Timeout
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 assert `response.status_code == 202` and `response.json['status'] == 'accepted'`
    - **EXPECTED OUTCOME**: Bug 2 exploration tests PASS (confirms async route is working)
    - _Requirements: 2.3, 2.4, 2.5_

  - [x] 4.9 Verify preservation tests still pass after Bug 2 fix
    - **Property 2: Preservation** - Steps 3–6 Synchronous, Session State, App Token
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all preservation property tests from task 2
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions from the async change)
    - Confirm steps 3–6 still return HTTP 200, session state still includes all required fields, `X-App-Token` header still sent
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5. Write additional unit and integration tests

  - [x] 5.1 Unit tests for Bug 1 fix
    - Test `CookCountySalesDataSource.fetch_comparables` with `max_age_months=36` against a mocked Socrata response; assert non-empty result
    - Test `CookCountySalesDataSource._fetch_sales_for_pins` with a cutoff date of 2022-01-01; assert the generated SoQL `WHERE` clause contains `sale_date >= '2022-01-01T00:00:00.000'`
    - Test `WorkflowController._execute_comparable_search` uses `MAX_AGE_MONTHS` (not the literal `12`) by patching `ComparableSalesFinder.MAX_AGE_MONTHS` and asserting the patched value is forwarded
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 Unit tests for Bug 2 fix
    - Test `POST /api/analysis/{session_id}/step/2` returns 202 and sets `session.loading = True`
    - Test `POST /api/analysis/{session_id}/step/3` still returns 200 (synchronous path unchanged)
    - Test `run_comparable_search_task` sets `session.loading = False` and advances `session.current_step` to `COMPARABLE_SEARCH` on success
    - Test `run_comparable_search_task` sets `session.loading = False` and records `COMPARABLE_SEARCH_ERROR` in `step_results` on failure (mock `_execute_comparable_search` to raise)
    - Test `GET /api/analysis/{session_id}` includes `loading` in the response body
    - _Requirements: 2.3, 2.4, 2.5, 3.3, 3.4_

  - [x] 5.3 Integration tests
    - **Happy path**: Start a session, confirm property facts (step 1), POST to step 2, assert 202, poll `GET /api/analysis/{session_id}` until `loading=false`, assert `current_step = COMPARABLE_SEARCH` and `comparable_count > 0` (using a mocked Socrata response with 36-month data)
    - **Error path**: Simulate a Celery task failure (mock `_execute_comparable_search` to raise). Assert that `GET /api/analysis/{session_id}` returns `loading=false` and `step_results.COMPARABLE_SEARCH_ERROR` is set
    - **Synchronous steps unaffected**: After step 2 completes, advance through steps 3–6 using the normal synchronous path. Assert each returns HTTP 200 and the session advances correctly
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.3_

- [x] 6. Checkpoint — Ensure all tests pass
  - Run the full backend test suite: `cd backend && pytest -v`
  - Run the frontend test suite: `cd frontend && npm test`
  - Confirm all exploration tests (Property 1) pass — bugs are fixed
  - Confirm all preservation tests (Property 2) pass — no regressions
  - Confirm all unit and integration tests pass
  - Verify the Alembic migration applies cleanly: `flask db upgrade`
  - Ask the user if any questions arise before closing out
