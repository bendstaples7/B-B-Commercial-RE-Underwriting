"""
User identity contract tests.

Verifies that every authenticated endpoint reads user identity from the
X-User-Id header (via g.user_id) and NOT from the request body.

The regression this prevents: a change to the Axios interceptor that stops
sending user_id in the request body silently breaks endpoints that still
read it from the body — causing 400 or 422 errors that only surface when
a user actually clicks through the flow.

Rule enforced: no endpoint should return 400/422 when user_id is absent
from the request body but present in the X-User-Id header.

Run with:
    cd backend && pytest tests/test_user_identity_contracts.py -v
"""
import json
import pytest
from datetime import date

from app import db
from app.models.deal import Deal

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

USER_ID = "identity-contract-test-user"
HEADERS = {"X-User-Id": USER_ID}  # user_id in header ONLY — never in body


def _json(client, method, path, body=None):
    """Make a JSON request with user_id in header only. Returns (status, body)."""
    kwargs = {
        "headers": HEADERS,
        "content_type": "application/json",
    }
    if body is not None:
        kwargs["data"] = json.dumps(body)
    fn = getattr(client, method)
    resp = fn(path, **kwargs)
    try:
        return resp.status_code, resp.get_json()
    except Exception:
        return resp.status_code, None


def _create_deal(app) -> int:
    """Seed a minimal Deal owned by the test user and return its id."""
    with app.app_context():
        deal = Deal(
            created_by_user_id=USER_ID,
            property_address="123 Identity Test Ave",
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


# ---------------------------------------------------------------------------
# Analysis workflow
# ---------------------------------------------------------------------------

class TestAnalysisIdentityContract:
    """POST /api/analysis/start must work with user_id in header only."""

    def test_start_analysis_no_user_id_in_body(self, client):
        """POST /api/analysis/start must return 201 with user_id in header only.

        This is the exact regression that was introduced when the Axios
        interceptor was changed to stop sending user_id in the body.
        """
        status, body = _json(client, "post", "/api/analysis/start", {
            "address": "1048 N Spaulding Ave, Chicago, IL 60651",
            # NO user_id in body — only in X-User-Id header
        })
        assert status == 201, (
            f"POST /api/analysis/start returned {status} with user_id in header only.\n"
            f"Response: {body}\n"
            "This endpoint must read user_id from the X-User-Id header, not the body."
        )
        assert "session_id" in body, "Response missing session_id"


# ---------------------------------------------------------------------------
# Lead management
# ---------------------------------------------------------------------------

class TestLeadIdentityContract:
    """Lead endpoints must work with user_id in header only."""

    def test_analyze_lead_no_user_id_in_body(self, app, client):
        """POST /api/leads/:id/analyze must work with user_id in header only."""
        # Seed a lead
        from app.models import Lead
        with app.app_context():
            lead = Lead(
                property_street="123 Test St",
                owner_first_name="Test",
                owner_last_name="User",
                lead_score=50.0,
                lead_category="residential",
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

        status, body = _json(client, "post", f"/api/leads/{lead_id}/analyze", {
            # NO user_id in body
        })
        assert status == 201, (
            f"POST /api/leads/{lead_id}/analyze returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )

    def test_update_scoring_weights_no_user_id_in_body(self, client):
        """PUT /api/leads/scoring/weights must work with user_id in header only."""
        status, body = _json(client, "put", "/api/leads/scoring/weights", {
            "property_characteristics_weight": 0.25,
            "data_completeness_weight": 0.25,
            "owner_situation_weight": 0.25,
            "location_desirability_weight": 0.25,
            # NO user_id in body
        })
        assert status == 200, (
            f"PUT /api/leads/scoring/weights returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )


# ---------------------------------------------------------------------------
# Marketing lists
# ---------------------------------------------------------------------------

class TestMarketingIdentityContract:
    """Marketing list endpoints must work with user_id in header only."""

    def test_create_marketing_list_no_user_id_in_body(self, client):
        """POST /api/leads/marketing/lists must work with user_id in header only."""
        status, body = _json(client, "post", "/api/leads/marketing/lists", {
            "name": "Identity Contract Test List",
            # NO user_id in body
        })
        assert status == 201, (
            f"POST /api/leads/marketing/lists returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )


# ---------------------------------------------------------------------------
# Multifamily deals
# ---------------------------------------------------------------------------

class TestMultifamilyIdentityContract:
    """Multifamily deal endpoints must work with user_id in header only."""

    def test_create_deal_no_user_id_in_body(self, client):
        """POST /api/multifamily/deals must work with user_id in header only."""
        status, body = _json(client, "post", "/api/multifamily/deals", {
            "property_address": "456 Identity Test Blvd",
            "unit_count": 10,
            "purchase_price": 1000000,
            "close_date": "2025-06-01",
            # NO user_id in body
        })
        assert status == 201, (
            f"POST /api/multifamily/deals returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )

    def test_list_deals_no_user_id_in_body(self, client):
        """GET /api/multifamily/deals must work with user_id in header only."""
        status, body = _json(client, "get", "/api/multifamily/deals")
        assert status == 200, (
            f"GET /api/multifamily/deals returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )

    def test_get_deal_no_user_id_in_body(self, app, client):
        """GET /api/multifamily/deals/:id must work with user_id in header only."""
        deal_id = _create_deal(app)
        status, body = _json(client, "get", f"/api/multifamily/deals/{deal_id}")
        assert status == 200, (
            f"GET /api/multifamily/deals/{deal_id} returned {status} with user_id in header only.\n"
            f"Response: {body}"
        )
