"""
API contract tests — verify that every lead-list endpoint returns a response
that matches the shape the frontend Zod schema expects.

These tests catch backend/frontend type mismatches (e.g. mailer_history stored
as a string when the schema expects an object) before they reach the browser.

Each test:
  1. Seeds a Lead with realistic field values including edge-case types.
  2. Calls the endpoint via the test client.
  3. Asserts the response is 200 and every field has the expected Python type.

If a new field is added to the Lead model or the serializer, add it here.
"""
import json
import pytest
from app import db
from app.models.lead import Lead
from app.models.hubspot_signal import HubSpotSignal
from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
from app.models.task import Task
from app.models.task_association import TaskAssociation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_lead(**kwargs) -> Lead:
    """Create and persist a Lead with the given keyword arguments."""
    lead = Lead(**kwargs)
    db.session.add(lead)
    db.session.commit()
    return lead


def _assert_lead_shape(lead_dict: dict, is_list_response: bool = False) -> None:
    """Assert that a single lead dict matches the expected API contract.

    This mirrors the LeadSummarySchema in frontend/src/services/schemas.ts.
    Any type mismatch here means the frontend Zod schema would also fail.

    Parameters
    ----------
    lead_dict : dict
        The lead dict from the API response.
    is_list_response : bool
        When True, asserts that 'notes' and 'mailer_history' are absent
        (they were removed from _serialize_property_summary in task 3.7).
    """
    # Required fields
    assert isinstance(lead_dict['id'], int), f"id must be int, got {type(lead_dict['id'])}"
    assert isinstance(lead_dict['lead_score'], (int, float)), \
        f"lead_score must be numeric, got {type(lead_dict['lead_score'])}"
    assert isinstance(lead_dict['lead_category'], str), \
        f"lead_category must be str, got {type(lead_dict['lead_category'])}"

    # Nullable string fields present in list responses (notes and mailer_history excluded)
    nullable_str_fields = [
        'property_street', 'property_city', 'property_state', 'property_zip',
        'property_type', 'county_assessor_pin', 'most_recent_sale',
        'owner_first_name', 'owner_last_name', 'owner_2_first_name', 'owner_2_last_name',
        'ownership_type', 'acquisition_date',
        'phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7',
        'email_1', 'email_2', 'email_3', 'email_4', 'email_5',
        'socials', 'mailing_address', 'mailing_city', 'mailing_state', 'mailing_zip',
        'address_2', 'returned_addresses', 'source', 'date_identified',
        'skip_tracer', 'date_skip_traced', 'date_added_to_hubspot',
        'data_source', 'created_at', 'updated_at', 'zoning',
    ]
    for field in nullable_str_fields:
        val = lead_dict.get(field)
        assert val is None or isinstance(val, str), \
            f"{field} must be str or None, got {type(val)}: {val!r}"

    # Nullable numeric fields
    nullable_num_fields = [
        'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
        'units', 'units_allowed', 'tax_bill_2021',
    ]
    for field in nullable_num_fields:
        val = lead_dict.get(field)
        assert val is None or isinstance(val, (int, float)), \
            f"{field} must be numeric or None, got {type(val)}: {val!r}"

    # Nullable boolean fields
    nullable_bool_fields = ['needs_skip_trace', 'up_next_to_mail']
    for field in nullable_bool_fields:
        val = lead_dict.get(field)
        assert val is None or isinstance(val, bool), \
            f"{field} must be bool or None, got {type(val)}: {val!r}"

    if is_list_response:
        # notes and mailer_history were removed from _serialize_property_summary (task 3.7).
        # Assert they are absent so any regression (re-adding them) is caught immediately.
        assert 'notes' not in lead_dict, \
            f"'notes' must be absent from list responses but was present: {lead_dict.get('notes')!r}"
        assert 'mailer_history' not in lead_dict, \
            f"'mailer_history' must be absent from list responses but was present: {lead_dict.get('mailer_history')!r}"
    else:
        # Detail responses may include mailer_history — validate its type if present.
        if 'mailer_history' in lead_dict:
            mh = lead_dict['mailer_history']
            assert mh is None or isinstance(mh, (dict, list, str)), \
                f"mailer_history must be None/dict/list/str, got {type(mh)}: {mh!r}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def lead_with_string_mailer_history(app):
    """Lead with mailer_history stored as a plain string (legacy import data)."""
    with app.app_context():
        lead = _seed_lead(
            property_street='123 Contract Test St',
            lead_score=50.0,
            lead_category='residential',
            mailer_history='Personal, Blue Mosaic, 12/11/2022',
            owner_user_id='test-user',
        )
        yield lead.id


@pytest.fixture
def lead_with_dict_mailer_history(app):
    """Lead with mailer_history stored as a proper JSON object."""
    with app.app_context():
        lead = _seed_lead(
            property_street='456 Contract Test Ave',
            lead_score=60.0,
            lead_category='residential',
            mailer_history={'campaign': 'Spring 2024', 'sent': True},
            owner_user_id='test-user',
        )
        yield lead.id


@pytest.fixture
def lead_with_null_mailer_history(app):
    """Lead with mailer_history = NULL."""
    with app.app_context():
        lead = _seed_lead(
            property_street='789 Contract Test Blvd',
            lead_score=40.0,
            lead_category='residential',
            mailer_history=None,
            owner_user_id='test-user',
        )
        yield lead.id


@pytest.fixture
def warm_lead(app):
    """Lead with a PRIOR_WARM_CONVERSATION signal for the previously-warm view."""
    with app.app_context():
        # Seed signal dictionary entry
        existing = HubSpotSignalDictionary.query.filter_by(
            signal_type='PRIOR_WARM_CONVERSATION'
        ).first()
        if not existing:
            db.session.add(HubSpotSignalDictionary(
                signal_type='PRIOR_WARM_CONVERSATION',
                keywords=['interested', 'warm lead'],
            ))
            db.session.commit()

        lead = _seed_lead(
            property_street='999 Warm Lead St',
            lead_score=75.0,
            lead_category='residential',
            mailer_history='Bes and Ben, OLM, 3/26/2024',  # legacy string format
        )
        signal = HubSpotSignal(
            lead_id=lead.id,
            signal_type='PRIOR_WARM_CONVERSATION',
            source_engagement_id='test-eng-001',
            raw_evidence='interested',
        )
        db.session.add(signal)
        db.session.commit()
        yield lead.id


@pytest.fixture
def suppressed_lead(app):
    """Lead with suppression_flag=True for the do-not-contact view."""
    with app.app_context():
        lead = _seed_lead(
            property_street='111 DNC Test St',
            lead_score=10.0,
            lead_category='residential',
            suppression_flag=True,
            mailer_history='Some mailer string',
        )
        yield lead.id


# ---------------------------------------------------------------------------
# Contract tests — GET /api/properties/views/*
# ---------------------------------------------------------------------------

class TestLeadViewApiContract:
    """Verify that all lead view endpoints return correctly-shaped responses."""

    def test_previously_warm_view_shape(self, client, warm_lead):
        """GET /api/properties/views/previously-warm returns valid lead shapes."""
        response = client.get('/api/properties/views/previously-warm')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'leads' in data
        assert isinstance(data['leads'], list)
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_previously_warm_view_includes_warm_lead(self, client, warm_lead):
        """The previously-warm view includes leads with warm signals."""
        response = client.get('/api/properties/views/previously-warm')
        data = json.loads(response.data)
        lead_ids = [l['id'] for l in data['leads']]
        assert warm_lead in lead_ids, \
            f"Expected warm_lead id={warm_lead} in results, got {lead_ids}"

    def test_do_not_contact_view_shape(self, client, suppressed_lead):
        """GET /api/properties/views/do-not-contact returns valid lead shapes."""
        response = client.get('/api/properties/views/do-not-contact')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'leads' in data
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_follow_up_overdue_view_shape(self, client, app):
        """GET /api/properties/views/follow-up-overdue returns valid lead shapes."""
        with app.app_context():
            from datetime import datetime, timedelta
            lead = _seed_lead(
                property_street='222 Overdue St',
                lead_score=55.0,
                lead_category='residential',
                mailer_history='Test mailer',
            )
            task = Task(
                title='Follow up',
                status='overdue',
                source='manual',
                due_date=datetime.utcnow() - timedelta(days=3),
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(TaskAssociation(
                task_id=task.id,
                target_type='lead',
                target_id=lead.id,
            ))
            db.session.commit()

        response = client.get('/api/properties/views/follow-up-overdue')
        assert response.status_code == 200
        data = json.loads(response.data)
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_needs_review_view_shape(self, client, app):
        """GET /api/properties/views/needs-review returns valid lead shapes."""
        response = client.get('/api/properties/views/needs-review')
        assert response.status_code == 200
        data = json.loads(response.data)
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_no_next_action_view_shape(self, client, app):
        """GET /api/properties/views/no-next-action returns valid lead shapes."""
        response = client.get('/api/properties/views/no-next-action')
        assert response.status_code == 200
        data = json.loads(response.data)
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_missing_property_match_view_shape(self, client, app):
        """GET /api/properties/views/missing-property-match returns valid lead shapes."""
        response = client.get('/api/properties/views/missing-property-match')
        assert response.status_code == 200
        data = json.loads(response.data)
        for lead in data['leads']:
            _assert_lead_shape(lead, is_list_response=True)

    def test_mailer_history_string_does_not_break_view(
        self, client, lead_with_string_mailer_history
    ):
        """A lead with mailer_history as a plain string must not cause a parse error.

        Post-fix: mailer_history is no longer included in _serialize_property_summary
        (task 3.7 of the polling-optimization bugfix). The field is absent from the
        list response entirely, so legacy string values can never break the frontend
        Zod schema. This test verifies the endpoint returns 200 and the lead shape
        is valid (mailer_history absent is acceptable).
        """
        response = client.get('/api/properties/', headers={'X-User-Id': 'test-user'})
        assert response.status_code == 200
        data = json.loads(response.data)
        matching = [l for l in data['leads'] if l['id'] == lead_with_string_mailer_history]
        assert len(matching) == 1
        lead = matching[0]
        _assert_lead_shape(lead, is_list_response=True)
        # Explicit belt-and-suspenders check (also enforced by is_list_response=True above)
        assert 'mailer_history' not in lead

    def test_mailer_history_dict_passes_shape_check(
        self, client, lead_with_dict_mailer_history
    ):
        """A lead with mailer_history as a dict must pass the shape check."""
        response = client.get('/api/properties/', headers={'X-User-Id': 'test-user'})
        assert response.status_code == 200
        data = json.loads(response.data)
        matching = [l for l in data['leads'] if l['id'] == lead_with_dict_mailer_history]
        assert len(matching) == 1
        _assert_lead_shape(matching[0], is_list_response=True)

    def test_mailer_history_null_passes_shape_check(
        self, client, lead_with_null_mailer_history
    ):
        """A lead with mailer_history=NULL must pass the shape check."""
        response = client.get('/api/properties/', headers={'X-User-Id': 'test-user'})
        assert response.status_code == 200
        data = json.loads(response.data)
        matching = [l for l in data['leads'] if l['id'] == lead_with_null_mailer_history]
        assert len(matching) == 1
        _assert_lead_shape(matching[0], is_list_response=True)
