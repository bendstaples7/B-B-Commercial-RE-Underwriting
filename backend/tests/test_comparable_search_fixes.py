"""
Bug condition exploration tests for comparable-search-fixes spec.

Task 1: Write bug condition exploration tests (BEFORE implementing any fix)

These tests encode the EXPECTED (correct) behavior. They are EXPECTED TO FAIL
on unfixed code — failure confirms the bugs exist.

Bug 1 — Stale Date Cutoff:
  MAX_AGE_MONTHS = 12 on ComparableSalesFinder produces a SoQL cutoff of
  ~May 2025, but the Cook County Parcel Sales dataset (wvhk-k5uv) only has
  records through ~late 2024.  Every query returns 0 results.

  Call-site bug: WorkflowController._execute_comparable_search hardcodes
  max_age_months=12 instead of using ComparableSalesFinder.MAX_AGE_MONTHS,
  so even if the constant is fixed the call-site would bypass it.

Bug 2 — Frontend Axios Timeout:
  POST /api/analysis/{session_id}/step/2 executes synchronously, blocking
  for ~2 minutes.  The Axios instance has a 30-second timeout, so the
  frontend always sees a network error.  The route should return HTTP 202
  immediately and enqueue the work asynchronously.

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""
import inspect
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from app.services.comparable_sales_finder import (
    ComparableSalesFinder,
    CookCountySalesDataSource,
)
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType
from app.models.analysis_session import WorkflowStep


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_chicago_subject(
    lat: float = 41.8781,
    lon: float = -87.6298,
    property_type: PropertyType = PropertyType.SINGLE_FAMILY,
) -> PropertyFacts:
    """Return a PropertyFacts instance for a known Chicago address."""
    subject = PropertyFacts()
    subject.address = "2315 W Arthington St, Chicago, IL 60612"
    subject.property_type = property_type
    subject.latitude = lat
    subject.longitude = lon
    return subject


def _make_sale_row(
    pin: str,
    sale_date: str,
    sale_price: int = 300_000,
    prop_class: str = "202",
) -> dict:
    return {
        "pin": pin,
        "sale_date": sale_date,
        "sale_price": str(sale_price),
        "class": prop_class,
    }


def _make_bbox_row(pin: str, lat: float, lon: float) -> dict:
    return {"pin": pin, "lat": str(lat), "lon": str(lon)}


def _make_chars_row(pin: str) -> dict:
    return {
        "pin": pin,
        "bldg_sf": "1400",
        "beds": "3",
        "fbath": "1",
        "hbath": "1",
        "age": "40",
        "ext_wall": "3",
        "apts": "1",
    }


# ---------------------------------------------------------------------------
# Bug 1 Exploration — Stale Date Cutoff Returns Zero Comparables
# ---------------------------------------------------------------------------

class TestBug1StaleDataCutoffExploration:
    """
    Bug condition exploration for Bug 1.

    The Cook County Parcel Sales dataset was last updated ~late 2024.
    With MAX_AGE_MONTHS = 12 and a request date in mid-2025, the SoQL
    cutoff is ~May 2025 — entirely beyond the dataset's available range.
    Every query returns 0 results.

    These tests call the REAL ComparableSalesFinder with a mocked Socrata
    layer that returns realistic 2022–2024 sale records.  The mock simulates
    the dataset as it actually exists: records only up to late 2024.

    Expected outcome on UNFIXED code:
      - find_comparables(..., max_age_months=12) returns [] because the
        SoQL date filter excludes all available records.

    Validates: Requirements 1.1, 1.2
    """

    # A known Cook County PIN near the subject address
    _PIN = "16233090190000"

    # Sales that exist in the dataset — all dated 2022–2024
    _DATASET_SALES = [
        ("2024-11-01T00:00:00.000", 310_000),
        ("2024-06-15T00:00:00.000", 295_000),
        ("2023-09-20T00:00:00.000", 280_000),
        ("2022-03-10T00:00:00.000", 260_000),
    ]

    def _make_socrata_mock(self, max_age_months: int):
        """
        Return a fake _socrata_get that simulates the Cook County dataset.

        The dataset contains sales only up to 2024-12-31.  The mock applies
        the same date filter that the real Socrata API would apply: it only
        returns rows whose sale_date is >= the cutoff derived from
        max_age_months.

        With max_age_months=12 and a 2025 request date, the cutoff is
        ~May 2025 → no rows pass the filter → empty list returned.
        With max_age_months=36, the cutoff is ~May 2022 → rows from 2022–2024
        pass the filter → non-empty list returned.
        """
        cutoff = datetime.now() - timedelta(days=max_age_months * 30)

        def fake_socrata_get(url: str):
            if "pabr-t5kh" in url:
                # Parcel Universe — always return the PIN with coordinates
                return [_make_bbox_row(self._PIN, 41.8781, -87.6298)]

            if "wvhk-k5uv" in url:
                # Parcel Sales — simulate the dataset's date filter
                rows = []
                for sale_date_str, price in self._DATASET_SALES:
                    sale_dt = datetime.fromisoformat(sale_date_str.replace("T00:00:00.000", ""))
                    if sale_dt >= cutoff:
                        rows.append(_make_sale_row(self._PIN, sale_date_str, price))
                return rows

            if "bcnq-qi2z" in url:
                # Improvement Characteristics — always return data
                return [_make_chars_row(self._PIN)]

            return []

        return fake_socrata_get

    def test_bug1_12_month_cutoff_returns_empty_list(self):
        """
        Fix verification: find_comparables with MAX_AGE_MONTHS (now 36) returns
        non-empty results because the SoQL date filter (~May 2022) is well within
        the Cook County dataset range (records through ~late 2024).

        Previously FAILED on unfixed code (MAX_AGE_MONTHS=12 produced a cutoff
        of ~May 2025, beyond the dataset's last record).
        Counterexample documented: find_comparables(..., max_age_months=12) == []

        After fix: MAX_AGE_MONTHS=36 → cutoff ~May 2022 → results returned.

        Validates: Requirements 2.1, 2.2
        """
        subject = _make_chicago_subject()
        finder = ComparableSalesFinder()

        with patch.object(
            CookCountySalesDataSource,
            "_socrata_get",
            side_effect=self._make_socrata_mock(max_age_months=ComparableSalesFinder.MAX_AGE_MONTHS),
        ):
            result = finder.find_comparables(
                subject=subject,
                min_count=1,
                max_age_months=ComparableSalesFinder.MAX_AGE_MONTHS,
            )

        # EXPECTED BEHAVIOR (passes on fixed code):
        # MAX_AGE_MONTHS=36 produces a cutoff of ~May 2022, which is well
        # before the dataset's last record (~late 2024), so results are returned.
        assert len(result) > 0, (
            f"find_comparables(max_age_months={ComparableSalesFinder.MAX_AGE_MONTHS}) "
            f"returned [] — the fix to MAX_AGE_MONTHS=36 did not produce results. "
            f"Cutoff: ~{(datetime.now() - timedelta(days=ComparableSalesFinder.MAX_AGE_MONTHS*30)).strftime('%Y-%m-%d')}. "
            "Expected non-empty results for a Cook County address with 2022–2024 sales history."
        )

    def test_bug1_call_site_hardcodes_12_not_max_age_months_constant(self):
        """
        Call-site bug: WorkflowController._execute_comparable_search passes
        max_age_months=12 as a literal integer instead of using
        ComparableSalesFinder.MAX_AGE_MONTHS.

        This means even if MAX_AGE_MONTHS is updated to 36, the call-site
        will still pass 12 until it is also fixed.

        EXPECTED TO FAIL on unfixed code (the source code contains the
        literal '12' at the call-site).

        Validates: Requirements 1.1, 1.2
        """
        from app.controllers.workflow_controller import WorkflowController
        import inspect

        source = inspect.getsource(WorkflowController._execute_comparable_search)

        # The call-site should NOT contain the literal integer 12 as the
        # max_age_months argument.  After the fix it should reference
        # ComparableSalesFinder.MAX_AGE_MONTHS.
        #
        # We check that the string 'max_age_months=12' does NOT appear in
        # the method source — if it does, the hardcoded call-site bug exists.
        assert "max_age_months=12" not in source, (
            "COUNTEREXAMPLE DOCUMENTED: WorkflowController._execute_comparable_search "
            "contains 'max_age_months=12' as a hardcoded literal. "
            "This bypasses ComparableSalesFinder.MAX_AGE_MONTHS and means a "
            "constant change alone will not fix the call-site. "
            "Fix: replace with max_age_months=ComparableSalesFinder.MAX_AGE_MONTHS."
        )

    def test_bug1_max_age_months_constant_is_stale(self):
        """
        Confirm that ComparableSalesFinder.MAX_AGE_MONTHS is currently 12,
        which is the root cause of the stale date cutoff.

        EXPECTED TO FAIL on unfixed code (constant is 12, not 36).

        Validates: Requirements 1.1
        """
        # The fix changes MAX_AGE_MONTHS from 12 to 36.
        # This test documents the current (buggy) value.
        assert ComparableSalesFinder.MAX_AGE_MONTHS == 36, (
            f"COUNTEREXAMPLE DOCUMENTED: ComparableSalesFinder.MAX_AGE_MONTHS = "
            f"{ComparableSalesFinder.MAX_AGE_MONTHS} (expected 36 after fix). "
            f"With MAX_AGE_MONTHS=12 and a 2025 request date, the SoQL cutoff is "
            f"~{(datetime.now() - timedelta(days=12*30)).strftime('%Y-%m-%d')}, "
            f"which is beyond the Cook County dataset's last record (~2024-12-31). "
            f"Fix: change MAX_AGE_MONTHS = 12 to MAX_AGE_MONTHS = 36."
        )


# ---------------------------------------------------------------------------
# Bug 2 Exploration — Step 2 Route Blocks and Returns 200 Instead of 202
# ---------------------------------------------------------------------------

class TestBug2SynchronousStep2Exploration:
    """
    Bug condition exploration for Bug 2.

    POST /api/analysis/{session_id}/step/2 currently calls
    workflow_controller.advance_to_step(...) synchronously inside the Flask
    request handler.  For step 2 this blocks for ~2 minutes (four radius
    expansions × Socrata HTTP calls), exceeding the Axios 30-second timeout.

    The fix makes step 2 asynchronous: the route enqueues a Celery task and
    returns HTTP 202 immediately.

    These tests use the Flask test client with a mocked comparable finder
    so they complete quickly without real HTTP calls.

    Expected outcome on UNFIXED code:
      - response.status_code == 200 (not 202)
      - response.json['status'] != 'accepted'

    Validates: Requirements 1.3, 1.4
    """

    def _setup_session_at_step2(self, client, app):
        """
        Create an analysis session that is ready to advance to step 2
        (i.e., step 1 / PROPERTY_FACTS is complete).

        Returns the session_id.
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition
        from datetime import datetime
        import uuid

        with app.app_context():
            session_id = str(uuid.uuid4())
            session = AnalysisSession(
                session_id=session_id,
                user_id="test_user",
                current_step=WorkflowStep.PROPERTY_FACTS,
                completed_steps=["PROPERTY_FACTS"],
                step_results={"PROPERTY_FACTS": {"status": "complete"}},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(session)
            db.session.flush()

            # Add subject property so step validation passes
            subject = PropertyFacts(
                session_id=session.id,
                address="2315 W Arthington St, Chicago, IL 60612",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=3750,
                year_built=1920,
                construction_type=ConstructionType.BRICK,
                basement=False,
                parking_spaces=1,
                assessed_value=180000.0,
                annual_taxes=3600.0,
                zoning="R-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
                data_source="cook_county_assessor",
                user_modified_fields=[],
            )
            db.session.add(subject)
            db.session.commit()

        return session_id

    def test_bug2_step2_returns_202_not_200(self, app, client):
        """
        Bug condition: POST /api/analysis/{session_id}/step/2 returns HTTP 200
        (synchronous) instead of HTTP 202 (async accepted).

        _execute_comparable_search is mocked to return immediately so the test
        does not actually block, but the route still returns 200 on unfixed code
        because the synchronous path always returns 200.

        EXPECTED TO FAIL on unfixed code.
        Counterexample: response.status_code == 200, not 202.

        Validates: Requirements 1.3, 1.4
        """
        session_id = self._setup_session_at_step2(client, app)

        # Mock _execute_comparable_search to return immediately (avoids real HTTP calls
        # and the ~2-minute blocking duration).  The route still returns 200 on unfixed
        # code because the synchronous advance_to_step path always returns 200.
        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_comparable_search",
            return_value={"comparable_count": 0, "status": "complete"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/2",
                json={},
                content_type="application/json",
            )

        # EXPECTED BEHAVIOR (will FAIL on unfixed code):
        # The fixed route returns 202 immediately and enqueues a Celery task.
        # The unfixed route calls advance_to_step synchronously and returns 200.
        assert response.status_code == 202, (
            f"COUNTEREXAMPLE DOCUMENTED: POST /api/analysis/{{session_id}}/step/2 "
            f"returned HTTP {response.status_code} (expected 202). "
            f"On unfixed code the route executes synchronously and returns 200. "
            f"This confirms Bug 2: the route blocks for ~2 minutes, exceeding "
            f"the Axios 30-second timeout."
        )

    def test_bug2_step2_response_body_has_accepted_status(self, app, client):
        """
        Bug condition: POST /api/analysis/{session_id}/step/2 response body
        does not contain {'status': 'accepted'} on unfixed code.

        EXPECTED TO FAIL on unfixed code.
        Counterexample: response.json does not have status='accepted'.

        Validates: Requirements 1.3, 1.4
        """
        session_id = self._setup_session_at_step2(client, app)

        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_comparable_search",
            return_value={"comparable_count": 0, "status": "complete"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/2",
                json={},
                content_type="application/json",
            )

        data = response.get_json()

        # EXPECTED BEHAVIOR (will FAIL on unfixed code):
        # The fixed route returns {"status": "accepted", "session_id": "..."}.
        # The unfixed route returns the full synchronous step result dict.
        assert data is not None, "Response body should not be empty"
        assert data.get("status") == "accepted", (
            f"COUNTEREXAMPLE DOCUMENTED: POST /api/analysis/{{session_id}}/step/2 "
            f"returned status={data.get('status')!r} (expected 'accepted'). "
            f"Response body: {data}. "
            f"On unfixed code the route returns the full synchronous step result. "
            f"Fix: route should return {{\"status\": \"accepted\", \"session_id\": \"...\"}} "
            f"with HTTP 202."
        )

    def test_bug2_step2_response_contains_session_id(self, app, client):
        """
        The HTTP 202 response body should include ONLY the async sentinel
        shape: {"status": "accepted", "session_id": "..."}.  On unfixed code
        the response body has the full synchronous step result shape
        (current_step, previous_step, result, warnings, etc.) — not the
        202 sentinel.

        EXPECTED TO FAIL on unfixed code (response body has the synchronous
        step result shape, not the async accepted shape).

        Validates: Requirements 1.3, 1.4
        """
        session_id = self._setup_session_at_step2(client, app)

        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_comparable_search",
            return_value={"comparable_count": 0, "status": "complete"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/2",
                json={},
                content_type="application/json",
            )

        data = response.get_json()
        assert data is not None

        # On unfixed code the response body has the synchronous step result shape:
        # {"current_step": "COMPARABLE_SEARCH", "previous_step": "PROPERTY_FACTS",
        #  "result": {...}, "session_id": "...", "updated_at": "...", "warnings": []}
        # The fixed response should NOT have "current_step" or "previous_step" —
        # it should only have {"status": "accepted", "session_id": "..."}.
        assert "current_step" not in data, (
            f"COUNTEREXAMPLE DOCUMENTED: Response body contains 'current_step' key, "
            f"indicating the route returned the full synchronous step result instead of "
            f"the async 202 accepted sentinel. "
            f"Got: {data}. "
            f"Fix: route should return {{\"status\": \"accepted\", \"session_id\": \"{session_id}\"}} "
            f"with HTTP 202 — no 'current_step' or 'previous_step' keys."
        )

# ===========================================================================
# PRESERVATION PROPERTY TESTS (Task 2)
# ===========================================================================
# These tests verify that non-buggy behaviors are preserved on UNFIXED code.
# They MUST PASS on unfixed code (they test inputs where isBugCondition_Bug1
# and isBugCondition_Bug2 both return false).
#
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
# ===========================================================================

import uuid as _uuid_mod
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Preservation helpers (module-level, used by all preservation test classes)
# ---------------------------------------------------------------------------

def _pres_make_subject(lat=41.8781, lon=-87.6298, property_type=None):
    from app.models.property_facts import PropertyFacts, PropertyType
    subject = PropertyFacts()
    subject.address = "2315 W Arthington St, Chicago, IL 60612"
    subject.property_type = property_type or PropertyType.SINGLE_FAMILY
    subject.latitude = lat
    subject.longitude = lon
    return subject


def _pres_seed_session(app, target_step_value: int):
    from app import db
    from app.models.analysis_session import AnalysisSession, WorkflowStep
    from app.models.property_facts import (
        PropertyFacts, PropertyType, ConstructionType, InteriorCondition,
    )
    from app.models.comparable_sale import ComparableSale
    from app.models.ranked_comparable import RankedComparable
    from datetime import date

    session_id = str(_uuid_mod.uuid4())
    # For step 1, current_step IS step 1 (no prior step)
    current_step = WorkflowStep(max(1, target_step_value - 1))
    completed = [WorkflowStep(sv).name for sv in range(1, target_step_value)]

    session = AnalysisSession(
        session_id=session_id,
        user_id="test_user",
        current_step=current_step,
        completed_steps=completed,
        step_results={s: {"status": "complete"} for s in completed},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(session)
    db.session.flush()

    subject = PropertyFacts(
        session_id=session.id,
        address="2315 W Arthington St, Chicago, IL 60612",
        property_type=PropertyType.SINGLE_FAMILY,
        units=1,
        bedrooms=3,
        bathrooms=1.5,
        square_footage=1400,
        lot_size=3750,
        year_built=1920,
        construction_type=ConstructionType.BRICK,
        basement=False,
        parking_spaces=1,
        assessed_value=180000.0,
        annual_taxes=3600.0,
        zoning="R-3",
        interior_condition=InteriorCondition.AVERAGE,
        latitude=41.8781,
        longitude=-87.6298,
        data_source="cook_county_assessor",
        user_modified_fields=[],
    )
    db.session.add(subject)
    db.session.flush()

    if target_step_value >= 4:
        comp = ComparableSale(
            session_id=session.id,
            address="100 Test St, Chicago, IL 60612",
            sale_date=date(2023, 6, 1),
            sale_price=300000.0,
            property_type=PropertyType.SINGLE_FAMILY,
            units=1,
            bedrooms=3,
            bathrooms=1.5,
            square_footage=1400,
            lot_size=3750,
            year_built=1920,
            construction_type=ConstructionType.BRICK,
            interior_condition=InteriorCondition.AVERAGE,
            distance_miles=0.25,
            latitude=41.879,
            longitude=-87.630,
        )
        db.session.add(comp)
        db.session.flush()

        if target_step_value >= 5:
            ranked = RankedComparable(
                session_id=session.id,
                comparable_id=comp.id,
                total_score=0.85,
                rank=1,
                recency_score=0.9,
                proximity_score=0.95,
                units_score=1.0,
                beds_baths_score=1.0,
                sqft_score=0.8,
                construction_score=0.9,
                interior_score=0.7,
            )
            db.session.add(ranked)

    db.session.commit()
    return session_id, session.id


# ---------------------------------------------------------------------------
# Property 1: Arm's-Length Filter Preservation
# ---------------------------------------------------------------------------

class TestArmsLengthFilterPreservation:
    """
    Preservation property: fetch_comparables returns ONLY records where all
    three arm's-length flags are false, regardless of max_age_months (when
    the cutoff predates the dataset).

    Observation on UNFIXED code:
      _fetch_sales_for_pins applies server-side SoQL filters:
        AND is_multisale=false
        AND sale_filter_less_than_10k=false
        AND sale_filter_deed_type=false
      The mock simulates this by filtering records before returning them.
      Only records with all three flags false pass through.

    Validates: Requirements 3.1
    """

    # Hypothesis strategy: generate a list of sale records with random flag combos
    _sale_record_strategy = st.fixed_dictionaries({
        "is_multisale": st.booleans(),
        "sale_filter_less_than_10k": st.booleans(),
        "sale_filter_deed_type": st.booleans(),
        # sale_date between 2022-01-01 and 2024-12-31 (non-buggy range)
        "sale_date": st.dates(
            min_value=datetime(2022, 1, 1).date(),
            max_value=datetime(2024, 12, 31).date(),
        ).map(lambda d: d.strftime("%Y-%m-%dT00:00:00.000")),
        "sale_price": st.integers(min_value=50_000, max_value=1_000_000),
        "pin": st.text(
            alphabet="0123456789",
            min_size=14,
            max_size=14,
        ),
    })

    def _make_socrata_mock_with_records(self, records, max_age_months):
        """
        Return a fake _socrata_get that:
          - Returns bbox rows for all PINs in records
          - Returns only arm's-length-passing records from the sales dataset
            (simulating the server-side SoQL filter)
          - Returns improvement chars for all PINs
        """
        cutoff = datetime.now() - timedelta(days=max_age_months * 30)

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                # Return bbox rows for all unique PINs
                seen = set()
                rows = []
                for rec in records:
                    pin = rec["pin"]
                    if pin not in seen:
                        seen.add(pin)
                        rows.append({
                            "pin": pin,
                            "lat": "41.8781",
                            "lon": "-87.6298",
                        })
                return rows

            if "wvhk-k5uv" in url:
                # Simulate server-side arm's-length + date filter
                rows = []
                for rec in records:
                    sale_dt = datetime.fromisoformat(
                        rec["sale_date"].replace("T00:00:00.000", "")
                    )
                    if sale_dt < cutoff:
                        continue
                    # Server-side arm's-length filter
                    if rec["is_multisale"]:
                        continue
                    if rec["sale_filter_less_than_10k"]:
                        continue
                    if rec["sale_filter_deed_type"]:
                        continue
                    rows.append({
                        "pin": rec["pin"],
                        "sale_date": rec["sale_date"],
                        "sale_price": str(rec["sale_price"]),
                        "class": "202",
                    })
                return rows

            if "bcnq-qi2z" in url:
                seen = set()
                rows = []
                for rec in records:
                    pin = rec["pin"]
                    if pin not in seen:
                        seen.add(pin)
                        rows.append({
                            "pin": pin,
                            "bldg_sf": "1400",
                            "beds": "3",
                            "fbath": "1",
                            "hbath": "1",
                            "age": "40",
                            "ext_wall": "3",
                            "apts": "1",
                        })
                return rows

            return []

        return fake_socrata_get

    @given(
        records=st.lists(_sale_record_strategy, min_size=1, max_size=20),
        max_age_months=st.integers(min_value=36, max_value=60),
    )
    @settings(max_examples=50, deadline=None)
    def test_arms_length_filter_preserved_for_non_buggy_inputs(
        self, records, max_age_months
    ):
        """
        Property: For any set of sale records and any max_age_months >= 36
        (non-buggy: cutoff predates the dataset), fetch_comparables returns
        ONLY records where all three arm's-length flags are false.

        This is a preservation property: the arm's-length filtering behavior
        must be unchanged by the Bug 1 fix.

        Validates: Requirements 3.1
        """
        # isBugCondition_Bug1 is false when max_age_months >= 36 (cutoff ~2022+)
        # which is well before the dataset's last record (~2024-12-31)
        assume(max_age_months >= 36)

        subject = _pres_make_subject()
        finder = ComparableSalesFinder()

        with patch.object(
            CookCountySalesDataSource,
            "_socrata_get",
            side_effect=self._make_socrata_mock_with_records(records, max_age_months),
        ):
            result = finder.find_comparables(
                subject=subject,
                min_count=1,
                max_age_months=max_age_months,
            )

        # All returned records must have passed the arm's-length filter.
        # Since the mock simulates the server-side filter, any record that
        # was returned must have had all three flags false.
        #
        # A PIN may appear in both a clean record AND a flagged record (duplicate
        # PINs with different flag combinations). In that case the clean record
        # legitimately passes the filter. We only flag PINs where EVERY record
        # with that PIN is flagged — meaning there is no clean record that could
        # have produced the result.
        returned_pins = {r.get("pin") for r in result if r.get("pin")}

        # PINs that have at least one clean (non-flagged) record
        clean_pins = {
            rec["pin"]
            for rec in records
            if not rec["is_multisale"]
            and not rec["sale_filter_less_than_10k"]
            and not rec["sale_filter_deed_type"]
        }

        # PINs that are ONLY in flagged records (no clean record exists for them)
        exclusively_flagged_pins = {
            rec["pin"]
            for rec in records
            if rec["is_multisale"]
            or rec["sale_filter_less_than_10k"]
            or rec["sale_filter_deed_type"]
        } - clean_pins

        # No returned PIN should come exclusively from flagged records
        overlap = returned_pins & exclusively_flagged_pins
        assert not overlap, (
            f"Arm's-length filter violated: returned PINs {overlap} "
            f"have no clean (non-flagged) source record — they should have been "
            f"excluded by the is_multisale, sale_filter_less_than_10k, and "
            f"sale_filter_deed_type filters."
        )


# ---------------------------------------------------------------------------
# Property 2: Radius Expansion Preservation
# ---------------------------------------------------------------------------

class TestRadiusExpansionPreservation:
    """
    Preservation property: find_comparables stops at the FIRST radius in
    [0.25, 0.5, 0.75, 1.0] that yields >= min_count results, and never
    skips or reorders the sequence.

    Observation on UNFIXED code:
      ComparableSalesFinder.RADIUS_SEQUENCE = [0.25, 0.5, 0.75, 1.0]
      find_comparables iterates in order and returns as soon as
      len(comparables) >= min_count.

    Validates: Requirements 3.2
    """

    def _make_radius_mock(self, results_at_radius: dict):
        """
        Return a fake _socrata_get that returns different numbers of results
        depending on the radius encoded in the bounding-box WHERE clause.

        results_at_radius: {0.25: N, 0.5: M, ...} — number of results at each radius.
        The mock infers the radius from the lat/lon delta in the WHERE clause.
        """
        # Precompute lat deltas for each radius
        from app.services.comparable_sales_finder import (
            _MILES_PER_DEGREE_LAT,
            _MILES_PER_DEGREE_LON_AT_CHICAGO,
        )

        def _lat_delta(r):
            return r / _MILES_PER_DEGREE_LAT

        def fake_socrata_get(url):
            if "pabr-t5kh" in url:
                # Infer radius from the lat delta in the WHERE clause
                import urllib.parse
                # Parse the where clause to find the lat range
                decoded = urllib.parse.unquote(url)
                # Find the radius by matching lat delta
                matched_radius = None
                for r in [0.25, 0.5, 0.75, 1.0]:
                    delta = _lat_delta(r)
                    # Check if this delta appears in the URL (within tolerance)
                    if f"{41.8781 - delta:.4f}" in decoded or f"{41.8781 + delta:.4f}" in decoded:
                        matched_radius = r
                        break

                if matched_radius is None:
                    return []

                n = results_at_radius.get(matched_radius, 0)
                rows = []
                for i in range(n):
                    rows.append({
                        "pin": f"1623309{i:07d}",
                        "lat": "41.8781",
                        "lon": "-87.6298",
                    })
                return rows

            if "wvhk-k5uv" in url:
                # Return a sale for each PIN in the batch
                import urllib.parse
                decoded = urllib.parse.unquote(url)
                # Extract PINs from the IN clause
                import re
                pins = re.findall(r"'(\d{14})'", decoded)
                rows = []
                for pin in pins:
                    rows.append({
                        "pin": pin,
                        "sale_date": "2023-06-01T00:00:00.000",
                        "sale_price": "300000",
                        "class": "202",
                    })
                return rows

            if "bcnq-qi2z" in url:
                import urllib.parse
                import re
                decoded = urllib.parse.unquote(url)
                pins = re.findall(r"'(\d{14})'", decoded)
                rows = []
                for pin in pins:
                    rows.append({
                        "pin": pin,
                        "bldg_sf": "1400",
                        "beds": "3",
                        "fbath": "1",
                        "hbath": "1",
                        "age": "40",
                        "ext_wall": "3",
                        "apts": "1",
                    })
                return rows

            return []

        return fake_socrata_get

    @given(
        min_count=st.integers(min_value=1, max_value=10),
        # Which radius index (0-3) first satisfies min_count
        first_satisfying_idx=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=40, deadline=None)
    def test_radius_expansion_stops_at_first_satisfying_radius(
        self, min_count, first_satisfying_idx
    ):
        """
        Property: find_comparables stops at the first radius in
        [0.25, 0.5, 0.75, 1.0] that yields >= min_count results.

        We set up the mock so that:
          - Radii before first_satisfying_idx yield 0 results
          - The radius at first_satisfying_idx yields exactly min_count results
          - Radii after first_satisfying_idx yield min_count * 2 results

        The result must contain exactly min_count records (from the first
        satisfying radius), not more (which would indicate the search
        continued past the first satisfying radius).

        Validates: Requirements 3.2
        """
        radii = ComparableSalesFinder.RADIUS_SEQUENCE  # [0.25, 0.5, 0.75, 1.0]
        results_at_radius = {}
        for i, r in enumerate(radii):
            if i < first_satisfying_idx:
                results_at_radius[r] = 0
            elif i == first_satisfying_idx:
                results_at_radius[r] = min_count
            else:
                results_at_radius[r] = min_count * 2

        subject = _pres_make_subject()
        finder = ComparableSalesFinder()

        with patch.object(
            CookCountySalesDataSource,
            "_socrata_get",
            side_effect=self._make_radius_mock(results_at_radius),
        ):
            result = finder.find_comparables(
                subject=subject,
                min_count=min_count,
                max_age_months=36,  # non-buggy: cutoff ~2022
            )

        # The result should have exactly min_count records (stopped at first
        # satisfying radius, not continued to larger radii)
        assert len(result) == min_count, (
            f"Radius expansion stopped at wrong point: expected {min_count} results "
            f"(from radius {radii[first_satisfying_idx]} mi), got {len(result)}. "
            f"The search should stop at the first radius that satisfies min_count."
        )

    def test_radius_sequence_is_always_0_25_0_5_0_75_1_0(self):
        """
        Preservation: RADIUS_SEQUENCE is always [0.25, 0.5, 0.75, 1.0].
        This sequence must not be reordered or modified by the fix.

        Validates: Requirements 3.2
        """
        assert ComparableSalesFinder.RADIUS_SEQUENCE == [0.25, 0.5, 0.75, 1.0], (
            f"RADIUS_SEQUENCE changed: {ComparableSalesFinder.RADIUS_SEQUENCE}. "
            f"The radius expansion sequence must remain [0.25, 0.5, 0.75, 1.0]."
        )


# ---------------------------------------------------------------------------
# Property 3: Steps 3-6 Synchronous Preservation
# ---------------------------------------------------------------------------

class TestSteps3To6SynchronousPreservation:
    """
    Preservation property: POST /api/analysis/{session_id}/step/{n} for
    n in {3, 4, 5, 6} always returns HTTP 200 synchronously and never
    returns 202.

    Observation on UNFIXED code:
      advance_to_step route returns 200 for ALL steps (no async branching).
      After the Bug 2 fix, step 2 will return 202, but steps 3-6 must
      continue to return 200.

    isBugCondition_Bug2 is false for steps 3-6 (only step 2 triggers it).

    Validates: Requirements 3.3
    """

    @pytest.mark.parametrize("step_number", [3, 4, 5, 6])
    def test_steps_3_to_6_return_200_not_202(self, app, client, step_number):
        """
        Property: POST /api/analysis/{session_id}/step/{n} for n in {3,4,5,6}
        always returns HTTP 200 and never returns 202.

        isBugCondition_Bug2(X) is false for step_number != 2, so these steps
        must remain synchronous and return 200 on both unfixed and fixed code.

        Validates: Requirements 3.3
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, step_number)

        # Mock the step execution to avoid real computation
        step_execute_map = {
            3: "app.controllers.workflow_controller.WorkflowController._execute_step",
        }

        # Mock all step executions to return immediately
        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_step",
            return_value={"status": "complete"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/{step_number}",
                json={},
                content_type="application/json",
            )

        assert response.status_code == 200, (
            f"Step {step_number} returned HTTP {response.status_code} "
            f"(expected 200). Steps 3-6 must remain synchronous and return 200. "
            f"Only step 2 should return 202 after the Bug 2 fix."
        )
        assert response.status_code != 202, (
            f"Step {step_number} returned HTTP 202 — this step must remain "
            f"synchronous. Only step 2 should be async."
        )

    def test_step_3_returns_200_concrete(self, app, client):
        """
        Concrete example: POST /api/analysis/{session_id}/step/3 returns 200.

        Validates: Requirements 3.3
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, 3)

        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_step",
            return_value={"status": "ready_for_review"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/3",
                json={},
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "current_step" in data, (
            f"Step 3 response missing 'current_step'. Got: {data}"
        )


# ---------------------------------------------------------------------------
# Property 4: Session State Fields Preservation
# ---------------------------------------------------------------------------

class TestSessionStatePreservation:
    """
    Preservation property: GET /api/analysis/{session_id} always includes
    the required fields in its response body.

    Observation on UNFIXED code:
      get_session_state returns a dict with at minimum:
        session_id, user_id, current_step, created_at, updated_at,
        completed_steps, step_results
      And optionally (when data exists):
        subject_property, comparables, comparable_count,
        ranked_comparables, valuation_result, scenarios

    Validates: Requirements 3.4
    """

    # Required fields that must ALWAYS be present in the GET response
    REQUIRED_FIELDS = [
        "session_id",
        "user_id",
        "current_step",
        "created_at",
        "updated_at",
        "completed_steps",
        "step_results",
    ]

    # Fields that must be present when the corresponding data exists
    CONDITIONAL_FIELDS = [
        "subject_property",
        "comparables",
        "ranked_comparables",
        "valuation_result",
        "scenarios",
    ]

    def test_get_session_always_includes_required_fields(self, app, client):
        """
        Concrete example: GET /api/analysis/{session_id} includes all
        required fields for a freshly created session.

        Validates: Requirements 3.4
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, 1)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        for field in self.REQUIRED_FIELDS:
            assert field in data, (
                f"GET /api/analysis/{{session_id}} missing required field '{field}'. "
                f"Got fields: {list(data.keys())}"
            )

    def test_get_session_includes_subject_property_when_present(self, app, client):
        """
        When a session has a subject property, GET response includes
        'subject_property' field.

        Validates: Requirements 3.4
        """
        with app.app_context():
            # Seed at step 2 (has subject property)
            session_id, _ = _pres_seed_session(app, 2)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "subject_property" in data, (
            f"GET response missing 'subject_property' even though session has one. "
            f"Got fields: {list(data.keys())}"
        )

    def test_get_session_includes_comparables_when_present(self, app, client):
        """
        When a session has comparables, GET response includes 'comparables' field.

        Validates: Requirements 3.4
        """
        with app.app_context():
            # Seed at step 4 (has comparables)
            session_id, _ = _pres_seed_session(app, 4)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "comparables" in data, (
            f"GET response missing 'comparables' even though session has them. "
            f"Got fields: {list(data.keys())}"
        )

    @pytest.mark.parametrize("step_value", [1, 2, 3, 4])
    def test_get_session_required_fields_present_at_any_step(
        self, app, client, step_value
    ):
        """
        Property: GET /api/analysis/{session_id} always includes all required
        fields regardless of which step the session is at.

        Validates: Requirements 3.4
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, step_value)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

        for field in self.REQUIRED_FIELDS:
            assert field in data, (
                f"GET /api/analysis/{{session_id}} missing required field '{field}' "
                f"at step {step_value}. Got fields: {list(data.keys())}"
            )


# ---------------------------------------------------------------------------
# Property 5: App Token Header Preservation
# ---------------------------------------------------------------------------

class TestAppTokenPreservation:
    """
    Preservation property: _socrata_get sends the X-App-Token header whenever
    COOK_COUNTY_APP_TOKEN env var is set, regardless of the query parameters.

    Observation on UNFIXED code:
      CookCountySalesDataSource.__init__ reads COOK_COUNTY_APP_TOKEN from env.
      _socrata_get sets headers['X-App-Token'] = self._app_token when set.
      urllib.request.Request is called with those headers.

    Validates: Requirements 3.5
    """

    @given(
        app_token=st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="-_",
            ),
            min_size=8,
            max_size=40,
        ),
        query_suffix=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=0,
            max_size=20,
        ),
    )
    @settings(max_examples=30, deadline=None)
    def test_app_token_header_sent_when_env_var_set(self, app_token, query_suffix):
        """
        Property: _socrata_get includes X-App-Token header whenever
        COOK_COUNTY_APP_TOKEN is set, regardless of the URL/query parameters.

        Validates: Requirements 3.5
        """
        assume(len(app_token) >= 8)

        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(req.headers)
            # Return a mock response
            import io
            import json
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps([]).encode("utf-8")
            return mock_resp

        test_url = f"https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json?test={query_suffix}"

        with patch.dict(os.environ, {"COOK_COUNTY_APP_TOKEN": app_token}):
            source = CookCountySalesDataSource()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                source._socrata_get(test_url)

        # X-App-Token header must be present
        # urllib.request.Request capitalizes header names: 'X-app-token'
        header_keys_lower = {k.lower() for k in captured_headers.keys()}
        assert "x-app-token" in header_keys_lower, (
            f"X-App-Token header not sent when COOK_COUNTY_APP_TOKEN='{app_token}' is set. "
            f"Headers sent: {captured_headers}. "
            f"The _socrata_get method must always include X-App-Token when the env var is set."
        )

        # The header value must match the token
        token_value = None
        for k, v in captured_headers.items():
            if k.lower() == "x-app-token":
                token_value = v
                break
        assert token_value == app_token, (
            f"X-App-Token header value '{token_value}' does not match "
            f"COOK_COUNTY_APP_TOKEN='{app_token}'."
        )

    def test_app_token_not_sent_when_env_var_not_set(self):
        """
        Preservation: When COOK_COUNTY_APP_TOKEN is not set, no X-App-Token
        header is sent (no spurious header injection).

        Validates: Requirements 3.5
        """
        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(req.headers)
            import io
            import json
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps([]).encode("utf-8")
            return mock_resp

        test_url = "https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json?test=1"

        # Ensure the env var is not set
        env_without_token = {
            k: v for k, v in os.environ.items()
            if k != "COOK_COUNTY_APP_TOKEN"
        }
        with patch.dict(os.environ, env_without_token, clear=True):
            source = CookCountySalesDataSource()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                source._socrata_get(test_url)

        header_keys_lower = {k.lower() for k in captured_headers.keys()}
        assert "x-app-token" not in header_keys_lower, (
            f"X-App-Token header was sent even though COOK_COUNTY_APP_TOKEN is not set. "
            f"Headers sent: {captured_headers}."
        )

    def test_app_token_sent_for_all_three_socrata_endpoints(self):
        """
        Preservation: X-App-Token is sent for all three Socrata endpoints
        (Parcel Universe, Parcel Sales, Improvement Characteristics).

        Validates: Requirements 3.5
        """
        app_token = "test-token-12345678"
        calls_with_token = []

        def fake_urlopen(req, timeout=None):
            if req.headers.get("X-app-token") == app_token:
                calls_with_token.append(req.full_url)
            import json
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps([]).encode("utf-8")
            return mock_resp

        with patch.dict(os.environ, {"COOK_COUNTY_APP_TOKEN": app_token}):
            source = CookCountySalesDataSource()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                # Call each endpoint type
                source._socrata_get(
                    "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json?test=1"
                )
                source._socrata_get(
                    "https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json?test=1"
                )
                source._socrata_get(
                    "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json?test=1"
                )

        assert len(calls_with_token) == 3, (
            f"Expected X-App-Token on all 3 Socrata endpoint calls, "
            f"but only got it on {len(calls_with_token)}: {calls_with_token}"
        )


# ===========================================================================
# UNIT TESTS — Bug 1 Fix (Task 5.1)
# ===========================================================================
# These unit tests verify the specific mechanics of the Bug 1 fix:
#   1. fetch_comparables with max_age_months=36 returns non-empty results
#   2. _fetch_sales_for_pins generates the correct SoQL date filter
#   3. _execute_comparable_search forwards MAX_AGE_MONTHS (not literal 12)
#
# Validates: Requirements 2.1, 2.2
# ===========================================================================


class TestBug1UnitTests:
    """
    Unit tests for the Bug 1 (stale date cutoff) fix.

    Validates: Requirements 2.1, 2.2
    """

    # A known Cook County PIN near the test subject address
    _PIN = "16233090190000"

    # Realistic sales within the 36-month window (2022–2024)
    _SALES_IN_WINDOW = [
        ("2024-11-01T00:00:00.000", 310_000),
        ("2024-06-15T00:00:00.000", 295_000),
        ("2023-09-20T00:00:00.000", 280_000),
        ("2022-06-10T00:00:00.000", 260_000),
    ]

    def _make_socrata_mock(self):
        """
        Return a fake _socrata_get that always returns the sales in
        _SALES_IN_WINDOW regardless of the date filter in the URL.

        This simulates a Socrata response for a 36-month window where
        all four sales fall within the cutoff (~May 2022 or earlier).
        """
        pin = self._PIN

        def fake_socrata_get(url: str):
            if "pabr-t5kh" in url:
                return [{"pin": pin, "lat": "41.8781", "lon": "-87.6298"}]
            if "wvhk-k5uv" in url:
                return [
                    {
                        "pin": pin,
                        "sale_date": sale_date,
                        "sale_price": str(price),
                        "class": "202",
                    }
                    for sale_date, price in self._SALES_IN_WINDOW
                ]
            if "bcnq-qi2z" in url:
                return [
                    {
                        "pin": pin,
                        "bldg_sf": "1400",
                        "beds": "3",
                        "fbath": "1",
                        "hbath": "1",
                        "age": "40",
                        "ext_wall": "3",
                        "apts": "1",
                    }
                ]
            return []

        return fake_socrata_get

    # ------------------------------------------------------------------
    # Test 1: fetch_comparables with max_age_months=36 returns non-empty
    # ------------------------------------------------------------------

    def test_fetch_comparables_36_months_returns_non_empty(self):
        """
        Unit test: CookCountySalesDataSource.fetch_comparables called with
        max_age_months=36 against a mocked Socrata response returns a
        non-empty list of comparables.

        This directly validates the Bug 1 fix: with MAX_AGE_MONTHS=36 the
        SoQL cutoff is ~May 2022, which is well before the dataset's last
        record (~late 2024), so results are returned.

        Validates: Requirements 2.1, 2.2
        """
        subject = _make_chicago_subject()
        source = CookCountySalesDataSource()

        with patch.object(
            CookCountySalesDataSource,
            "_socrata_get",
            side_effect=self._make_socrata_mock(),
        ):
            result = source.fetch_comparables(
                subject_facts=subject,
                max_age_months=36,
                max_distance_miles=0.5,
                max_count=10,
            )

        assert len(result) > 0, (
            "fetch_comparables(max_age_months=36) returned an empty list. "
            "With a 36-month window the SoQL cutoff is ~May 2022, which is "
            "well before the dataset's last record (~late 2024). "
            "Expected at least one comparable to be returned."
        )

    # ------------------------------------------------------------------
    # Test 2: _fetch_sales_for_pins generates correct SoQL date filter
    # ------------------------------------------------------------------

    def test_fetch_sales_for_pins_soql_date_filter(self):
        """
        Unit test: CookCountySalesDataSource._fetch_sales_for_pins with a
        cutoff date of 2022-01-01 generates a SoQL WHERE clause that contains
        ``sale_date >= '2022-01-01T00:00:00.000'``.

        This verifies that the date filter is constructed correctly and that
        the ISO-8601 timestamp format matches what the Socrata API expects.

        Validates: Requirements 2.1, 2.2
        """
        source = CookCountySalesDataSource()
        cutoff = datetime(2022, 1, 1)
        pins = [self._PIN]
        target_classes = ["202"]  # single-family

        captured_urls = []

        def capturing_socrata_get(url: str):
            captured_urls.append(url)
            return []

        with patch.object(
            CookCountySalesDataSource,
            "_socrata_get",
            side_effect=capturing_socrata_get,
        ):
            source._fetch_sales_for_pins(pins, cutoff, target_classes)

        assert len(captured_urls) == 1, (
            f"Expected exactly 1 Socrata call for 1 PIN batch, got {len(captured_urls)}"
        )

        import urllib.parse
        decoded_url = urllib.parse.unquote(captured_urls[0])

        expected_fragment = "sale_date >= '2022-01-01T00:00:00.000'"
        assert expected_fragment in decoded_url, (
            f"SoQL WHERE clause does not contain the expected date filter. "
            f"Expected to find: {expected_fragment!r}\n"
            f"Decoded URL: {decoded_url}"
        )

    # ------------------------------------------------------------------
    # Test 3: _execute_comparable_search forwards MAX_AGE_MONTHS constant
    # ------------------------------------------------------------------

    def test_execute_comparable_search_uses_max_age_months_constant(self, app, client):
        """
        Unit test: WorkflowController no longer has a comparable_finder attribute
        and _execute_comparable_search raises NotImplementedError.

        The comparable search is now performed by run_comparable_search_task via
        GeminiComparableSearchService — not by WorkflowController directly.

        Validates: Requirements 2.1, 2.2 (via the new Gemini-based architecture)
        """
        from app.controllers.workflow_controller import WorkflowController

        with app.app_context():
            controller = WorkflowController()

            # WorkflowController should no longer have a comparable_finder attribute
            assert not hasattr(controller, 'comparable_finder'), (
                "WorkflowController still has 'comparable_finder' attribute. "
                "Task 6 requires removing ComparableSalesFinder from WorkflowController."
            )

            # _execute_comparable_search should raise NotImplementedError
            with pytest.raises(NotImplementedError):
                controller._execute_comparable_search(None)


# ===========================================================================
# UNIT TESTS — Bug 2 Fix (Task 5.2)
# ===========================================================================
# These tests verify the concrete behavior of the Bug 2 fix:
#   - POST /api/analysis/{session_id}/step/2 returns 202 and sets loading=True
#   - POST /api/analysis/{session_id}/step/3 still returns 200 (sync path)
#   - run_comparable_search_task sets loading=False and advances current_step
#     to COMPARABLE_SEARCH on success
#   - run_comparable_search_task sets loading=False and records
#     COMPARABLE_SEARCH_ERROR in step_results on failure
#   - GET /api/analysis/{session_id} includes 'loading' in the response body
#
# Validates: Requirements 2.3, 2.4, 2.5, 3.3, 3.4
# ===========================================================================


class TestBug2UnitTests:
    """
    Unit tests for the Bug 2 fix (async step-2 route + Celery task).

    Validates: Requirements 2.3, 2.4, 2.5, 3.3, 3.4
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seed_session_at_step1(self, app):
        """
        Create an AnalysisSession at PROPERTY_FACTS (step 1) with a confirmed
        subject property so the step-2 route can validate step 1 is complete.

        Returns the session_id string.
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.models.property_facts import (
            PropertyFacts, PropertyType, ConstructionType, InteriorCondition,
        )
        import uuid

        with app.app_context():
            session_id = str(uuid.uuid4())
            session = AnalysisSession(
                session_id=session_id,
                user_id="test_user",
                current_step=WorkflowStep.PROPERTY_FACTS,
                completed_steps=["PROPERTY_FACTS"],
                step_results={"PROPERTY_FACTS": {"status": "complete"}},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(session)
            db.session.flush()

            subject = PropertyFacts(
                session_id=session.id,
                address="2315 W Arthington St, Chicago, IL 60612",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=3750,
                year_built=1920,
                construction_type=ConstructionType.BRICK,
                basement=False,
                parking_spaces=1,
                assessed_value=180000.0,
                annual_taxes=3600.0,
                zoning="R-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
                data_source="cook_county_assessor",
                user_modified_fields=[],
            )
            db.session.add(subject)
            db.session.commit()

        return session_id

    def _seed_session_at_step2(self, app):
        """
        Create an AnalysisSession at COMPARABLE_SEARCH (step 2) — i.e. step 1
        is complete and the session is ready to advance to step 3.

        Returns (session_id, db_session_id).
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.models.property_facts import (
            PropertyFacts, PropertyType, ConstructionType, InteriorCondition,
        )
        import uuid

        with app.app_context():
            session_id = str(uuid.uuid4())
            session = AnalysisSession(
                session_id=session_id,
                user_id="test_user",
                current_step=WorkflowStep.COMPARABLE_SEARCH,
                completed_steps=["PROPERTY_FACTS"],
                step_results={"PROPERTY_FACTS": {"status": "complete"}},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(session)
            db.session.flush()

            subject = PropertyFacts(
                session_id=session.id,
                address="2315 W Arthington St, Chicago, IL 60612",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=3750,
                year_built=1920,
                construction_type=ConstructionType.BRICK,
                basement=False,
                parking_spaces=1,
                assessed_value=180000.0,
                annual_taxes=3600.0,
                zoning="R-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
                data_source="cook_county_assessor",
                user_modified_fields=[],
            )
            db.session.add(subject)
            db.session.commit()
            db_id = session.id

        return session_id, db_id

    # ------------------------------------------------------------------
    # Test 1: POST /step/2 returns 202 and sets session.loading = True
    # ------------------------------------------------------------------

    def test_step2_returns_202_and_sets_loading_true(self, app, client):
        """
        POST /api/analysis/{session_id}/step/2 must return HTTP 202 with
        {"status": "accepted", "session_id": "..."} and set session.loading=True
        in the database before returning.

        The app fixture already patches run_comparable_search_task.delay to a
        no-op MagicMock, so no Redis connection is attempted.

        Validates: Requirements 2.3, 2.4
        """
        session_id = self._seed_session_at_step1(app)

        response = client.post(
            f"/api/analysis/{session_id}/step/2",
            json={},
            content_type="application/json",
        )

        # --- HTTP response assertions ---
        assert response.status_code == 202, (
            f"Expected HTTP 202, got {response.status_code}. "
            f"Response body: {response.get_json()}"
        )
        data = response.get_json()
        assert data is not None
        assert data.get("status") == "accepted", (
            f"Expected status='accepted', got {data.get('status')!r}. Full body: {data}"
        )
        assert data.get("session_id") == session_id, (
            f"Expected session_id={session_id!r} in response, got {data.get('session_id')!r}"
        )

        # --- Database state assertions ---
        from app.models.analysis_session import AnalysisSession
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session is not None
            assert session.loading is True, (
                f"Expected session.loading=True after POST /step/2, got {session.loading!r}. "
                f"The route must set loading=True before enqueuing the Celery task."
            )

    # ------------------------------------------------------------------
    # Test 2: POST /step/3 still returns 200 (synchronous path unchanged)
    # ------------------------------------------------------------------

    def test_step3_returns_200_synchronous_path_unchanged(self, app, client):
        """
        POST /api/analysis/{session_id}/step/3 must still return HTTP 200
        with the full synchronous step result (not 202).

        isBugCondition_Bug2 is false for step 3, so the synchronous path
        must be completely unaffected by the Bug 2 fix.

        Validates: Requirements 3.3
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, 3)

        # Mock _execute_step to avoid real computation (step 3 = COMPARABLE_REVIEW)
        with patch(
            "app.controllers.workflow_controller.WorkflowController._execute_step",
            return_value={"status": "ready_for_review"},
        ):
            response = client.post(
                f"/api/analysis/{session_id}/step/3",
                json={},
                content_type="application/json",
            )

        assert response.status_code == 200, (
            f"Expected HTTP 200 for step 3, got {response.status_code}. "
            f"Steps 3-6 must remain synchronous and return 200. "
            f"Response body: {response.get_json()}"
        )
        assert response.status_code != 202, (
            "Step 3 must NOT return 202 — only step 2 is async."
        )

        data = response.get_json()
        assert data is not None
        # Synchronous response includes current_step and previous_step
        assert "current_step" in data, (
            f"Synchronous step-3 response missing 'current_step'. Got: {data}"
        )
        assert "session_id" in data, (
            f"Synchronous step-3 response missing 'session_id'. Got: {data}"
        )

    # ------------------------------------------------------------------
    # Test 3: run_comparable_search_task success path
    # ------------------------------------------------------------------

    def test_run_comparable_search_task_success_sets_loading_false_and_advances_step(
        self, app
    ):
        """
        run_comparable_search_task (called directly, not via .delay) must:
          - Call GeminiComparableSearchService.search
          - Set session.loading = False
          - Advance session.current_step to COMPARABLE_SEARCH
          - Record the result in session.step_results[COMPARABLE_SEARCH]

        The task calls create_app() internally to build its own app context.
        We patch create_app to return the test app so the task operates on
        the same in-memory SQLite database that the test seeded.

        Validates: Requirements 2.4, 2.5
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from celery_worker import run_comparable_search_task
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService

        session_id = self._seed_session_at_step1(app)

        # Set loading=True to simulate the state after the route enqueued the task
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.loading = True
            db.session.commit()

        mock_gemini_result = {
            "comparables": [],
            "narrative": "Test narrative from Gemini.",
        }

        # Patch create_app so the task's internal app context uses the same in-memory SQLite DB.
        # Patch GeminiComparableSearchService.search to return a well-formed result.
        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 return_value=mock_gemini_result,
             ):
            result = run_comparable_search_task(session_id)

        # Verify return value
        assert isinstance(result, dict), (
            f"Task returned unexpected type: {type(result)!r}"
        )
        assert "error" not in result, (
            f"Task returned an error on the happy path: {result!r}"
        )

        # Verify database state
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session is not None

            assert session.loading is False, (
                f"Expected session.loading=False after task success, got {session.loading!r}. "
                f"The task must set loading=False on completion."
            )
            assert session.current_step == WorkflowStep.COMPARABLE_SEARCH, (
                f"Expected current_step=COMPARABLE_SEARCH after task success, "
                f"got {session.current_step!r}. "
                f"The task must advance current_step to COMPARABLE_SEARCH."
            )
            step_results = dict(session.step_results or {})
            assert WorkflowStep.COMPARABLE_SEARCH.name in step_results, (
                f"Expected COMPARABLE_SEARCH key in step_results, "
                f"got keys: {list(step_results.keys())}"
            )

    # ------------------------------------------------------------------
    # Test 4: run_comparable_search_task failure path
    # ------------------------------------------------------------------

    def test_run_comparable_search_task_failure_sets_loading_false_and_records_error(
        self, app
    ):
        """
        When GeminiComparableSearchService.search raises an exception,
        run_comparable_search_task must:
          - Set session.loading = False
          - Record the error string in session.step_results['COMPARABLE_SEARCH_ERROR']
          - NOT raise (returns {'error': ...} dict instead)

        The task calls create_app() internally; we patch it to return the test
        app so the task operates on the same in-memory SQLite database.

        Validates: Requirements 2.4, 2.5
        """
        from app import db
        from app.models.analysis_session import AnalysisSession
        from celery_worker import run_comparable_search_task
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService

        session_id = self._seed_session_at_step1(app)

        # Set loading=True to simulate the state after the route enqueued the task
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.loading = True
            db.session.commit()

        error_message = "Gemini API unavailable: connection timeout"

        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 side_effect=RuntimeError(error_message),
             ):
            result = run_comparable_search_task(session_id)

        # Task must return an error dict, not raise
        assert isinstance(result, dict), (
            f"Task should return a dict on failure, got {type(result)!r}"
        )
        assert "error" in result, (
            f"Task failure result missing 'error' key. Got: {result!r}"
        )

        # Verify database state
        with app.app_context():
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session is not None

            assert session.loading is False, (
                f"Expected session.loading=False after task failure, got {session.loading!r}. "
                f"The task must set loading=False even when search raises."
            )

            step_results = dict(session.step_results or {})
            assert "COMPARABLE_SEARCH_ERROR" in step_results, (
                f"Expected 'COMPARABLE_SEARCH_ERROR' key in step_results after failure, "
                f"got keys: {list(step_results.keys())}. "
                f"The task must record the error so the frontend can surface it."
            )
            assert error_message in step_results["COMPARABLE_SEARCH_ERROR"], (
                f"Error message not recorded correctly. "
                f"Expected to find {error_message!r} in "
                f"step_results['COMPARABLE_SEARCH_ERROR']={step_results['COMPARABLE_SEARCH_ERROR']!r}"
            )

    # ------------------------------------------------------------------
    # Test 5: GET /api/analysis/{session_id} includes 'loading' in response
    # ------------------------------------------------------------------

    def test_get_session_includes_loading_field(self, app, client):
        """
        GET /api/analysis/{session_id} must include 'loading' in the response
        body so the frontend polling hook can detect when the async task is done.

        Validates: Requirements 3.4
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, 1)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200, (
            f"Expected HTTP 200, got {response.status_code}"
        )
        data = response.get_json()
        assert data is not None

        assert "loading" in data, (
            f"GET /api/analysis/{{session_id}} response missing 'loading' field. "
            f"Got fields: {list(data.keys())}. "
            f"The 'loading' field is required for the frontend polling hook to "
            f"detect when the async comparable search task is complete."
        )

    def test_get_session_loading_is_false_by_default(self, app, client):
        """
        A freshly created session must have loading=False in the GET response.

        Validates: Requirements 2.4, 3.4
        """
        with app.app_context():
            session_id, _ = _pres_seed_session(app, 1)

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "loading" in data, (
            f"'loading' field missing from GET response. Got: {list(data.keys())}"
        )
        assert data["loading"] is False, (
            f"Expected loading=False for a freshly created session, "
            f"got loading={data['loading']!r}."
        )

    def test_get_session_loading_reflects_true_when_set(self, app, client):
        """
        When session.loading is set to True (e.g. after POST /step/2 enqueues
        the task), GET /api/analysis/{session_id} must return loading=True.

        Validates: Requirements 2.4, 3.4
        """
        from app import db
        from app.models.analysis_session import AnalysisSession

        with app.app_context():
            session_id, _ = _pres_seed_session(app, 1)
            # Manually set loading=True to simulate the enqueued state
            session = AnalysisSession.query.filter_by(session_id=session_id).first()
            session.loading = True
            db.session.commit()

        response = client.get(f"/api/analysis/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert data.get("loading") is True, (
            f"Expected loading=True after setting session.loading=True, "
            f"got loading={data.get('loading')!r}. "
            f"GET /api/analysis/{{session_id}} must reflect the current loading state."
        )


# ===========================================================================
# INTEGRATION TESTS (Task 5.3)
# ===========================================================================
# Three end-to-end integration tests that exercise the full async step-2
# workflow and verify the synchronous steps 3–6 are unaffected.
#
# Key technique: the app fixture patches run_comparable_search_task.delay to
# a no-op.  For integration tests we call run_comparable_search_task(session_id)
# DIRECTLY (simulating the Celery worker) after the route enqueues it.
# We patch app.create_app to return the test app so the task uses the same
# in-memory SQLite database that the test seeded.
#
# Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 3.3
# ===========================================================================


class TestIntegration:
    """
    Integration tests for the comparable-search-fixes spec.

    Covers:
      1. Happy path — full async step-2 lifecycle with mocked Socrata
      2. Error path — Celery task failure surfaces COMPARABLE_SEARCH_ERROR
      3. Synchronous steps unaffected — steps 3–6 still return HTTP 200

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 3.3
    """

    # ------------------------------------------------------------------
    # Shared Socrata mock (36-month window, returns 4 sales for one PIN)
    # ------------------------------------------------------------------

    _PIN = "16233090190000"

    _SALES = [
        ("2024-11-01T00:00:00.000", 310_000),
        ("2024-06-15T00:00:00.000", 295_000),
        ("2023-09-20T00:00:00.000", 280_000),
        ("2022-06-10T00:00:00.000", 260_000),
    ]

    def _make_socrata_mock(self):
        """
        Return a fake _socrata_get that returns 4 sales for _PIN.
        Simulates a 36-month Socrata response with records dated 2022–2024.
        """
        pin = self._PIN
        sales = self._SALES

        def fake_socrata_get(url: str):
            if "pabr-t5kh" in url:
                return [{"pin": pin, "lat": "41.8781", "lon": "-87.6298"}]
            if "wvhk-k5uv" in url:
                return [
                    {
                        "pin": pin,
                        "sale_date": sale_date,
                        "sale_price": str(price),
                        "class": "202",
                    }
                    for sale_date, price in sales
                ]
            if "bcnq-qi2z" in url:
                return [
                    {
                        "pin": pin,
                        "bldg_sf": "1400",
                        "beds": "3",
                        "fbath": "1",
                        "hbath": "1",
                        "age": "40",
                        "ext_wall": "3",
                        "apts": "1",
                    }
                ]
            return []

        return fake_socrata_get

    # ------------------------------------------------------------------
    # Helper: seed a session at step 1 (PROPERTY_FACTS confirmed)
    # ------------------------------------------------------------------

    def _seed_session_at_step1(self, app):
        """
        Create an AnalysisSession at PROPERTY_FACTS with a confirmed subject
        property.  Returns the session_id string.
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.models.property_facts import (
            PropertyFacts, PropertyType, ConstructionType, InteriorCondition,
        )
        import uuid

        with app.app_context():
            session_id = str(uuid.uuid4())
            session = AnalysisSession(
                session_id=session_id,
                user_id="test_user",
                current_step=WorkflowStep.PROPERTY_FACTS,
                completed_steps=["PROPERTY_FACTS"],
                step_results={"PROPERTY_FACTS": {"status": "complete"}},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(session)
            db.session.flush()

            subject = PropertyFacts(
                session_id=session.id,
                address="2315 W Arthington St, Chicago, IL 60612",
                property_type=PropertyType.SINGLE_FAMILY,
                units=1,
                bedrooms=3,
                bathrooms=1.5,
                square_footage=1400,
                lot_size=3750,
                year_built=1920,
                construction_type=ConstructionType.BRICK,
                basement=False,
                parking_spaces=1,
                assessed_value=180_000.0,
                annual_taxes=3_600.0,
                zoning="R-3",
                interior_condition=InteriorCondition.AVERAGE,
                latitude=41.8781,
                longitude=-87.6298,
                data_source="cook_county_assessor",
                user_modified_fields=[],
            )
            db.session.add(subject)
            db.session.commit()

        return session_id

    # ------------------------------------------------------------------
    # Integration Test 1: Happy path — full async step-2 lifecycle
    # ------------------------------------------------------------------

    def test_integration_happy_path_async_step2(self, app, client):
        """
        Integration — happy path:

        1. Seed a session at step 1 (PROPERTY_FACTS confirmed).
        2. POST /api/analysis/{session_id}/step/2 → assert HTTP 202 and
           {"status": "accepted"}.
        3. Assert session.loading is True immediately after the route returns.
        4. Call run_comparable_search_task(session_id) directly (simulating
           the Celery worker), with:
             - app.create_app patched to return the test app (same SQLite DB)
             - CookCountySalesDataSource._socrata_get mocked to return 4 sales
        5. GET /api/analysis/{session_id} and assert:
             - loading = False
             - current_step = "COMPARABLE_SEARCH"
             - comparable_count > 0

        Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.services.comparable_sales_finder import CookCountySalesDataSource
        from celery_worker import run_comparable_search_task

        session_id = self._seed_session_at_step1(app)

        # --- Step A: POST /step/2 → expect 202 ---
        response = client.post(
            f"/api/analysis/{session_id}/step/2",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 202, (
            f"Expected HTTP 202 from POST /step/2, got {response.status_code}. "
            f"Body: {response.get_json()}"
        )
        body = response.get_json()
        assert body is not None
        assert body.get("status") == "accepted", (
            f"Expected status='accepted' in 202 body, got {body!r}"
        )

        # --- Step B: Verify loading=True was set before the route returned ---
        with app.app_context():
            session_obj = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session_obj.loading is True, (
                f"Expected session.loading=True after POST /step/2, "
                f"got {session_obj.loading!r}"
            )

        # --- Step C: Simulate the Celery worker executing the task ---
        # Patch app.create_app so the task's internal app context uses the
        # same in-memory SQLite database that this test seeded.
        # Patch GeminiComparableSearchService.search to return a well-formed result.
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService
        mock_gemini_result = {
            "comparables": [
                {
                    "address": "100 Test St, Chicago, IL 60612",
                    "sale_date": "2024-06-15",
                    "sale_price": 295000.0,
                    "property_type": "SINGLE_FAMILY",
                    "units": 1,
                    "bedrooms": 3,
                    "bathrooms": 1.5,
                    "square_footage": 1400,
                    "lot_size": 3750,
                    "year_built": 1920,
                    "construction_type": "FRAME",
                    "interior_condition": "AVERAGE",
                    "distance_miles": 0.3,
                    "latitude": 41.879,
                    "longitude": -87.630,
                    "similarity_notes": "Similar single-family home.",
                }
            ],
            "narrative": "Test narrative from Gemini.",
        }
        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 return_value=mock_gemini_result,
             ):
            task_result = run_comparable_search_task(session_id)

        # Task must return a result dict (not an error)
        assert isinstance(task_result, dict), (
            f"Task returned unexpected type: {type(task_result)!r}"
        )
        assert "error" not in task_result, (
            f"Task returned an error on the happy path: {task_result!r}"
        )

        # --- Step D: Poll GET /api/analysis/{session_id} and assert final state ---
        get_response = client.get(f"/api/analysis/{session_id}")
        assert get_response.status_code == 200, (
            f"GET /api/analysis/{{session_id}} returned {get_response.status_code}"
        )
        state = get_response.get_json()
        assert state is not None

        assert state.get("loading") is False, (
            f"Expected loading=False after task completion, got {state.get('loading')!r}. "
            f"The Celery task must set loading=False when it finishes."
        )
        assert state.get("current_step") == WorkflowStep.COMPARABLE_SEARCH.name, (
            f"Expected current_step='COMPARABLE_SEARCH' after task completion, "
            f"got {state.get('current_step')!r}. "
            f"The task must advance current_step to COMPARABLE_SEARCH."
        )
        comparable_count = state.get("comparable_count", 0)
        assert comparable_count > 0, (
            f"Expected comparable_count > 0 after task completion with mocked 36-month "
            f"Socrata data, got comparable_count={comparable_count!r}. "
            f"The task must persist comparables to the database."
        )

    # ------------------------------------------------------------------
    # Integration Test 2: Error path — task failure surfaces error
    # ------------------------------------------------------------------

    def test_integration_error_path_task_failure(self, app, client):
        """
        Integration — error path:

        1. Seed a session at step 1.
        2. POST /step/2 → assert 202.
        3. Call run_comparable_search_task(session_id) directly with
           _execute_comparable_search mocked to raise RuntimeError.
        4. GET /api/analysis/{session_id} and assert:
             - loading = False
             - step_results contains 'COMPARABLE_SEARCH_ERROR'

        Validates: Requirements 2.4, 2.5
        """
        from app import db
        from app.models.analysis_session import AnalysisSession
        from celery_worker import run_comparable_search_task

        session_id = self._seed_session_at_step1(app)

        # POST /step/2 to enqueue (no-op delay in test fixture)
        response = client.post(
            f"/api/analysis/{session_id}/step/2",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 202, (
            f"Expected 202 from POST /step/2, got {response.status_code}"
        )

        error_message = "Gemini API unavailable: simulated integration failure"

        # Simulate the Celery worker executing the task, but GeminiComparableSearchService.search raises
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService
        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 side_effect=RuntimeError(error_message),
             ):
            task_result = run_comparable_search_task(session_id)

        # Task must return an error dict, not raise
        assert isinstance(task_result, dict), (
            f"Task should return a dict on failure, got {type(task_result)!r}"
        )
        assert "error" in task_result, (
            f"Task failure result missing 'error' key. Got: {task_result!r}"
        )

        # GET the session and assert error state
        get_response = client.get(f"/api/analysis/{session_id}")
        assert get_response.status_code == 200, (
            f"GET /api/analysis/{{session_id}} returned {get_response.status_code}"
        )
        state = get_response.get_json()
        assert state is not None

        assert state.get("loading") is False, (
            f"Expected loading=False after task failure, got {state.get('loading')!r}. "
            f"The task must set loading=False even when _execute_comparable_search raises."
        )

        step_results = state.get("step_results", {})
        assert "COMPARABLE_SEARCH_ERROR" in step_results, (
            f"Expected 'COMPARABLE_SEARCH_ERROR' in step_results after task failure, "
            f"got keys: {list(step_results.keys())}. "
            f"The task must record the error so the frontend can surface it."
        )
        assert error_message in step_results["COMPARABLE_SEARCH_ERROR"], (
            f"Error message not recorded correctly in step_results. "
            f"Expected to find {error_message!r} in "
            f"step_results['COMPARABLE_SEARCH_ERROR']="
            f"{step_results['COMPARABLE_SEARCH_ERROR']!r}"
        )

    # ------------------------------------------------------------------
    # Integration Test 3: Synchronous steps 3–6 unaffected after step 2
    # ------------------------------------------------------------------

    def test_integration_synchronous_steps_3_to_6_unaffected(self, app, client):
        """
        Integration — synchronous steps unaffected:

        After step 2 completes (via the Celery task), advance through steps
        3–6 using the normal synchronous path.  Assert each POST returns
        HTTP 200 and the session advances correctly.

        Steps:
          3 = COMPARABLE_REVIEW  (no-op, returns ready_for_review)
          4 = WEIGHTED_SCORING   (mocked)
          5 = VALUATION_MODELS   (mocked)
          6 = REPORT_GENERATION  (mocked)

        Validates: Requirements 3.3
        """
        from app import db
        from app.models.analysis_session import AnalysisSession, WorkflowStep
        from app.services.comparable_sales_finder import CookCountySalesDataSource
        from celery_worker import run_comparable_search_task

        session_id = self._seed_session_at_step1(app)

        # --- Step 2: POST /step/2 → 202, then run task directly ---
        response = client.post(
            f"/api/analysis/{session_id}/step/2",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 202, (
            f"Expected 202 from POST /step/2, got {response.status_code}"
        )

        # Run the Celery task directly with mocked Gemini to complete step 2
        from app.services.gemini_comparable_search_service import GeminiComparableSearchService
        mock_gemini_result = {
            "comparables": [
                {
                    "address": "100 Test St, Chicago, IL 60612",
                    "sale_date": "2024-06-15",
                    "sale_price": 295000.0,
                    "property_type": "SINGLE_FAMILY",
                    "units": 1,
                    "bedrooms": 3,
                    "bathrooms": 1.5,
                    "square_footage": 1400,
                    "lot_size": 3750,
                    "year_built": 1920,
                    "construction_type": "FRAME",
                    "interior_condition": "AVERAGE",
                    "distance_miles": 0.3,
                    "latitude": 41.879,
                    "longitude": -87.630,
                    "similarity_notes": "Similar single-family home.",
                }
            ],
            "narrative": "Test narrative from Gemini.",
        }
        with patch("app.create_app", return_value=app), \
             patch.object(
                 GeminiComparableSearchService,
                 "search",
                 return_value=mock_gemini_result,
             ):
            task_result = run_comparable_search_task(session_id)

        assert "error" not in task_result, (
            f"Step 2 task failed unexpectedly: {task_result!r}"
        )

        # Verify step 2 completed and session is at COMPARABLE_SEARCH
        with app.app_context():
            session_obj = AnalysisSession.query.filter_by(session_id=session_id).first()
            assert session_obj.current_step == WorkflowStep.COMPARABLE_SEARCH, (
                f"Expected current_step=COMPARABLE_SEARCH after task, "
                f"got {session_obj.current_step!r}"
            )
            assert session_obj.loading is False, (
                f"Expected loading=False after task, got {session_obj.loading!r}"
            )

        # --- Steps 3–6: advance synchronously, assert each returns 200 ---
        step_mock_results = {
            3: {"status": "ready_for_review"},
            4: {"ranked_count": 4, "top_score": 0.85, "status": "complete"},
            5: {
                "arv_range": {
                    "conservative": 280_000,
                    "likely": 300_000,
                    "aggressive": 320_000,
                },
                "confidence_score": 0.82,
                "comparable_valuations_count": 4,
                "status": "complete",
            },
            6: {"report_sections": ["summary", "comparables"], "status": "complete"},
        }

        expected_step_names = {
            3: WorkflowStep.COMPARABLE_REVIEW.name,
            4: WorkflowStep.WEIGHTED_SCORING.name,
            5: WorkflowStep.VALUATION_MODELS.name,
            6: WorkflowStep.REPORT_GENERATION.name,
        }

        for step_number in [3, 4, 5, 6]:
            # Mock both _execute_step (to avoid real computation) and
            # _validate_step_completion (to bypass pre-condition DB checks
            # that would fail because the mocked steps don't persist real
            # child records like RankedComparable or ValuationResult).
            with patch(
                "app.controllers.workflow_controller.WorkflowController._execute_step",
                return_value=step_mock_results[step_number],
            ), patch(
                "app.controllers.workflow_controller.WorkflowController._validate_step_completion",
                return_value=[],  # no warnings, no hard errors
            ):
                step_response = client.post(
                    f"/api/analysis/{session_id}/step/{step_number}",
                    json={},
                    content_type="application/json",
                )

            assert step_response.status_code == 200, (
                f"Step {step_number} returned HTTP {step_response.status_code} "
                f"(expected 200). Steps 3–6 must remain synchronous and return 200. "
                f"Response body: {step_response.get_json()}"
            )
            assert step_response.status_code != 202, (
                f"Step {step_number} returned 202 — only step 2 should be async."
            )

            step_data = step_response.get_json()
            assert step_data is not None, (
                f"Step {step_number} returned an empty response body."
            )
            assert "current_step" in step_data, (
                f"Step {step_number} synchronous response missing 'current_step'. "
                f"Got: {step_data}"
            )
            assert step_data["current_step"] == expected_step_names[step_number], (
                f"Step {step_number} advanced to wrong step: "
                f"expected {expected_step_names[step_number]!r}, "
                f"got {step_data['current_step']!r}"
            )
            assert "session_id" in step_data, (
                f"Step {step_number} synchronous response missing 'session_id'. "
                f"Got: {step_data}"
            )


# ===========================================================================
# REGRESSION TEST — Socrata Sync Endpoint Preserved (Task 15, Requirement 8.1)
# ===========================================================================
# Verifies that POST /api/cache/socrata/sync still returns the expected
# HTTP 202 response with {"task_id": ..., "dataset": ...} after the Gemini
# comparable search is introduced.
#
# Requirement 8.1: The Application SHALL preserve the POST /api/cache/socrata/sync
# endpoint and its existing behavior after the Gemini comparable search is introduced.
#
# Validates: Requirements 8.1, 8.4
# ===========================================================================


class TestSocrataSyncEndpointPreserved:
    """
    Regression guard: POST /api/cache/socrata/sync must continue to return
    HTTP 202 with the expected JSON shape after the Gemini comparable search
    is introduced.

    Requirement 8.4 decouples WorkflowController from ComparableSalesFinder,
    but the Socrata cache infrastructure (including this endpoint) must remain
    completely intact.

    Validates: Requirements 8.1, 8.4
    """

    def test_socrata_sync_endpoint_preserved(self, client):
        """
        POST /api/cache/socrata/sync with dataset='all' must return HTTP 202
        with a JSON body containing 'task_id' and 'dataset' keys.

        This is a regression guard: the endpoint must be unaffected by the
        introduction of GeminiComparableSearchService and the removal of
        ComparableSalesFinder from WorkflowController.

        Validates: Requirements 8.1, 8.4
        """
        mock_result = MagicMock()
        mock_result.id = "regression-guard-task-id-001"

        with patch(
            "celery_worker.socrata_cache_refresh_task.delay",
            return_value=mock_result,
        ):
            response = client.post(
                "/api/cache/socrata/sync",
                json={"dataset": "all"},
                content_type="application/json",
            )

        # Endpoint must still return HTTP 202
        assert response.status_code == 202, (
            f"POST /api/cache/socrata/sync returned HTTP {response.status_code} "
            f"(expected 202). The Socrata sync endpoint must be preserved after "
            f"the Gemini comparable search is introduced. "
            f"Response body: {response.get_json()}"
        )

        data = response.get_json()
        assert data is not None, (
            "POST /api/cache/socrata/sync returned an empty response body. "
            "Expected JSON with 'task_id' and 'dataset' keys."
        )

        # Response must contain 'task_id'
        assert "task_id" in data, (
            f"POST /api/cache/socrata/sync response missing 'task_id' key. "
            f"Got keys: {list(data.keys())}. "
            f"The endpoint response shape must be preserved."
        )

        # Response must contain 'dataset' echoing the request value
        assert "dataset" in data, (
            f"POST /api/cache/socrata/sync response missing 'dataset' key. "
            f"Got keys: {list(data.keys())}. "
            f"The endpoint response shape must be preserved."
        )
        assert data["dataset"] == "all", (
            f"POST /api/cache/socrata/sync response 'dataset' field is "
            f"{data['dataset']!r} (expected 'all'). "
            f"The endpoint must echo the requested dataset name."
        )

        # task_id must match the mocked Celery result
        assert data["task_id"] == "regression-guard-task-id-001", (
            f"POST /api/cache/socrata/sync response 'task_id' is "
            f"{data['task_id']!r} (expected 'regression-guard-task-id-001'). "
            f"The endpoint must return the Celery task ID."
        )

    def test_socrata_sync_endpoint_returns_202_for_specific_datasets(self, client):
        """
        POST /api/cache/socrata/sync with a specific dataset name must also
        return HTTP 202 with the correct dataset echoed in the response.

        Validates: Requirements 8.1
        """
        for dataset in ["parcel_universe", "parcel_sales", "improvement_characteristics"]:
            mock_result = MagicMock()
            mock_result.id = f"task-{dataset}"

            with patch(
                "celery_worker.socrata_cache_refresh_task.delay",
                return_value=mock_result,
            ):
                response = client.post(
                    "/api/cache/socrata/sync",
                    json={"dataset": dataset},
                    content_type="application/json",
                )

            assert response.status_code == 202, (
                f"POST /api/cache/socrata/sync with dataset={dataset!r} returned "
                f"HTTP {response.status_code} (expected 202). "
                f"All dataset variants must remain functional."
            )

            data = response.get_json()
            assert data is not None
            assert data.get("dataset") == dataset, (
                f"Response 'dataset' field is {data.get('dataset')!r} "
                f"(expected {dataset!r})."
            )
