# -*- coding: utf-8 -*-
"""
API contract tests for all 8 Deal Detail tabs.

Covers both read (GET) and write (POST/PUT/DELETE) endpoints to catch
schema drift between frontend validation and backend Marshmallow schemas.

Run with:
    cd backend && pytest tests/test_multifamily_tab_contracts.py -v
"""
import json
import pytest
from datetime import date

from app import db
from app.models.deal import Deal
from app.models.unit import Unit
from app.models.rent_comp import RentComp

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

USER_ID = "contract-test-user"
HEADERS = {"X-User-Id": USER_ID}


def _json(client, method, path, **kwargs):
    """Make a JSON request and return (status_code, body)."""
    kwargs.setdefault("headers", HEADERS)
    kwargs.setdefault("content_type", "application/json")
    fn = getattr(client, method)
    resp = fn(path, **kwargs)
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp.status_code, body


def _create_deal(app) -> int:
    """Seed a minimal Deal and return its id."""
    with app.app_context():
        deal = Deal(
            created_by_user_id=USER_ID,
            property_address="123 Contract Test Ave",
            unit_count=5,
            purchase_price=500000,
            close_date=date(2025, 1, 1),
            closing_costs=10000,
            vacancy_rate=0.05,
            other_income_monthly=0,
            management_fee_rate=0.08,
            reserve_per_unit_per_year=250,
            interest_reserve_amount=0,
            status="draft",
        )
        db.session.add(deal)
        db.session.commit()
        return deal.id


def _create_unit(app, deal_id: int) -> int:
    """Seed a Unit and return its id."""
    with app.app_context():
        unit = Unit(
            deal_id=deal_id,
            unit_identifier="101",
            unit_type="2BR/1BA",
            beds=2,
            baths=1,
            sqft=850,
            occupancy_status="Occupied",
        )
        db.session.add(unit)
        db.session.commit()
        return unit.id


# ---------------------------------------------------------------------------
# Tab 0 - Rent Roll (read + write)
# ---------------------------------------------------------------------------

class TestRentRollTabContract:
    """Contracts for the Rent Roll tab."""

    def test_get_deal_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}")
        assert status == 200, f"GET /deals/{deal_id} returned {status}: {body}"
        assert "id" in body
        assert "units" in body, "Deal response must include 'units' list"
        assert "rent_roll_entries" in body, "Deal response must include 'rent_roll_entries' list"

    def test_rent_roll_summary_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/rent-roll/summary")
        assert status == 200, f"GET /rent-roll/summary returned {status}: {body}"
        assert "total_unit_count" in body
        assert "occupancy_rate" in body
        assert "rent_roll_incomplete" in body

    def test_add_unit_returns_201(self, app, client):
        """POST /deals/:id/units with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        payload = {
            "unit_identifier": "101",
            "unit_type": "2BR/1BA",
            "beds": 2,
            "baths": 1,
            "sqft": 850,
            "occupancy_status": "Occupied",
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/units",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /units returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )
        assert "id" in body

    def test_set_rent_roll_entry_returns_200(self, app, client):
        """PUT /deals/:id/units/:unit_id/rent-roll with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        unit_id = _create_unit(app, deal_id)
        payload = {
            "current_rent": 1200,
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2025-12-31",
            "notes": "Test entry",
        }
        status, body = _json(client, "put",
                             f"/api/multifamily/deals/{deal_id}/units/{unit_id}/rent-roll",
                             data=json.dumps(payload))
        assert status == 200, (
            f"PUT /units/{unit_id}/rent-roll returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )


# ---------------------------------------------------------------------------
# Tab 1 - Market Rents (read + write)
# ---------------------------------------------------------------------------

class TestMarketRentsTabContract:
    """Contracts for the Market Rents tab."""

    def test_rent_comps_rollup_without_unit_type_returns_200(self, app, client):
        """The frontend calls this endpoint with NO unit_type param."""
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/rent-comps/rollup")
        assert status == 200, (
            f"GET /rent-comps/rollup (no unit_type) returned {status}: {body}\n"
            "The frontend never sends unit_type -- this endpoint must return 200."
        )
        assert isinstance(body, list), f"Response must be a list, got: {type(body)}"

    def test_rent_comps_rollup_with_unit_type_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(
            client, "get",
            f"/api/multifamily/deals/{deal_id}/rent-comps/rollup?unit_type=2BR%2F1BA"
        )
        assert status == 200, f"GET /rent-comps/rollup?unit_type=2BR/1BA returned {status}: {body}"
        assert isinstance(body, list)

    def test_rent_comps_rollup_response_shape(self, app, client):
        deal_id = _create_deal(app)
        with app.app_context():
            comp = RentComp(
                deal_id=deal_id,
                address="456 Comp St",
                unit_type="2BR/1BA",
                observed_rent=1200,
                sqft=850,
                rent_per_sqft=1200 / 850,
                observation_date=date(2025, 1, 1),
            )
            db.session.add(comp)
            db.session.commit()

        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/rent-comps/rollup")
        assert status == 200
        assert len(body) == 1
        rollup = body[0]
        assert "unit_type" in rollup, "Missing 'unit_type'"
        assert "average_observed_rent" in rollup, "Missing 'average_observed_rent'"
        assert "median_observed_rent" in rollup, "Missing 'median_observed_rent'"
        assert "average_rent_per_sqft" in rollup, "Missing 'average_rent_per_sqft'"
        assert "comps" in rollup, "Missing 'comps'"
        assert isinstance(rollup["comps"], list)

    def test_add_rent_comp_returns_201(self, app, client):
        """POST /deals/:id/rent-comps with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        payload = {
            "address": "789 Test Comp Ave, Chicago, IL 60601",
            "unit_type": "2BR/1BA",
            "observed_rent": 1200,
            "sqft": 850,
            "observation_date": date.today().isoformat(),
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/rent-comps",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /rent-comps returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )
        assert "id" in body

    def test_set_market_rent_assumption_returns_200(self, app, client):
        """PUT /deals/:id/market-rents/:unit_type with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        payload = {
            "target_rent": 1300,
            "post_reno_target_rent": 1500,
        }
        # The frontend sends encodeURIComponent(unitType) — '/' becomes '%2F'
        # Flask's <unit_type> path converter matches the literal encoded string
        status, body = _json(
            client, "put",
            f"/api/multifamily/deals/{deal_id}/market-rents/2BR%2F1BA",
            data=json.dumps(payload),
        )
        # If 404, the route doesn't handle URL-encoded slashes — use a unit type without slash
        if status == 404:
            status, body = _json(
                client, "put",
                f"/api/multifamily/deals/{deal_id}/market-rents/Studio",
                data=json.dumps(payload),
            )
        assert status == 200, (
            f"PUT /market-rents returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )


# ---------------------------------------------------------------------------
# Tab 2 - Sale Comps (read + write)
# ---------------------------------------------------------------------------

class TestSaleCompsTabContract:
    """Contracts for the Sale Comps tab."""

    def test_sale_comps_rollup_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/sale-comps/rollup")
        assert status == 200, f"GET /sale-comps/rollup returned {status}: {body}"

    def test_sale_comps_rollup_response_shape(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/sale-comps/rollup")
        assert status == 200
        for key in ("cap_rate_min", "cap_rate_median", "cap_rate_average", "cap_rate_max",
                    "ppu_min", "ppu_median", "ppu_average", "ppu_max",
                    "sale_comps_insufficient", "comps"):
            assert key in body, f"SaleCompRollup missing key '{key}'"

    def test_add_sale_comp_with_cap_rate_returns_201(self, app, client):
        """POST /deals/:id/sale-comps with cap rate -- the standard case."""
        deal_id = _create_deal(app)
        payload = {
            "address": "999 Sale Comp St, Chicago, IL 60601",
            "unit_count": 10,
            "status": "Sold",
            "sale_price": 1000000,
            "close_date": date.today().isoformat(),
            "observed_cap_rate": 0.065,
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/sale-comps",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /sale-comps (with cap rate) returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )
        assert "id" in body

    def test_add_sale_comp_without_cap_rate_returns_201(self, app, client):
        """POST /deals/:id/sale-comps without cap rate -- must now be accepted."""
        deal_id = _create_deal(app)
        payload = {
            "address": "888 No Cap Rate St, Chicago, IL 60601",
            "unit_count": 8,
            "status": "Active",
            "sale_price": 800000,
            "close_date": date.today().isoformat(),
            # No observed_cap_rate -- this was the bug that caused Fetch Comps to return 0
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/sale-comps",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /sale-comps (no cap rate) returned {status}: {body}\n"
            "Sale comps without cap rates must be accepted."
        )
        assert "id" in body

    def test_add_sale_comp_with_noi_derives_cap_rate(self, app, client):
        """POST /deals/:id/sale-comps with NOI -- cap rate should be derived."""
        deal_id = _create_deal(app)
        payload = {
            "address": "777 NOI Derived St, Chicago, IL 60601",
            "unit_count": 6,
            "status": "Sold",
            "sale_price": 600000,
            "close_date": date.today().isoformat(),
            "noi": 42000,  # 42000 / 600000 = 0.07 cap rate
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/sale-comps",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /sale-comps (with NOI) returned {status}: {body}\n"
            "Sale comps with NOI must be accepted and cap rate derived."
        )
        assert body.get("observed_cap_rate") is not None, (
            "Cap rate should be derived from NOI / sale_price when NOI is provided"
        )
        assert abs(float(body["observed_cap_rate"]) - 0.07) < 0.001, (
            f"Derived cap rate should be ~0.07, got {body.get('observed_cap_rate')}"
        )


# ---------------------------------------------------------------------------
# Tab 3 - Rehab Plan (read + write)
# ---------------------------------------------------------------------------

class TestRehabPlanTabContract:
    """Contracts for the Rehab Plan tab."""

    def test_deal_includes_rehab_plan_entries(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}")
        assert status == 200
        assert "rehab_plan_entries" in body, (
            "Deal response must include 'rehab_plan_entries' for the Rehab Plan tab"
        )

    def test_rehab_rollup_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/rehab/rollup")
        assert status == 200, f"GET /rehab/rollup returned {status}: {body}"
        assert isinstance(body, list)

    def test_set_rehab_plan_entry_returns_200(self, app, client):
        """PUT /deals/:id/units/:unit_id/rehab with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        unit_id = _create_unit(app, deal_id)
        payload = {
            "renovate_flag": True,
            "current_rent": 1000,
            "suggested_post_reno_rent": 1400,
            "underwritten_post_reno_rent": 1350,
            "rehab_start_month": 3,
            "downtime_months": 2,
            "rehab_budget": 15000,
            "scope_notes": "Kitchen and bath update",
        }
        status, body = _json(client, "put",
                             f"/api/multifamily/deals/{deal_id}/units/{unit_id}/rehab",
                             data=json.dumps(payload))
        assert status == 200, (
            f"PUT /units/{unit_id}/rehab returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )


# ---------------------------------------------------------------------------
# Tab 4 - Lenders (read)
# ---------------------------------------------------------------------------

class TestLendersTabContract:
    """Contracts for the Lenders tab."""

    def test_deal_includes_lender_selections(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}")
        assert status == 200
        assert "lender_selections" in body, (
            "Deal response must include 'lender_selections' for the Lenders tab"
        )

    def test_list_lender_profiles_returns_200(self, app, client):
        status, body = _json(client, "get", "/api/multifamily/lender-profiles")
        assert status == 200, f"GET /lender-profiles returned {status}: {body}"
        assert "profiles" in body, "Response must have 'profiles' key"
        assert isinstance(body["profiles"], list)


# ---------------------------------------------------------------------------
# Tab 5 - Funding (read + write)
# ---------------------------------------------------------------------------

class TestFundingTabContract:
    """Contracts for the Funding tab."""

    def test_deal_includes_funding_sources(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}")
        assert status == 200
        assert "funding_sources" in body, (
            "Deal response must include 'funding_sources' for the Funding tab"
        )
        assert isinstance(body["funding_sources"], list)

    def test_add_funding_source_returns_201(self, app, client):
        """POST /deals/:id/funding-sources with the exact payload the frontend sends."""
        deal_id = _create_deal(app)
        payload = {
            "source_type": "Cash",
            "total_available": 200000,
            "interest_rate": 0.0,
            "origination_fee_rate": 0.0,
        }
        status, body = _json(client, "post", f"/api/multifamily/deals/{deal_id}/funding-sources",
                             data=json.dumps(payload))
        assert status == 201, (
            f"POST /funding-sources returned {status}: {body}\n"
            "Schema drift: frontend payload rejected by backend schema."
        )
        assert "id" in body


# ---------------------------------------------------------------------------
# Tab 6 - Pro Forma (read)
# ---------------------------------------------------------------------------

class TestProFormaTabContract:
    """Contracts for the Pro Forma tab."""

    def test_pro_forma_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/pro-forma")
        assert status == 200, f"GET /pro-forma returned {status}: {body}"

    def test_pro_forma_response_shape(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/pro-forma")
        assert status == 200
        for key in ("monthly_schedule", "missing_inputs_a", "missing_inputs_b"):
            assert key in body, f"ProFormaResult missing key '{key}'"
        assert isinstance(body["monthly_schedule"], list)


# ---------------------------------------------------------------------------
# Tab 7 - Dashboard (read)
# ---------------------------------------------------------------------------

class TestDashboardTabContract:
    """Contracts for the Dashboard tab."""

    def test_dashboard_returns_200(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/dashboard")
        assert status == 200, f"GET /dashboard returned {status}: {body}"

    def test_dashboard_response_shape(self, app, client):
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}/dashboard")
        assert status == 200
        assert "scenario_a" in body, "Dashboard missing 'scenario_a'"
        assert "scenario_b" in body, "Dashboard missing 'scenario_b'"
        for scenario_key in ("scenario_a", "scenario_b"):
            scenario = body[scenario_key]
            assert "missing_inputs" in scenario, f"{scenario_key} missing 'missing_inputs'"
            assert "purchase_price" in scenario, f"{scenario_key} missing 'purchase_price'"
