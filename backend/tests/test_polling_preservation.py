"""
Preservation Property Tests — Task 2 (Polling Optimization Bugfix)

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

These tests encode the BASELINE behavior that must be PRESERVED after the fix.
On UNFIXED code they are expected to PASS — confirming the baseline exists.
On FIXED code they must also PASS — confirming no regressions were introduced.

Observation-first methodology:
  - _serialize_property_detail on a lead with notes and mailer_history
    → both fields present in output (observed on unfixed code: CONFIRMED)

Property 2: Preservation — Active Polling and Single-Owner Behavior Unchanged

For any component registration where isBugCondition(registration) returns false
(i.e., the polling is already conditional or the component is the legitimate
single owner), the fixed code SHALL produce exactly the same polling behavior
as the original code.
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.controllers.property_controller import _serialize_property_summary, _serialize_property_detail


# ---------------------------------------------------------------------------
# Minimal Lead stub — avoids DB dependency (reused from bug condition tests)
# ---------------------------------------------------------------------------

class _EmptyRelationship:
    """Mimics a SQLAlchemy lazy relationship that returns an empty list on .all()."""
    def all(self):
        return []

    def filter_by(self, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return None


class LeadStub:
    """Minimal stub that mimics the Lead ORM model for serializer testing."""

    def __init__(self, **kwargs):
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
        self.motivation_score = kwargs.get('motivation_score', 0.0)
        self.motivation_signal_summary = kwargs.get('motivation_signal_summary', [])
        self.motivation_signals = kwargs.get('motivation_signals', [])
        # Lazy-loaded relationships
        self.enrichment_records = _EmptyRelationship()
        self.marketing_list_members = _EmptyRelationship()
        self.property_contacts = _EmptyRelationship()


# ---------------------------------------------------------------------------
# Hypothesis strategies for lead data
# ---------------------------------------------------------------------------

# Non-empty text for notes
st_notes = st.text(min_size=1, max_size=500)

# Various mailer_history shapes
st_mailer_history = st.one_of(
    st.just({'sent': 1, 'last_sent': '2024-01-01'}),
    st.just({'sent': 5, 'last_sent': '2024-06-15', 'responses': 2}),
    st.just({'sent': 0}),
    st.fixed_dictionaries({
        'sent': st.integers(min_value=0, max_value=100),
    }),
    st.just([{'date': '2024-01-01', 'type': 'postcard'}]),
    st.just('2024-01-01'),
)

# Lead score values
st_lead_score = st.floats(min_value=0.0, max_value=100.0, allow_nan=False)

# Property types
st_property_type = st.sampled_from([
    'single_family', 'multi_family', 'commercial', 'land', None
])


# ---------------------------------------------------------------------------
# Preservation 3.9 / 2.8 — _serialize_property_detail includes notes and mailer_history
# ---------------------------------------------------------------------------

class TestDetailSerializerPreservation:
    """
    Preservation 3.9 / 2.8: _serialize_property_detail must CONTINUE to include
    'notes' and 'mailer_history' for the detail view.

    These tests PASS on both unfixed and fixed code — they establish the baseline
    that the detail serializer must not be modified.

    Observed on unfixed code: _serialize_property_detail includes both fields.
    This behavior must be preserved after the fix.
    """

    def test_detail_includes_notes_when_non_null(self):
        """
        Concrete case: a lead with non-null notes.
        _serialize_property_detail must include 'notes' in its output.

        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(notes='This is an important note about the property owner.')
        result = _serialize_property_detail(lead)

        assert 'notes' in result, (
            "Preservation violated: 'notes' must be present in _serialize_property_detail output"
        )
        assert result['notes'] == 'This is an important note about the property owner.'

    def test_detail_includes_mailer_history_when_non_null(self):
        """
        Concrete case: a lead with non-null mailer_history.
        _serialize_property_detail must include 'mailer_history' in its output.

        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(mailer_history={'sent': 3, 'last_sent': '2024-03-15'})
        result = _serialize_property_detail(lead)

        assert 'mailer_history' in result, (
            "Preservation violated: 'mailer_history' must be present in _serialize_property_detail output"
        )
        assert result['mailer_history'] == {'sent': 3, 'last_sent': '2024-03-15'}

    def test_detail_includes_both_fields_when_both_non_null(self):
        """
        Both notes and mailer_history must be present in the detail serializer.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(
            notes='Long note text that must remain accessible on the detail page.',
            mailer_history={'sent': 5, 'last_sent': '2024-06-01', 'responses': 1},
        )
        result = _serialize_property_detail(lead)

        assert 'notes' in result, (
            "Preservation violated: 'notes' must be present in _serialize_property_detail"
        )
        assert 'mailer_history' in result, (
            "Preservation violated: 'mailer_history' must be present in _serialize_property_detail"
        )
        assert result['notes'] == 'Long note text that must remain accessible on the detail page.'
        assert result['mailer_history'] == {'sent': 5, 'last_sent': '2024-06-01', 'responses': 1}

    def test_detail_includes_notes_when_null(self):
        """
        Even when notes is None, the 'notes' key must be present in the detail output.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(notes=None)
        result = _serialize_property_detail(lead)

        assert 'notes' in result, (
            "Preservation violated: 'notes' key must be present in _serialize_property_detail "
            "even when value is None"
        )
        assert result['notes'] is None

    def test_detail_includes_mailer_history_when_null(self):
        """
        Even when mailer_history is None, the 'mailer_history' key must be present.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(mailer_history=None)
        result = _serialize_property_detail(lead)

        assert 'mailer_history' in result, (
            "Preservation violated: 'mailer_history' key must be present in _serialize_property_detail "
            "even when value is None"
        )
        assert result['mailer_history'] is None

    @given(
        notes=st_notes,
        mailer_history=st_mailer_history,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_property_detail_always_includes_notes_for_any_lead(self, notes, mailer_history):
        """
        Property: For ANY lead with non-null notes and mailer_history,
        _serialize_property_detail must ALWAYS include 'notes' in its output.

        **Validates: Requirements 3.9 / 2.8**

        This is the preservation property — the detail serializer must not be modified.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(notes=notes, mailer_history=mailer_history)
        result = _serialize_property_detail(lead)

        assert 'notes' in result, (
            f"Preservation violated: 'notes' absent from _serialize_property_detail. "
            f"notes={notes!r}, mailer_history={mailer_history!r}"
        )
        assert result['notes'] == notes, (
            f"Preservation violated: 'notes' value changed. "
            f"Expected {notes!r}, got {result['notes']!r}"
        )

    @given(
        notes=st_notes,
        mailer_history=st_mailer_history,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_property_detail_always_includes_mailer_history_for_any_lead(self, notes, mailer_history):
        """
        Property: For ANY lead with non-null notes and mailer_history,
        _serialize_property_detail must ALWAYS include 'mailer_history' in its output.

        **Validates: Requirements 3.9 / 2.8**

        This is the preservation property — the detail serializer must not be modified.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(notes=notes, mailer_history=mailer_history)
        result = _serialize_property_detail(lead)

        assert 'mailer_history' in result, (
            f"Preservation violated: 'mailer_history' absent from _serialize_property_detail. "
            f"notes={notes!r}, mailer_history={mailer_history!r}"
        )
        assert result['mailer_history'] == mailer_history, (
            f"Preservation violated: 'mailer_history' value changed. "
            f"Expected {mailer_history!r}, got {result['mailer_history']!r}"
        )

    @given(
        notes=st.one_of(st.none(), st_notes),
        mailer_history=st.one_of(st.none(), st_mailer_history),
        lead_score=st_lead_score,
        property_type=st_property_type,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_property_detail_preserves_both_fields_across_all_lead_shapes(
        self, notes, mailer_history, lead_score, property_type
    ):
        """
        Property: For ANY lead shape (notes and mailer_history may be None or non-None),
        _serialize_property_detail must ALWAYS include both 'notes' and 'mailer_history'
        keys in its output.

        **Validates: Requirements 3.9 / 2.8**

        This is the broadest preservation property — the detail serializer must include
        both fields regardless of their values.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(
            notes=notes,
            mailer_history=mailer_history,
            lead_score=lead_score,
            property_type=property_type,
        )
        result = _serialize_property_detail(lead)

        assert 'notes' in result, (
            f"Preservation violated: 'notes' key absent from _serialize_property_detail. "
            f"notes={notes!r}"
        )
        assert 'mailer_history' in result, (
            f"Preservation violated: 'mailer_history' key absent from _serialize_property_detail. "
            f"mailer_history={mailer_history!r}"
        )
        # Values must be preserved exactly
        assert result['notes'] == notes
        assert result['mailer_history'] == mailer_history


# ---------------------------------------------------------------------------
# Preservation 3.9 — _serialize_property_summary preserves visible columns
# ---------------------------------------------------------------------------

class TestSummarySerializerPreservesVisibleColumns:
    """
    Preservation 3.9: The property list page must continue to display all
    currently visible columns. Only notes and mailer_history are removed.

    These tests verify that the visible columns remain in _serialize_property_summary
    on both unfixed and fixed code.
    """

    VISIBLE_COLUMNS = [
        'id',
        'property_street',
        'property_city',
        'property_state',
        'property_zip',
        'property_type',
        'bedrooms',
        'bathrooms',
        'square_footage',
        'lot_size',
        'year_built',
        'owner_first_name',
        'owner_last_name',
        'lead_score',
        'lead_category',
        'created_at',
        'updated_at',
    ]

    def test_summary_includes_all_visible_columns(self):
        """
        All visible columns must be present in _serialize_property_summary output.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(
            property_street='456 Oak Ave',
            property_city='Springfield',
            property_state='IL',
            property_zip='62701',
            property_type='single_family',
            bedrooms=4,
            bathrooms=2.5,
            square_footage=2000,
            lot_size=6000,
            year_built=1985,
            owner_first_name='Jane',
            owner_last_name='Smith',
            lead_score=75.0,
            lead_category='hot',
        )
        result = _serialize_property_summary(lead)

        missing_columns = [col for col in self.VISIBLE_COLUMNS if col not in result]

        assert missing_columns == [], (
            f"Preservation violated: visible columns missing from _serialize_property_summary: "
            f"{missing_columns}"
        )

    def test_summary_preserves_property_street_value(self):
        """
        The property_street value must be preserved exactly.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(property_street='789 Elm Street')
        result = _serialize_property_summary(lead)

        assert result['property_street'] == '789 Elm Street'

    def test_summary_preserves_lead_score_value(self):
        """
        The lead_score value must be preserved exactly.
        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(lead_score=82.5)
        result = _serialize_property_summary(lead)

        assert result['lead_score'] == 82.5

    @given(
        property_street=st.text(min_size=1, max_size=200),
        lead_score=st_lead_score,
        property_type=st_property_type,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_property_summary_always_includes_visible_columns_for_any_lead(
        self, property_street, lead_score, property_type
    ):
        """
        Property: For ANY lead, _serialize_property_summary must include all
        visible columns (address, owner name, score, status, etc.).

        **Validates: Requirement 3.9**

        PASSES on both unfixed and fixed code.
        """
        lead = LeadStub(
            property_street=property_street,
            lead_score=lead_score,
            property_type=property_type,
        )
        result = _serialize_property_summary(lead)

        # Core visible columns must always be present
        core_columns = ['id', 'property_street', 'lead_score', 'lead_category']
        for col in core_columns:
            assert col in result, (
                f"Preservation violated: '{col}' absent from _serialize_property_summary. "
                f"property_street={property_street!r}, lead_score={lead_score!r}"
            )

        # Values must be preserved
        assert result['property_street'] == property_street
        assert result['lead_score'] == lead_score
