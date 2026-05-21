# Bugfix Requirements Document

## Introduction

Two related bugs prevent the comparable sales search from working end-to-end. Bug 1 causes the
Cook County Socrata query to return 0 results because the date cutoff (`datetime.now() - 12 months`)
falls entirely beyond the dataset's available data range (last updated through ~late 2024). Bug 2
causes the frontend to display "Network error. Please check your connection." because the Axios
instance has a 30-second timeout and the comparable search takes ~2 minutes to complete across up
to four radius expansions. Together these bugs make Step 2 (Comparable Search) completely
non-functional: the backend finds nothing, and the frontend never sees a successful response even
when the backend does succeed.

---

## Bug Analysis

### Current Behavior (Defect)

**Bug 1 — Zero comparables returned (stale date cutoff)**

1.1 WHEN the comparable search runs and `max_age_months` is 12, THEN the system queries the Cook
County Parcel Sales dataset (`wvhk-k5uv`) with `sale_date >= '<~12 months ago>'`, which resolves to
approximately May 2025, and the system returns 0 sales because the dataset contains no records
after ~late 2024.

1.2 WHEN all four radius expansions (0.25, 0.5, 0.75, 1.0 miles) are exhausted with a 12-month
cutoff, THEN the system returns an empty comparables list to the workflow controller.

**Bug 2 — Frontend "Network error" on comparable search**

1.3 WHEN the user clicks "Confirm & Continue" on Step 1 and the frontend calls
`POST /api/analysis/{session_id}/step/2`, THEN the Axios instance times out after 30 seconds and
the frontend displays "Network error. Please check your connection." even though the backend
continues processing and completes successfully ~2 minutes later.

1.4 WHEN the Axios timeout fires before the backend responds, THEN the frontend sets an error state
and the user sees a failure message with no way to recover without refreshing the page, even though
the backend session has advanced to Step 2 successfully.

---

### Expected Behavior (Correct)

**Bug 1 — Zero comparables returned (stale date cutoff)**

2.1 WHEN the comparable search runs, THEN the system SHALL use a lookback window long enough to
reach data that exists in the Cook County dataset (e.g., 36 months), so that the `sale_date`
filter includes sales from 2022 through late 2024 and returns results.

2.2 WHEN all four radius expansions are exhausted with the extended lookback window, THEN the
system SHALL return a non-empty comparables list for any Cook County address that has had
residential sales activity in the past 3 years.

**Bug 2 — Frontend "Network error" on comparable search**

2.3 WHEN the user clicks "Confirm & Continue" on Step 1, THEN the system SHALL fire the
`POST /api/analysis/{session_id}/step/2` request and immediately return a pending/accepted
response to the frontend (HTTP 202), so the Axios timeout is never reached.

2.4 WHEN the backend comparable search is running asynchronously, THEN the frontend SHALL poll
`GET /api/analysis/{session_id}` at a regular interval to detect when the session advances to
Step 2, and SHALL transition the UI to Step 2 automatically upon detecting completion.

2.5 WHEN the backend comparable search fails or the session enters an error state, THEN the
frontend SHALL surface the error to the user after detecting it via polling, rather than showing
a generic network error.

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the comparable search returns results, THEN the system SHALL CONTINUE TO filter sales by
property type, arm's-length flags, and radius so that only valid residential comparables matching
the subject property type are returned.

3.2 WHEN the comparable search returns results, THEN the system SHALL CONTINUE TO expand the
search radius through the sequence 0.25 → 0.5 → 0.75 → 1.0 miles and stop as soon as
`min_count` comparables are found.

3.3 WHEN the user advances through other workflow steps (Steps 3–6), THEN the system SHALL
CONTINUE TO use the same synchronous `advanceToStep` call pattern for those steps, as they
complete quickly and do not require async handling.

3.4 WHEN the session is polled during the async comparable search, THEN the system SHALL CONTINUE
TO return the current session state (including `current_step`, `loading`, and any available
property facts) so the frontend can display progress to the user.

3.5 WHEN the Cook County app token (`COOK_COUNTY_APP_TOKEN`) is configured, THEN the system SHALL
CONTINUE TO send it as the `X-App-Token` header on all Socrata requests to maintain the higher
rate limit.

---

## Bug Condition Pseudocode

### Bug 1 — Stale Date Cutoff

```pascal
FUNCTION isBugCondition_Bug1(X)
  INPUT: X of type ComparableSearchRequest
  OUTPUT: boolean

  cutoff ← datetime.now() - timedelta(days=X.max_age_months * 30)
  RETURN cutoff > COOK_COUNTY_DATASET_MAX_DATE   // ~late 2024
END FUNCTION

// Property: Fix Checking — Extended Lookback
FOR ALL X WHERE isBugCondition_Bug1(X) DO
  results ← CookCountySalesDataSource.fetch_comparables'(X)
  ASSERT length(results) > 0   // at least one sale found within the extended window
END FOR

// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition_Bug1(X) DO
  ASSERT CookCountySalesDataSource.fetch_comparables(X)
       = CookCountySalesDataSource.fetch_comparables'(X)
END FOR
```

### Bug 2 — Frontend Timeout

```pascal
FUNCTION isBugCondition_Bug2(X)
  INPUT: X of type StepAdvanceRequest
  OUTPUT: boolean

  RETURN X.step_number = 2   // only step 2 triggers the long-running comparable search
END FUNCTION

// Property: Fix Checking — Async Step Advance
FOR ALL X WHERE isBugCondition_Bug2(X) DO
  response ← POST /api/analysis/{X.session_id}/step/2'
  ASSERT response.status = 202   // accepted immediately, not after ~2 minutes
  ASSERT response arrives within AXIOS_TIMEOUT
END FOR

// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition_Bug2(X) DO
  ASSERT advanceToStep(X) behaves synchronously as before
END FOR
```
