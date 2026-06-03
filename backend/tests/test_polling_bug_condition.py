"""
Bug Condition Exploration Tests — Task 1 (Polling Optimization Bugfix)

**Validates: Requirements 1.7**

Sub-property E — List serializer bulk fields

Property: For any lead with non-null notes and mailer_history,
_serialize_property_summary must NOT include 'notes' or 'mailer_history' keys.

On UNFIXED code: both keys are present in the output — this test FAILS.
On FIXED code: both keys are absent — this test PASSES.

These tests are EXPECTED TO FAIL on unfixed code — failure confirms the bug exists.
DO NOT fix the code or the tests when they fail.
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.controllers.property_controller import _serialize_property_summary, _serialize_property_detail


# ---------------------------------------------------------------------------
# Minimal Lead stub — avoids DB dependency
# ---------------------------------------------------------------------------

class _EmptyRelationship:
    """Mimics a SQLAlchemy lazy relationship that returns an empty list on .all()."""
    def all(self):
        return []


class LeadStub:
    """Minimal stub that mimics the Lead ORM model for serializer testing."""

    def __init__(self, **kwargs):
        # Required fields with defaults
        self.id = kwargs.get('id', 1)
        self.lead_category = kwargs.get('lead_category', 'warm')
        self.property_street = kwargs.get('property_street', '123 Main St')
        self.property_city = kwargs.get('property_city', 'Chicago')
        self.property_state = kwargs.get('property_state', 'IL')
        self.property_zip = kwargs.get('property_zip', '60601')
        self.property_type = kwargs.get('property_type', 'single_family')
        self.bedrooms = kwargs.get('bedrooms', 3)
        self.bathrooms = kwargs.get('bathrooms', 2.0)
        self.square_footage = kwargs.get('square_footage', 1500)
        self.lot_size = kwargs.get('lot_size', 5000)
        self.year_built = kwargs.get('year_built', 1990)
        self.units = kwargs.get('units', 1)
        self.units_allowed = kwargs.get('units_allowed', None)
        self.zoning = kwargs.get('zoning', 'R-1')
        self.county_assessor_pin = kwargs.get('county_assessor_pin', None)
        self.tax_bill_2021 = kwargs.get('tax_bill_2021', None)
        self.most_recent_sale = kwargs.get('most_recent_sale', None)
        self.owner_first_name = kwargs.get('owner_first_name', 'John')
        self.owner_last_name = kwargs.get('owner_last_name', 'Doe')
        self.owner_2_first_name = kwargs.get('owner_2_first_name', None)
        self.owner_2_last_name = kwargs.get('owner_2_last_name', None)
        self.ownership_type = kwargs.get('ownership_type', None)
        self.acquisition_date = kwargs.get('acquisition_date', None)
        self.phone_1 = kwargs.get('phone_1', None)
        self.phone_2 = kwargs.get('phone_2', None)
        self.phone_3 = kwargs.get('phone_3', None)
        self.phone_4 = kwargs.get('phone_4', None)
        self.phone_5 = kwargs.get('phone_5', None)
        self.phone_6 = kwargs.get('phone_6', None)
        self.phone_7 = kwargs.get('phone_7', None)
        self.email_1 = kwargs.get('email_1', None)
        self.email_2 = kwargs.get('email_2', None)
        self.email_3 = kwargs.get('email_3', None)
        self.email_4 = kwargs.get('email_4', None)
        self.email_5 = kwargs.get('email_5', None)
        self.socials = kwargs.get('socials', None)
        self.mailing_address = kwargs.get('mailing_address', None)
        self.mailing_city = kwargs.get('mailing_city', None)
        self.mailing_state = kwargs.get('mailing_state', None)
        self.mailing_zip = kwargs.get('mailing_zip', None)
        self.address_2 = kwargs.get('address_2', None)
        self.returned_addresses = kwargs.get('returned_addresses', None)
        self.source = kwargs.get('source', 'manual')
        self.date_identified = kwargs.get('date_identified', None)
        self.notes = kwargs.get('notes', None)
        self.needs_skip_trace = kwargs.get('needs_skip_trace', False)
        self.skip_tracer = kwargs.get('skip_tracer', None)
        self.date_skip_traced = kwargs.get('date_skip_traced', None)
        self.date_added_to_hubspot = kwargs.get('date_added_to_hubspot', None)
        self.up_next_to_mail = kwargs.get('up_next_to_mail', False)
        self.mailer_history = kwargs.get('mailer_history', None)
        self.lead_score = kwargs.get('lead_score', 50.0)
        self.data_source = kwargs.get('data_source', 'manual')
        self.last_import_job_id = kwargs.get('last_import_job_id', None)
        self.created_at = kwargs.get('created_at', None)
        self.updated_at = kwargs.get('updated_at', None)
        self.analysis_session_id = kwargs.get('analysis_session_id', None)
        self.analysis_session = kwargs.get('analysis_session', None)
        self.suppression_flag = kwargs.get('suppression_flag', False)
        # DuPage lead database additions
        self.source_type = kwargs.get('source_type', None)
        self.tax_distress_data = kwargs.get('tax_distress_data', None)
        self.manual_priority = kwargs.get('manual_priority', None)
        self.owner_user_id = kwargs.get('owner_user_id', None)
        # Lazy-loaded relationships — return empty queryable-like objects
        self.enrichment_records = _EmptyRelationship()
        self.marketing_list_members = _EmptyRelationship()


# ---------------------------------------------------------------------------
# Hypothesis strategies for lead data
# ---------------------------------------------------------------------------

# Non-empty text for notes and mailer_history
st_notes = st.text(min_size=1, max_size=500)
st_mailer_history = st.one_of(
    st.just({'sent': 1, 'last_sent': '2024-01-01'}),
    st.just({'sent': 5, 'last_sent': '2024-06-15', 'responses': 2}),
    st.just({'sent': 0}),
    st.fixed_dictionaries({
        'sent': st.integers(min_value=0, max_value=100),
    }),
)


# ---------------------------------------------------------------------------
# Sub-property E — List serializer bulk fields
# ---------------------------------------------------------------------------

class TestListSerializerBulkFields:
    """
    Sub-property E: _serialize_property_summary must NOT include 'notes'
    or 'mailer_history' in its output for any lead.

    On UNFIXED code: both keys are present — tests FAIL (confirms bug exists).
    On FIXED code: both keys are absent — tests PASS (confirms fix works).
    """

    def test_notes_absent_from_summary_with_non_null_notes(self):
        """
        Concrete failing case: a lead with non-null notes.
        On unfixed code: 'notes' key IS present in the result — FAILS.
        On fixed code: 'notes' key is absent — PASSES.
        """
        lead = LeadStub(notes='This is an important note about the property owner.')
        result = _serialize_property_summary(lead)

        # On UNFIXED code: this assertion FAILS because 'notes' is in the result
        assert 'notes' not in result, (
            f"Bug confirmed: 'notes' key present in _serialize_property_summary output. "
            f"Value: {result.get('notes')!r}"
        )

    def test_mailer_history_absent_from_summary_with_non_null_mailer_history(self):
        """
        Concrete failing case: a lead with non-null mailer_history.
        On unfixed code: 'mailer_history' key IS present in the result — FAILS.
        On fixed code: 'mailer_history' key is absent — PASSES.
        """
        lead = LeadStub(mailer_history={'sent': 3, 'last_sent': '2024-03-15'})
        result = _serialize_property_summary(lead)

        # On UNFIXED code: this assertion FAILS because 'mailer_history' is in the result
        assert 'mailer_history' not in result, (
            f"Bug confirmed: 'mailer_history' key present in _serialize_property_summary output. "
            f"Value: {result.get('mailer_history')!r}"
        )

    def test_both_bulk_fields_absent_from_summary(self):
        """
        Both notes and mailer_history must be absent from the summary serializer.
        On unfixed code: FAILS because both keys are present.
        """
        lead = LeadStub(
            notes='Long note text that wastes bandwidth in list responses.',
            mailer_history={'sent': 5, 'last_sent': '2024-06-01', 'responses': 1},
        )
        result = _serialize_property_summary(lead)

        # On UNFIXED code: both assertions FAIL
        assert 'notes' not in result, (
            f"Bug confirmed: 'notes' present in summary. Value: {result.get('notes')!r}"
        )
        assert 'mailer_history' not in result, (
            f"Bug confirmed: 'mailer_history' present in summary. "
            f"Value: {result.get('mailer_history')!r}"
        )

    @given(
        notes=st_notes,
        mailer_history=st_mailer_history,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_property_notes_never_in_summary_for_any_lead(self, notes, mailer_history):
        """
        Property: For ANY lead with non-null notes and mailer_history,
        _serialize_property_summary must NOT include 'notes' in its output.

        On UNFIXED code: FAILS immediately on the first example because
        'notes' is always present in the unfixed serializer.
        """
        lead = LeadStub(notes=notes, mailer_history=mailer_history)
        result = _serialize_property_summary(lead)

        assert 'notes' not in result, (
            f"Counterexample found: notes={notes!r}, mailer_history={mailer_history!r}. "
            f"'notes' key present in summary output with value: {result.get('notes')!r}"
        )

    @given(
        notes=st_notes,
        mailer_history=st_mailer_history,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_property_mailer_history_never_in_summary_for_any_lead(self, notes, mailer_history):
        """
        Property: For ANY lead with non-null notes and mailer_history,
        _serialize_property_summary must NOT include 'mailer_history' in its output.

        On UNFIXED code: FAILS immediately on the first example because
        'mailer_history' is always present in the unfixed serializer.
        """
        lead = LeadStub(notes=notes, mailer_history=mailer_history)
        result = _serialize_property_summary(lead)

        assert 'mailer_history' not in result, (
            f"Counterexample found: notes={notes!r}, mailer_history={mailer_history!r}. "
            f"'mailer_history' key present in summary output with value: "
            f"{result.get('mailer_history')!r}"
        )

    def test_detail_serializer_still_includes_notes(self):
        """
        Preservation check: _serialize_property_detail must STILL include 'notes'.
        This test should PASS on both unfixed and fixed code.
        (Ensures we don't accidentally break the detail serializer.)
        """
        lead = LeadStub(notes='Detail note that should remain accessible.')
        result = _serialize_property_detail(lead)

        # This should pass on both unfixed and fixed code
        assert 'notes' in result, (
            "'notes' must remain in _serialize_property_detail output"
        )
        assert result['notes'] == 'Detail note that should remain accessible.'

    def test_detail_serializer_still_includes_mailer_history(self):
        """
        Preservation check: _serialize_property_detail must STILL include 'mailer_history'.
        This test should PASS on both unfixed and fixed code.
        """
        lead = LeadStub(mailer_history={'sent': 2, 'last_sent': '2024-05-01'})
        result = _serialize_property_detail(lead)

        # This should pass on both unfixed and fixed code
        assert 'mailer_history' in result, (
            "'mailer_history' must remain in _serialize_property_detail output"
        )
        assert result['mailer_history'] == {'sent': 2, 'last_sent': '2024-05-01'}
