"""
Property-based tests for lead ownership isolation.

Feature: multi-user-lead-exclusivity
"""
import json
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import Lead


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# User ID strategy: arbitrary non-empty ASCII strings that look like user IDs
_user_id_strategy = st.text(
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789-',
    min_size=4,
    max_size=36,
).filter(lambda s: s.strip() == s and len(s) >= 4)

# Lead field strategies — minimal valid lead data
_street_strategy = st.text(
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789 ',
    min_size=3,
    max_size=50,
).map(str.strip).filter(lambda s: len(s) >= 3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_lead_for_user(user_id: str, street_suffix: str = '') -> Lead:
    """Create and persist a Lead owned by *user_id*.

    Returns the committed Lead instance.
    """
    lead = Lead(
        property_street=f'100 Test{street_suffix} St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
        owner_first_name='Test',
        owner_last_name='Owner',
        property_type='single_family',
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60601',
        lead_score=50.0,
        owner_user_id=user_id,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def _delete_leads_for_users(*user_ids: str) -> None:
    """Delete all Lead rows owned by any of the given user IDs."""
    for uid in user_ids:
        Lead.query.filter_by(owner_user_id=uid).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# Property 13: Cross-user lead access returns 404
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    user_id_1=_user_id_strategy,
    user_id_2=_user_id_strategy,
)
def test_property_13_cross_user_lead_access_returns_404(app, client, user_id_1, user_id_2):
    """
    Property 13: Cross-user lead access returns 404

    For any two distinct users ``u1`` and ``u2``, and any lead ``L`` owned by
    ``u1``, a GET or POST (analyze) request for ``L`` authenticated as ``u2``
    SHALL return HTTP 404.

    This ensures that the existence of another user's lead is never revealed
    to an unauthorized caller — the response is indistinguishable from a
    genuinely non-existent lead.

    **Validates: Requirements 4.4**
    """
    # The two users must be distinct
    assume(user_id_1 != user_id_2)

    with app.app_context():
        # Clean up any leftover rows from prior Hypothesis examples
        _delete_leads_for_users(user_id_1, user_id_2)

        try:
            # Create a lead owned by user 1
            lead = _create_lead_for_user(user_id_1)
            lead_id = lead.id

            # --- GET /api/properties/<lead_id> as user 2 ---
            get_response = client.get(
                f'/api/properties/{lead_id}',
                headers={'X-User-Id': user_id_2},
            )
            assert get_response.status_code == 404, (
                f"GET /api/properties/{lead_id} as user_2={user_id_2!r} "
                f"(lead owned by user_1={user_id_1!r}) should return 404, "
                f"got {get_response.status_code}: {get_response.get_data(as_text=True)}"
            )

            # --- POST /api/properties/<lead_id>/analyze as user 2 ---
            analyze_response = client.post(
                f'/api/properties/{lead_id}/analyze',
                data=json.dumps({}),
                content_type='application/json',
                headers={'X-User-Id': user_id_2},
            )
            assert analyze_response.status_code == 404, (
                f"POST /api/properties/{lead_id}/analyze as user_2={user_id_2!r} "
                f"(lead owned by user_1={user_id_1!r}) should return 404, "
                f"got {analyze_response.status_code}: {analyze_response.get_data(as_text=True)}"
            )

            # Sanity check: user 1 CAN access their own lead (200)
            own_get_response = client.get(
                f'/api/properties/{lead_id}',
                headers={'X-User-Id': user_id_1},
            )
            assert own_get_response.status_code == 200, (
                f"GET /api/properties/{lead_id} as owner user_1={user_id_1!r} "
                f"should return 200, got {own_get_response.status_code}: "
                f"{own_get_response.get_data(as_text=True)}"
            )

        finally:
            # Always clean up so the next Hypothesis example starts with a
            # clean DB state regardless of whether assertions passed or failed.
            _delete_leads_for_users(user_id_1, user_id_2)
