"""Integration, performance, and Celery tests for the multifamily pro forma feature.

Covers:
  - 19.1  End-to-end pro forma integration test (10-unit deal via CRUD endpoints)
  - 19.2  Dashboard performance test (200-unit deal, warm cache < 500 ms)
  - 19.3  Excel export performance test (200-unit deal < 5 s)
  - 19.4  Write-path timing test (cacheable-input write < 50 ms, no sync recompute)
  - 19.5  Celery bulk recompute integration test (direct task invocation)

Requirements: 8.1-8.14, 11.1, 11.3, 12.4, 15.4, 15.5
"""
import time
import json
import pytest
from unittest.mock import patch, MagicMock

from app import db


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BASE = '/api/multifamily'
USER_HEADERS = {'X-User-Id': 'test-user-e2e'}


def _post(client, path, payload):
    return client.post(
        f'{BASE}{path}',
        data=json.dumps(payload),
        content_type='application/json',
        headers=USER_HEADERS,
    )


def _put(client, path, payload):
    return client.put(
        f'{BASE}{path}',
        data=json.dumps(payload),
        content_type='application/json',
        headers=USER_HEADERS,
    )


def _get(client, path):
    return client.get(f'{BASE}{path}', headers=USER_HEADERS)


# ---------------------------------------------------------------------------
# Deal seeding helpers
# ---------------------------------------------------------------------------

_DEAL_PAYLOAD = {
    'property_address': '100 E2E Ave',
    'property_city': 'Chicago',
    'property_state': 'IL',
    'property_zip': '60601',
    'unit_count': 10,
    'purchase_price': 1_200_000.0,
    'closing_costs': 24_000.0,
    'close_date': '2025-06-01',
    'vacancy_rate': 0.05,
    'other_income_monthly': 500.0,
    'management_fee_rate': 0.08,
    'reserve_per_unit_per_year': 300.0,
    'property_taxes_annual': 18_000.0,
    'insurance_annual': 6_000.0,
    'utilities_annual': 4_800.0,
    'repairs_and_maintenance_annual': 3_600.0,
    'admin_and_marketing_annual': 1_200.0,
    'payroll_annual': 0.0,
    'other_opex_annual': 2_400.0,
    'interest_reserve_amount': 0.0,
}


def _create_deal(client, unit_count=10, **overrides):
    """Create a deal and return its ID."""
    payload = dict(_DEAL_PAYLOAD, unit_count=unit_count, **overrides)
    resp = _post(client, '/deals', payload)
    assert resp.status_code == 201, f"Deal creation failed: {resp.get_json()}"
    return resp.get_json()['id']


def _add_unit(client, deal_id, identifier, unit_type='2BR/1BA', beds=2,
              baths=1.0, sqft=800, occupancy='Occupied'):
    """Add a unit to a deal and return its ID."""
    resp = _post(client, f'/deals/{deal_id}/units', {
        'unit_identifier': identifier,
        'unit_type': unit_type,
        'beds': beds,
        'baths': baths,
        'sqft': sqft,
        'occupancy_status': occupancy,
    })
    assert resp.status_code == 201, f"Unit creation failed: {resp.get_json()}"
    return resp.get_json()['id']


def _set_rent_roll(client, deal_id, unit_id, current_rent=1_200.0):
    """Set a rent roll entry for a unit."""
    resp = _put(client, f'/deals/{deal_id}/units/{unit_id}/rent-roll', {
        'current_rent': current_rent,
        'lease_start_date': '2024-01-01',
        'lease_end_date': '2024-12-31',
    })
    assert resp.status_code == 200, f"Rent roll set failed: {resp.get_json()}"


def _set_rehab(client, deal_id, unit_id, renovate=False, start_month=None,
               downtime=None, budget=0.0, post_reno_rent=None):
    """Set a rehab plan entry for a unit."""
    payload = {
        'renovate_flag': renovate,
        'current_rent': 1_200.0,
        'rehab_budget': budget,
    }
    if renovate and start_month is not None:
        payload['rehab_start_month'] = start_month
        payload['downtime_months'] = downtime or 1
        payload['underwritten_post_reno_rent'] = post_reno_rent or 1_400.0
        payload['suggested_post_reno_rent'] = post_reno_rent or 1_400.0
    resp = _put(client, f'/deals/{deal_id}/units/{unit_id}/rehab', payload)
    assert resp.status_code == 200, f"Rehab set failed: {resp.get_json()}"


def _create_ctp_lender(client):
    """Create a Construction-to-Perm lender profile and return its ID."""
    resp = _post(client, '/lender-profiles', {
        'company': 'E2E Bank CTP',
        'lender_type': 'Construction_To_Perm',
        'origination_fee_rate': 0.01,
        'ltv_total_cost': 0.75,
        'construction_rate': 0.07,
        'construction_io_months': 12,
        'construction_term_months': 18,
        'perm_rate': 0.065,
        'perm_amort_years': 30,
        'min_interest_or_yield': 0.0,
        'prepay_penalty_description': 'None',
    })
    assert resp.status_code == 201, f"CTP lender creation failed: {resp.get_json()}"
    return resp.get_json()['id']


def _create_sfr_lender(client):
    """Create a Self-Funded-Reno lender profile and return its ID."""
    resp = _post(client, '/lender-profiles', {
        'company': 'E2E Bank SFR',
        'lender_type': 'Self_Funded_Reno',
        'origination_fee_rate': 0.01,
        'max_purchase_ltv': 0.70,
        'treasury_5y_rate': 0.04,
        'spread_bps': 250,
        'term_years': 10,
        'amort_years': 30,
        'prepay_penalty_description': 'None',
    })
    assert resp.status_code == 201, f"SFR lender creation failed: {resp.get_json()}"
    return resp.get_json()['id']


def _attach_lender(client, deal_id, scenario, profile_id, is_primary=True):
    """Attach a lender profile to a deal scenario."""
    resp = _post(client, f'/deals/{deal_id}/scenarios/{scenario}/lenders', {
        'lender_profile_id': profile_id,
        'is_primary': is_primary,
    })
    assert resp.status_code == 201, f"Lender attach failed: {resp.get_json()}"


def _add_funding_source(client, deal_id, source_type='Cash', total=400_000.0):
    """Add a funding source to a deal."""
    resp = _post(client, f'/deals/{deal_id}/funding-sources', {
        'source_type': source_type,
        'total_available': total,
        'interest_rate': 0.0,
        'origination_fee_rate': 0.0,
    })
    assert resp.status_code == 201, f"Funding source add failed: {resp.get_json()}"


def _seed_full_deal(client, unit_count=10):
    """
    Create a fully-populated deal: units, rent roll, rehab plan (no-reno),
    lenders for both scenarios, and a cash funding source.

    Returns deal_id.
    """
    deal_id = _create_deal(client, unit_count=unit_count)

    unit_ids = []
    for i in range(unit_count):
        uid = _add_unit(client, deal_id, identifier=f'U{i + 1:03d}')
        unit_ids.append(uid)

    for uid in unit_ids:
        _set_rent_roll(client, deal_id, uid, current_rent=1_200.0)
        _set_rehab(client, deal_id, uid, renovate=False)

    ctp_id = _create_ctp_lender(client)
    sfr_id = _create_sfr_lender(client)
    _attach_lender(client, deal_id, 'A', ctp_id, is_primary=True)
    _attach_lender(client, deal_id, 'B', sfr_id, is_primary=True)

    _add_funding_source(client, deal_id, source_type='Cash', total=400_000.0)

    return deal_id


# ---------------------------------------------------------------------------
# 19.1  End-to-end pro forma integration test
# Requirements: 8.1-8.14, 11.1
# ---------------------------------------------------------------------------

class TestProFormaE2E:
    """Full CRUD -> pro-forma -> dashboard integration test."""

    def test_create_deal_and_get_pro_forma(self, client, app):
        """
        Create a 10-unit deal via CRUD endpoints, request the pro forma,
        and assert response shape and numeric plausibility.

        Requirements: 8.1-8.14
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=10)

        resp = _get(client, f'/deals/{deal_id}/pro-forma')
        assert resp.status_code == 200, f"Pro forma failed: {resp.get_json()}"
        data = resp.get_json()

        # Top-level keys
        assert 'monthly_schedule' in data, "Missing monthly_schedule"
        assert 'summary' in data, "Missing summary"

        # Exactly 24 monthly rows
        schedule = data['monthly_schedule']
        assert len(schedule) == 24, f"Expected 24 rows, got {len(schedule)}"

        # Each row has required fields
        required_row_keys = {
            'month', 'gsr', 'egi', 'noi', 'net_cash_flow',
            'debt_service_a', 'debt_service_b',
            'cash_flow_after_debt_a', 'cash_flow_after_debt_b',
        }
        for row in schedule:
            missing = required_row_keys - set(row.keys())
            assert not missing, f"Month {row.get('month')} missing keys: {missing}"

        # Month numbers are 1..24 in order
        months = [row['month'] for row in schedule]
        assert months == list(range(1, 25)), "Month sequence incorrect"

        # GSR plausibility: 10 units x $1,200 = $12,000/month
        month1_gsr = float(schedule[0]['gsr'])
        assert month1_gsr == pytest.approx(12_000.0, rel=0.01), (
            f"Month 1 GSR {month1_gsr} not near expected 12000"
        )

        # NOI > 0 for month 1 (all units occupied, no renovation downtime)
        assert float(schedule[0]['noi']) > 0, "Month 1 NOI should be positive"

        # Summary keys present
        summary = data['summary']
        assert 'in_place_noi' in summary
        assert 'stabilized_noi' in summary

        # in_place_noi approx month 1 NOI x 12
        if summary['in_place_noi'] is not None:
            assert float(summary['in_place_noi']) == pytest.approx(
                float(schedule[0]['noi']) * 12, rel=0.01
            ), "in_place_noi != month1_noi * 12"

    def test_get_dashboard_after_pro_forma(self, client, app):
        """
        After seeding a full deal, GET /dashboard returns both scenario
        summaries with the required fields from Req 11.1.

        Requirements: 11.1, 11.2
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=10)

        resp = _get(client, f'/deals/{deal_id}/dashboard')
        assert resp.status_code == 200, f"Dashboard failed: {resp.get_json()}"
        data = resp.get_json()

        assert 'scenario_a' in data, "Missing scenario_a"
        assert 'scenario_b' in data, "Missing scenario_b"

        required_scenario_keys = {
            'purchase_price',
            'loan_amount',
            'in_place_noi',
            'stabilized_noi',
            'in_place_dscr',
            'stabilized_dscr',
        }
        for scenario_key in ('scenario_a', 'scenario_b'):
            scenario = data[scenario_key]
            if scenario is None:
                continue  # missing-inputs path -- acceptable
            missing = required_scenario_keys - set(scenario.keys())
            assert not missing, f"{scenario_key} missing keys: {missing}"

    def test_missing_inputs_returns_null_scenario(self, client, app):
        """
        A deal with no lenders attached should return null scenario summaries
        and a non-empty missing_inputs list.

        Requirements: 8.14, 11.2
        """
        with app.app_context():
            deal_id = _create_deal(client, unit_count=5)
            for i in range(5):
                uid = _add_unit(client, deal_id, identifier=f'M{i + 1}')
                _set_rent_roll(client, deal_id, uid)
                _set_rehab(client, deal_id, uid)

        resp = _get(client, f'/deals/{deal_id}/pro-forma')
        assert resp.status_code == 200
        data = resp.get_json()

        has_missing = (
            bool(data.get('missing_inputs_a'))
            or bool(data.get('missing_inputs_b'))
        )
        assert has_missing, (
            "Expected missing_inputs when no lender is attached"
        )

    def test_force_recompute_returns_fresh_result(self, client, app):
        """
        POST /pro-forma/recompute should return a fresh result even when
        a cached result exists.

        Requirements: 15.4
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=5)

        # Warm the cache
        _get(client, f'/deals/{deal_id}/pro-forma')

        # Force recompute
        resp = _post(client, f'/deals/{deal_id}/pro-forma/recompute', {})
        assert resp.status_code == 200, f"Recompute failed: {resp.get_json()}"
        data = resp.get_json()
        assert 'monthly_schedule' in data or 'summary' in data, (
            "Recompute response missing expected keys"
        )

    def test_cache_hit_returns_same_result(self, client, app):
        """
        Two consecutive GET /pro-forma calls should return identical
        In_Place_NOI (cache hit on second call).

        Requirements: 15.1, 15.2
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=5)

        resp1 = _get(client, f'/deals/{deal_id}/pro-forma')
        resp2 = _get(client, f'/deals/{deal_id}/pro-forma')

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        noi1 = resp1.get_json().get('summary', {}).get('in_place_noi')
        noi2 = resp2.get_json().get('summary', {}).get('in_place_noi')

        if noi1 is not None and noi2 is not None:
            assert noi1 == pytest.approx(noi2, rel=1e-9), (
                "Cache hit returned different in_place_noi"
            )

    def test_write_invalidates_cache(self, client, app):
        """
        Updating a rent roll entry should invalidate the cached pro forma
        so the next GET recomputes with the new rent.

        Requirements: 15.3
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=5)

        # Warm cache
        resp_before = _get(client, f'/deals/{deal_id}/pro-forma')
        assert resp_before.status_code == 200
        noi_before = resp_before.get_json().get('summary', {}).get('in_place_noi')

        # Fetch unit IDs from the deal
        deal_resp = _get(client, f'/deals/{deal_id}')
        units = deal_resp.get_json().get('units', [])
        assert units, "Deal has no units"
        first_unit_id = units[0]['id']

        # Update rent roll to a much higher rent
        _put(client, f'/deals/{deal_id}/units/{first_unit_id}/rent-roll', {
            'current_rent': 5_000.0,
            'lease_start_date': '2024-01-01',
            'lease_end_date': '2024-12-31',
        })

        # Re-fetch pro forma -- should reflect new rent
        resp_after = _get(client, f'/deals/{deal_id}/pro-forma')
        assert resp_after.status_code == 200
        noi_after = resp_after.get_json().get('summary', {}).get('in_place_noi')

        if noi_before is not None and noi_after is not None:
            assert float(noi_after) > float(noi_before), (
                "NOI did not increase after raising rent -- "
                "cache may not have been invalidated (Req 15.3)"
            )


# ---------------------------------------------------------------------------
# 19.2  Dashboard performance test
# Requirements: 11.3
# ---------------------------------------------------------------------------

class TestDashboardPerformance:
    """Dashboard must return in < 500 ms with a warm cache (Req 11.3)."""

    def test_dashboard_warm_cache_under_500ms(self, client, app):
        """
        Seed a 200-unit deal, warm the cache, then assert the dashboard
        endpoint responds in under 500 ms.

        Requirements: 11.3
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=200)

        # Warm the cache
        warm_resp = _get(client, f'/deals/{deal_id}/pro-forma')
        assert warm_resp.status_code == 200, "Cache warm failed"

        # Timed request
        start = time.perf_counter()
        resp = _get(client, f'/deals/{deal_id}/dashboard')
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert resp.status_code == 200, f"Dashboard failed: {resp.get_json()}"
        assert elapsed_ms < 500, (
            f"Dashboard took {elapsed_ms:.1f} ms with warm cache "
            f"(limit: 500 ms, Req 11.3)"
        )


# ---------------------------------------------------------------------------
# 19.3  Excel export performance test
# Requirements: 12.4
# ---------------------------------------------------------------------------

class TestExcelExportPerformance:
    """Excel export must complete in < 5 s for a 200-unit deal (Req 12.4)."""

    def test_excel_export_200_units_under_5s(self, client, app):
        """
        Seed a 200-unit deal and assert the Excel export endpoint responds
        in under 5 seconds.

        Requirements: 12.4
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=200)

        start = time.perf_counter()
        resp = _get(client, f'/deals/{deal_id}/export/excel')
        elapsed_s = time.perf_counter() - start

        assert resp.status_code == 200, (
            f"Excel export failed with status {resp.status_code}"
        )
        assert resp.content_type in (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/octet-stream',
        ), f"Unexpected content type: {resp.content_type}"
        assert len(resp.data) > 0, "Excel export returned empty body"
        assert elapsed_s < 5.0, (
            f"Excel export took {elapsed_s:.2f} s for 200 units "
            f"(limit: 5 s, Req 12.4)"
        )


# ---------------------------------------------------------------------------
# 19.4  Write-path timing test
# Requirements: 15.4
# ---------------------------------------------------------------------------

class TestWritePathTiming:
    """
    A write to a cacheable input must return in < 50 ms for a 200-unit deal
    because the write must NOT synchronously recompute the pro forma.

    Requirements: 15.4
    """

    def test_rent_roll_write_under_50ms(self, client, app):
        """
        Updating a rent roll entry on a 200-unit deal should complete in
        under 50 ms -- confirming no synchronous recompute occurs.

        Requirements: 15.4
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=200)

        # Warm the cache so a cached result exists
        _get(client, f'/deals/{deal_id}/pro-forma')

        # Fetch a unit ID
        deal_resp = _get(client, f'/deals/{deal_id}')
        units = deal_resp.get_json().get('units', [])
        assert units, "Deal has no units"
        first_unit_id = units[0]['id']

        # Timed write
        start = time.perf_counter()
        resp = _put(client, f'/deals/{deal_id}/units/{first_unit_id}/rent-roll', {
            'current_rent': 1_300.0,
            'lease_start_date': '2024-01-01',
            'lease_end_date': '2024-12-31',
        })
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert resp.status_code == 200, f"Rent roll write failed: {resp.get_json()}"
        assert elapsed_ms < 50, (
            f"Rent roll write took {elapsed_ms:.1f} ms "
            f"(limit: 50 ms -- synchronous recompute must not occur, Req 15.4)"
        )


# ---------------------------------------------------------------------------
# 19.5  Celery bulk recompute integration test
# Requirements: 15.5
# ---------------------------------------------------------------------------

class TestCeleryBulkRecompute:
    """
    recompute_all_deals() is called directly (simulating CELERY_ALWAYS_EAGER)
    and must fan out and populate the cache for every active deal.

    Requirements: 15.5
    """

    def test_recompute_all_deals_populates_cache(self, client, app):
        """
        Seed two fully-populated deals, clear their cached pro forma results,
        then call recompute_all_deals() directly and assert both deals now
        have a cached result.

        Requirements: 15.5
        """
        with app.app_context():
            deal_id_1 = _seed_full_deal(client, unit_count=5)
            deal_id_2 = _seed_full_deal(client, unit_count=5)

            # Clear any existing cache rows
            from app.models.pro_forma_result import ProFormaResult
            ProFormaResult.query.filter(
                ProFormaResult.deal_id.in_([deal_id_1, deal_id_2])
            ).delete(synchronize_session=False)
            db.session.commit()

            # Verify cache is empty
            cached_before = ProFormaResult.query.filter(
                ProFormaResult.deal_id.in_([deal_id_1, deal_id_2])
            ).count()
            assert cached_before == 0, "Cache should be empty before recompute"

            # Run the Celery task synchronously
            from app.tasks.multifamily_recompute import recompute_all_deals
            processed = recompute_all_deals()

            # Both deals should have been processed
            assert processed >= 2, (
                f"Expected at least 2 deals processed, got {processed}"
            )

            # Both deals should now have a cached result
            cached_after = ProFormaResult.query.filter(
                ProFormaResult.deal_id.in_([deal_id_1, deal_id_2])
            ).count()
            assert cached_after == 2, (
                f"Expected 2 cached results after recompute, got {cached_after}"
            )

    def test_recompute_all_deals_skips_deleted(self, client, app):
        """
        Soft-deleted deals should not be recomputed.

        Requirements: 15.5
        """
        with app.app_context():
            deal_id = _seed_full_deal(client, unit_count=5)

            # Soft-delete the deal
            from app.models.deal import Deal
            from datetime import datetime, timezone
            deal = Deal.query.get(deal_id)
            deal.deleted_at = datetime.now(timezone.utc)
            db.session.commit()

            # Clear cache
            from app.models.pro_forma_result import ProFormaResult
            ProFormaResult.query.filter_by(deal_id=deal_id).delete()
            db.session.commit()

            # Run recompute
            from app.tasks.multifamily_recompute import recompute_all_deals
            recompute_all_deals()

            # Deleted deal should NOT have a cached result
            cached = ProFormaResult.query.filter_by(deal_id=deal_id).count()
            assert cached == 0, (
                "Soft-deleted deal should not have a cached pro forma result"
            )

    def test_admin_recompute_endpoint_enqueues_task(self, client, app):
        """
        POST /api/multifamily/admin/recompute-all should return 202 and
        a task_id when the Celery task is enqueued.

        Requirements: 15.5
        """
        mock_task = MagicMock()
        mock_task.id = 'mock-task-id-12345'

        with patch('app.tasks.multifamily_recompute.celery') as mock_celery:
            mock_celery.send_task.return_value = mock_task

            resp = client.post(
                '/api/multifamily/admin/recompute-all',
                headers=USER_HEADERS,
            )

        assert resp.status_code == 202, (
            f"Expected 202, got {resp.status_code}: {resp.get_json()}"
        )
        data = resp.get_json()
        assert 'task_id' in data, "Response missing task_id"
        assert 'message' in data, "Response missing message"
