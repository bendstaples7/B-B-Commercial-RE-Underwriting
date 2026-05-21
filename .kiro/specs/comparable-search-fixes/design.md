# Comparable Search Fixes — Bugfix Design

## Overview

Two bugs make Step 2 (Comparable Search) completely non-functional. Bug 1 is a stale date
cutoff in `CookCountySalesDataSource.fetch_comparables`: the hardcoded `max_age_months=12`
default produces a `sale_date >= ~May 2025` filter, but the Cook County Parcel Sales dataset
(`wvhk-k5uv`) only contains records through ~late 2024, so every query returns 0 results. The
fix is a one-line constant change: raise `MAX_AGE_MONTHS` from 12 to 36 in
`ComparableSalesFinder` and update the matching call-site in `WorkflowController`.

Bug 2 is a frontend timeout: the Axios instance has a 30-second timeout, but the comparable
search can take ~2 minutes across four radius expansions. The fix makes Step 2 asynchronous:
`POST /api/analysis/{session_id}/step/2` enqueues a Celery task and returns HTTP 202
immediately; the frontend polls `GET /api/analysis/{session_id}` until `current_step` advances
to `COMPARABLE_SEARCH` (or an error is detected). Steps 3–6 remain synchronous and are
unaffected.

---

## Glossary

- **Bug_Condition (C)**: The condition that triggers a bug — either a date cutoff that falls
  beyond the dataset's available range (Bug 1), or a step-2 advance request that will exceed
  the Axios timeout (Bug 2).
- **Property (P)**: The desired behavior when the bug condition holds — non-empty comparables
  returned (Bug 1), or an HTTP 202 response received within the timeout (Bug 2).
- **Preservation**: Existing behaviors that must remain unchanged: property-type and radius
  filtering, the 0.25→0.5→0.75→1.0 mile expansion sequence, synchronous handling of Steps
  3–6, session state returned during polling, and the `X-App-Token` header on Socrata requests.
- **`ComparableSalesFinder`**: The service class in
  `backend/app/services/comparable_sales_finder.py` that orchestrates radius expansion and
  delegates to data sources.
- **`CookCountySalesDataSource`**: The inner class in the same file that queries the three Cook
  County Socrata datasets (Parcel Universe, Parcel Sales, Improvement Characteristics).
- **`MAX_AGE_MONTHS`**: The class-level constant on `ComparableSalesFinder` (currently `12`)
  that controls the lookback window passed to every data source.
- **`advance_to_step` route**: `POST /api/analysis/{session_id}/step/<step_number>` in
  `backend/app/controllers/routes.py` — currently synchronous for all steps.
- **`run_comparable_search` task**: The new Celery task to be added to `celery_worker.py` that
  will execute `WorkflowController._execute_comparable_search` in the background.
- **`loading` flag**: A field to be added to `AnalysisSession` (and surfaced in
  `get_session_state`) so the frontend can distinguish "step 2 in progress" from "step 2
  complete" during polling.
- **Polling hook**: A `useQuery` call in the frontend that re-fetches
  `GET /api/analysis/{session_id}` on a fixed interval while `loading` is true.

---

## Bug Details

### Bug 1 — Stale Date Cutoff

The bug manifests whenever `ComparableSalesFinder.find_comparables` is called with the default
`max_age_months=12` (or any value ≤ ~5 months from the current date). The
`CookCountySalesDataSource._fetch_sales_for_pins` method constructs a SoQL `WHERE` clause with
`sale_date >= '<cutoff>'`; when the cutoff is later than the dataset's last record (~late 2024),
the Socrata API returns an empty array for every PIN batch, causing all four radius expansions
to yield 0 results.

**Formal Specification:**

```
FUNCTION isBugCondition_Bug1(X)
  INPUT: X of type ComparableSearchRequest
         (fields: max_age_months: int, request_date: datetime)
  OUTPUT: boolean

  cutoff ← X.request_date - timedelta(days=X.max_age_months * 30)
  RETURN cutoff > COOK_COUNTY_DATASET_MAX_DATE   // ~2024-12-31
END FUNCTION
```

**Examples:**

- Request date 2025-05-15, `max_age_months=12` → cutoff 2024-05-15 → **bug condition holds**
  (dataset has records back to ~2022, but the cutoff is within the dataset range only by
  accident; with the dataset frozen at late 2024, a 12-month window from mid-2025 misses all
  data). Expected: ≥1 comparable returned. Actual: 0 comparables.
- Request date 2025-05-15, `max_age_months=36` → cutoff 2022-05-15 → **bug condition does NOT
  hold** (cutoff is well before the dataset's last record). Expected: ≥1 comparable returned.
  Actual (after fix): ≥1 comparable returned. ✓
- Request date 2024-06-01, `max_age_months=12` → cutoff 2023-06-01 → **bug condition does NOT
  hold** (dataset was live at that time). Behavior must be preserved.

### Bug 2 — Frontend Axios Timeout

The bug manifests when the frontend calls `POST /api/analysis/{session_id}/step/2`. The Axios
instance is configured with `timeout: 30000` (30 s). The comparable search iterates up to four
radius expansions, each making multiple Socrata HTTP calls with a 15-second socket timeout,
giving a worst-case backend duration of ~2 minutes. Axios fires an `ECONNABORTED` error before
the backend responds, which the response interceptor converts to "Network error. Please check
your connection."

**Formal Specification:**

```
FUNCTION isBugCondition_Bug2(X)
  INPUT: X of type StepAdvanceRequest
         (fields: step_number: int, session_id: str)
  OUTPUT: boolean

  RETURN X.step_number = 2
END FUNCTION
```

**Examples:**

- `POST /api/analysis/{id}/step/2` → backend takes ~120 s → Axios times out at 30 s →
  **bug condition holds**. Expected: frontend receives HTTP 202 within 30 s. Actual: network
  error displayed.
- `POST /api/analysis/{id}/step/3` → backend takes <1 s → **bug condition does NOT hold**.
  Synchronous behavior must be preserved.
- `POST /api/analysis/{id}/step/4` → backend takes <1 s → **bug condition does NOT hold**.
  Synchronous behavior must be preserved.

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `CookCountySalesDataSource._fetch_sales_for_pins` must continue to apply the
  `sale_type='LAND AND BUILDING'`, `is_multisale=false`, `sale_filter_less_than_10k=false`,
  and `sale_filter_deed_type=false` arm's-length filters on every Socrata query.
- `ComparableSalesFinder.find_comparables` must continue to expand the search radius through
  the sequence `[0.25, 0.5, 0.75, 1.0]` miles and stop as soon as `min_count` comparables are
  found.
- `ComparableSalesFinder.filter_by_property_type` must continue to restrict results to the
  property type matching the subject property.
- `POST /api/analysis/{session_id}/step/{n}` for `n ∈ {3, 4, 5, 6}` must continue to execute
  synchronously and return HTTP 200 with the full step result.
- `GET /api/analysis/{session_id}` must continue to return `current_step`, `completed_steps`,
  `step_results`, `subject_property`, `comparables`, `ranked_comparables`, `valuation_result`,
  and `scenarios` in its response body.
- `CookCountySalesDataSource._socrata_get` must continue to send the `X-App-Token` header when
  `COOK_COUNTY_APP_TOKEN` is set.

**Scope:**

All inputs where `isBugCondition_Bug1` and `isBugCondition_Bug2` both return false must be
completely unaffected by these fixes. This includes:

- Comparable searches run with a `max_age_months` value whose cutoff date falls before the
  dataset's last record (i.e., any future scenario where the dataset is updated).
- All step advance calls for steps 3–6.
- All `GET /api/analysis/{session_id}` polling calls (read-only, no side effects).
- All Socrata requests — the `X-App-Token` header path is unchanged.

---

## Hypothesized Root Cause

### Bug 1

1. **Frozen dataset, stale constant**: The Cook County Parcel Sales dataset (`wvhk-k5uv`) has
   not been updated since ~late 2024. The `MAX_AGE_MONTHS = 12` constant on
   `ComparableSalesFinder` was set when the dataset was current; it now produces a cutoff date
   that is entirely beyond the dataset's available range.
   - The constant is used as the default in `find_comparables(max_age_months=MAX_AGE_MONTHS)`
     and passed directly to `CookCountySalesDataSource.fetch_comparables`.
   - The call-site in `WorkflowController._execute_comparable_search` also hardcodes
     `max_age_months=12`, bypassing the class constant.

2. **No fallback or staleness detection**: There is no logic to detect that the dataset is
   frozen and widen the window automatically. The fix is a deliberate constant change to 36
   months, which covers the full available dataset range.

### Bug 2

1. **Synchronous long-running route**: `advance_to_step` in `routes.py` calls
   `workflow_controller.advance_to_step(...)` synchronously inside the Flask request handler.
   For step 2, this blocks the HTTP connection for the full duration of the comparable search
   (~2 minutes), which exceeds the Axios 30-second timeout.

2. **No per-request timeout override**: The Axios instance has a single global `timeout:
   30000`. There is no per-call override for the step-2 advance, and no mechanism to signal
   the frontend that the operation is long-running.

3. **Celery already available**: The project already uses Celery with a Redis broker for bulk
   lead rescoring and import jobs. The comparable search task can follow the same pattern
   (`create_app()` + `app_context()` inside the task body).

4. **`loading` field absent from session model**: The `AnalysisSession` model has no `loading`
   boolean. Adding one allows the polling endpoint to distinguish "task enqueued, not yet
   complete" from "task complete" without the frontend having to infer state from step numbers
   alone.

---

## Correctness Properties

Property 1: Bug Condition — Extended Lookback Returns Results

_For any_ `ComparableSearchRequest` where `isBugCondition_Bug1` returns true (i.e., the
12-month cutoff falls beyond the dataset's last record), the fixed
`CookCountySalesDataSource.fetch_comparables` — called with `max_age_months=36` — SHALL return
a non-empty list of comparable sales for any Cook County address that has had residential sales
activity between 2022 and late 2024.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition — Step 2 Returns HTTP 202 Within Timeout

_For any_ `StepAdvanceRequest` where `isBugCondition_Bug2` returns true (i.e., `step_number =
2`), the fixed `POST /api/analysis/{session_id}/step/2` endpoint SHALL return an HTTP 202
response with a `{"status": "accepted", "session_id": "..."}` body, and that response SHALL
arrive at the frontend within the 30-second Axios timeout.

**Validates: Requirements 2.3, 2.4, 2.5**

Property 3: Preservation — Non-Buggy Comparable Searches Unchanged

_For any_ `ComparableSearchRequest` where `isBugCondition_Bug1` returns false (i.e., the
cutoff date falls within the dataset's available range), the fixed
`CookCountySalesDataSource.fetch_comparables` SHALL produce the same result as the original
function, preserving all property-type filtering, arm's-length filtering, and radius expansion
behavior.

**Validates: Requirements 3.1, 3.2, 3.5**

Property 4: Preservation — Steps 3–6 Remain Synchronous

_For any_ `StepAdvanceRequest` where `isBugCondition_Bug2` returns false (i.e., `step_number ∈
{3, 4, 5, 6}`), the fixed `POST /api/analysis/{session_id}/step/{n}` endpoint SHALL behave
exactly as before — executing synchronously and returning HTTP 200 with the full step result.

**Validates: Requirements 3.3**

Property 5: Preservation — Session State Returned During Polling

_For any_ `GET /api/analysis/{session_id}` request made while the async comparable search is
in progress, the endpoint SHALL return the current session state including `current_step`,
`loading`, and any available `subject_property` facts, so the frontend can display progress.

**Validates: Requirements 3.4**

---

## Fix Implementation

### Bug 1 — Changes Required

**File**: `backend/app/services/comparable_sales_finder.py`

**Change 1 — Update the class constant:**

```python
# Before
MAX_AGE_MONTHS = 12

# After
MAX_AGE_MONTHS = 36
```

**File**: `backend/app/controllers/workflow_controller.py`

**Change 2 — Update the hardcoded call-site in `_execute_comparable_search`:**

```python
# Before
comparables_data = self.comparable_finder.find_comparables(
    subject=session.subject_property,
    min_count=10,
    max_age_months=12
)

# After
comparables_data = self.comparable_finder.find_comparables(
    subject=session.subject_property,
    min_count=10,
    max_age_months=ComparableSalesFinder.MAX_AGE_MONTHS
)
```

This ensures the call-site and the class constant stay in sync. No other logic changes are
needed for Bug 1.

---

### Bug 2 — Changes Required

**File**: `backend/app/models/analysis_session.py`

**Change 3 — Add `loading` column to `AnalysisSession`:**

```python
loading = db.Column(db.Boolean, nullable=False, default=False)
```

A new Alembic migration must be generated to add this column.

**File**: `backend/app/controllers/workflow_controller.py`

**Change 4 — Surface `loading` in `get_session_state`:**

```python
state = {
    ...
    'loading': session.loading,
    ...
}
```

**File**: `backend/celery_worker.py`

**Change 5 — Add `run_comparable_search` Celery task:**

```python
@celery.task(name='workflow.run_comparable_search')
def run_comparable_search_task(session_id: str) -> dict:
    from app import create_app
    from app.controllers.workflow_controller import WorkflowController
    from app.models import AnalysisSession
    from app.models.analysis_session import WorkflowStep
    from app import db

    app = create_app()
    with app.app_context():
        controller = WorkflowController()
        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        if not session:
            return {'error': 'session not found'}
        try:
            result = controller._execute_comparable_search(session)
            # Record completion
            completed_steps = list(session.completed_steps or [])
            if WorkflowStep.PROPERTY_FACTS.name not in completed_steps:
                completed_steps.append(WorkflowStep.PROPERTY_FACTS.name)
            completed_steps_updated = completed_steps
            step_results = dict(session.step_results or {})
            step_results[WorkflowStep.COMPARABLE_SEARCH.name] = result
            session.completed_steps = completed_steps_updated
            session.step_results = step_results
            session.current_step = WorkflowStep.COMPARABLE_SEARCH
            session.loading = False
            session.updated_at = datetime.utcnow()
            db.session.commit()
            return result
        except Exception as exc:
            session.loading = False
            session.step_results = {
                **(session.step_results or {}),
                'COMPARABLE_SEARCH_ERROR': str(exc),
            }
            db.session.commit()
            return {'error': str(exc)}
```

**File**: `backend/app/controllers/routes.py`

**Change 6 — Make the step-2 route return HTTP 202 and enqueue the task:**

```python
@api_bp.route('/analysis/<session_id>/step/<int:step_number>', methods=['POST'])
@limiter.limit("20 per minute")
@handle_errors
def advance_to_step(session_id, step_number):
    schema = AdvanceStepSchema()
    data = schema.load(request.get_json() or {})

    try:
        target_step = WorkflowStep(step_number)
    except ValueError:
        return jsonify({'error': 'Invalid step number', 'message': 'Step number must be between 1 and 6'}), 400

    # Step 2 is async — enqueue and return 202 immediately
    if target_step == WorkflowStep.COMPARABLE_SEARCH:
        from app.models import AnalysisSession
        from celery_worker import run_comparable_search_task

        session = AnalysisSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        # Validate step 1 is complete before accepting
        workflow_controller._validate_step_completion(session, WorkflowStep.PROPERTY_FACTS)

        session.loading = True
        session.updated_at = datetime.utcnow()
        db.session.commit()

        run_comparable_search_task.delay(session_id)

        logger.info(f"Enqueued comparable search for session {session_id}")
        return jsonify({'status': 'accepted', 'session_id': session_id}), 202

    # All other steps remain synchronous
    result = workflow_controller.advance_to_step(
        session_id=session_id,
        target_step=target_step,
        approval_data=data.get('approval_data')
    )
    logger.info(f"Advanced session {session_id} to step {target_step.name}")
    return jsonify(result), 200
```

**File**: `frontend/src/services/api.ts`

**Change 7 — Update `advanceToStep` to handle HTTP 202 for step 2:**

```typescript
advanceToStep: async (
  sessionId: string,
  stepNumber: number,
  approvalData?: Record<string, any>
): Promise<StepResult> => {
  const response = await api.post<StepResult>(
    `/analysis/${sessionId}/step/${stepNumber}`,
    { approval_data: approvalData }
  )
  // Step 2 returns 202 Accepted — treat as a pending result
  if (response.status === 202) {
    return { status: 'accepted', sessionId } as unknown as StepResult
  }
  return response.data
},
```

**File**: `frontend/src/types/index.ts`

**Change 8 — Add `loading` to `AnalysisSession`:**

```typescript
export interface AnalysisSession {
  // ... existing fields ...
  loading: boolean
}
```

**Frontend component (wherever Step 2 is triggered)**

**Change 9 — Add polling logic using TanStack React Query v5:**

```typescript
// After firing advanceToStep for step 2, enable polling on the session query
const { data: session } = useQuery({
  queryKey: ['session', sessionId],
  queryFn: () => analysisService.getSession(sessionId),
  // Poll every 5 seconds while loading is true
  refetchInterval: (query) =>
    query.state.data?.loading ? 5000 : false,
})

// Detect completion or error
useEffect(() => {
  if (!session) return
  if (!session.loading && session.currentStep === WorkflowStep.COMPARABLE_SEARCH) {
    // Step 2 complete — advance UI
    onStepComplete(session)
  }
  if (session.stepResults?.COMPARABLE_SEARCH_ERROR) {
    // Surface error to user
    setError(session.stepResults.COMPARABLE_SEARCH_ERROR)
  }
}, [session])
```

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate each bug on unfixed code, then verify the fix works correctly and preserves
existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fixes.
Confirm or refute the root cause analysis.

**Bug 1 — Test Plan**: Call `CookCountySalesDataSource.fetch_comparables` (or
`ComparableSalesFinder.find_comparables`) with `max_age_months=12` against a known Cook County
address and assert that the result is non-empty. This test will fail on unfixed code, confirming
the stale cutoff root cause.

**Bug 1 — Test Cases**:
1. **12-month cutoff returns empty** (will fail on unfixed code): Call
   `find_comparables(subject, min_count=1, max_age_months=12)` for a Chicago address with known
   sales history. Assert `len(result) > 0`. Expected counterexample: empty list returned.
2. **36-month cutoff returns results** (will pass after fix): Same call with
   `max_age_months=36`. Assert `len(result) > 0`.

**Bug 2 — Test Plan**: Call `POST /api/analysis/{session_id}/step/2` via the Flask test client
and assert the response status is 202 and arrives immediately. On unfixed code this will either
time out or return 200 after a long delay.

**Bug 2 — Test Cases**:
1. **Step 2 returns 202** (will fail on unfixed code): POST to step 2 with a mock comparable
   finder. Assert `response.status_code == 202` and `response.json['status'] == 'accepted'`.
2. **Step 2 enqueues Celery task** (will fail on unfixed code): Assert that
   `run_comparable_search_task.delay` was called with the correct `session_id`.
3. **Steps 3–6 still return 200** (must pass on both unfixed and fixed code): POST to steps
   3–6. Assert `response.status_code == 200`.

**Expected Counterexamples**:
- Bug 1: `find_comparables` returns `[]` with `max_age_months=12` because the SoQL date filter
  excludes all available records.
- Bug 2: `advance_to_step` route returns 200 (not 202) and blocks for the full search duration.

---

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed functions produce
the expected behavior.

**Pseudocode:**

```
// Bug 1
FOR ALL X WHERE isBugCondition_Bug1(X) DO
  results ← CookCountySalesDataSource.fetch_comparables'(X)  // max_age_months=36
  ASSERT length(results) > 0
END FOR

// Bug 2
FOR ALL X WHERE isBugCondition_Bug2(X) DO
  response ← POST /api/analysis/{X.session_id}/step/2'
  ASSERT response.status = 202
  ASSERT response.json.status = 'accepted'
  ASSERT response arrives within AXIOS_TIMEOUT (30 s)
END FOR
```

---

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed functions
produce the same result as the original functions.

**Pseudocode:**

```
// Bug 1
FOR ALL X WHERE NOT isBugCondition_Bug1(X) DO
  ASSERT CookCountySalesDataSource.fetch_comparables(X)
       = CookCountySalesDataSource.fetch_comparables'(X)
END FOR

// Bug 2
FOR ALL X WHERE NOT isBugCondition_Bug2(X) DO
  ASSERT advance_to_step_original(X) = advance_to_step_fixed(X)
  // i.e., steps 3–6 still return HTTP 200 synchronously
END FOR
```

**Testing Approach**: Property-based testing is recommended for Bug 1 preservation checking
because the date arithmetic interacts with the radius expansion loop in non-obvious ways.
Hypothesis can generate many `(max_age_months, radius, property_type)` combinations and verify
that the filtering and deduplication logic is unchanged.

**Preservation Test Cases**:
1. **Arm's-length filters preserved**: Verify that sales with `is_multisale=true` or
   `sale_filter_less_than_10k=true` are still excluded after the `max_age_months` change.
2. **Radius expansion sequence preserved**: Verify that `find_comparables` still stops at the
   first radius that yields `min_count` results, using the same `[0.25, 0.5, 0.75, 1.0]`
   sequence.
3. **Property-type filter preserved**: Verify that single-family searches still exclude
   multi-family class codes (203–208) and vice versa.
4. **Steps 3–6 synchronous**: Verify that advancing to steps 3, 4, 5, and 6 still returns
   HTTP 200 with a full result body.
5. **Session state during polling**: Verify that `GET /api/analysis/{session_id}` returns
   `loading=true` while the Celery task is running and `loading=false` after completion.
6. **`X-App-Token` header preserved**: Verify that `_socrata_get` still sends the
   `X-App-Token` header when `COOK_COUNTY_APP_TOKEN` is set.

---

### Unit Tests

- Test `CookCountySalesDataSource.fetch_comparables` with `max_age_months=36` against a mocked
  Socrata response; assert non-empty result.
- Test `CookCountySalesDataSource._fetch_sales_for_pins` with a cutoff date of 2022-01-01;
  assert the generated SoQL `WHERE` clause contains `sale_date >= '2022-01-01T00:00:00.000'`.
- Test `WorkflowController._execute_comparable_search` uses `MAX_AGE_MONTHS` (not the literal
  `12`) by patching `ComparableSalesFinder.MAX_AGE_MONTHS` and asserting the patched value is
  forwarded.
- Test `POST /api/analysis/{session_id}/step/2` returns 202 and sets `session.loading = True`.
- Test `POST /api/analysis/{session_id}/step/3` still returns 200 (synchronous path unchanged).
- Test `run_comparable_search_task` sets `session.loading = False` and advances
  `session.current_step` to `COMPARABLE_SEARCH` on success.
- Test `run_comparable_search_task` sets `session.loading = False` and records an error key in
  `step_results` on failure.
- Test `GET /api/analysis/{session_id}` includes `loading` in the response body.

### Property-Based Tests

- **Bug 1 fix checking**: Generate random Cook County–style PIN lists and sale records with
  `sale_date` values between 2022-01-01 and 2024-12-31. Assert that
  `fetch_comparables(max_age_months=36)` returns all records whose `sale_date` falls within the
  36-month window.
- **Bug 1 preservation — date filter**: Generate `(sale_date, max_age_months)` pairs where
  `max_age_months` is large enough that the cutoff predates the dataset. Assert that the set of
  returned PINs is identical between the original and fixed implementations.
- **Bug 1 preservation — arm's-length filters**: Generate sale records with random combinations
  of `is_multisale`, `sale_filter_less_than_10k`, and `sale_filter_deed_type` flags. Assert
  that only records with all three flags false are returned, regardless of `max_age_months`.
- **Bug 2 preservation — steps 3–6**: Generate random valid session states at each step
  boundary. Assert that `POST /api/analysis/{session_id}/step/{n}` for `n ∈ {3, 4, 5, 6}`
  always returns HTTP 200 and never returns 202.

### Integration Tests

- End-to-end: Start a session, confirm property facts (step 1), POST to step 2, assert 202,
  poll `GET /api/analysis/{session_id}` until `loading=false`, assert `current_step =
  COMPARABLE_SEARCH` and `comparable_count > 0` (using a mocked Socrata response with 36-month
  data).
- Error path: Simulate a Celery task failure (mock `_execute_comparable_search` to raise).
  Assert that `GET /api/analysis/{session_id}` returns `loading=false` and
  `step_results.COMPARABLE_SEARCH_ERROR` is set.
- Synchronous steps unaffected: After step 2 completes, advance through steps 3–6 using the
  normal synchronous path. Assert each returns HTTP 200 and the session advances correctly.
