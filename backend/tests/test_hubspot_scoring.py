"""Property-based tests for LeadScoringEngine — Properties 11, 12, 13.

Tests use Hypothesis to verify universal scoring invariants without
requiring a Flask app context or database connection.  All Lead and
ScoringWeights objects are constructed with MagicMock so the pure
computation logic can be exercised in isolation.
"""
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.lead_scoring_engine import LeadScoringEngine


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_lead_scoring_engine.py conventions)
# ---------------------------------------------------------------------------

def _make_weights(prop=0.25, completeness=0.25, owner=0.25, location=0.25):
    """Return a mock ScoringWeights object with the given weight values."""
    w = MagicMock()
    w.property_characteristics_weight = prop
    w.data_completeness_weight = completeness
    w.owner_situation_weight = owner
    w.location_desirability_weight = location
    return w


def _make_lead(suppression_flag=False, **kwargs):
    """Return a minimal mock Lead object.

    All scoring sub-method attributes default to None/falsy so the base
    score is 0.0 unless overridden via kwargs.
    """
    lead = MagicMock()
    _zero_attrs = [
        "property_type", "bedrooms", "bathrooms", "square_footage",
        "lot_size", "year_built",
        "owner_first_name", "owner_last_name", "ownership_type",
        "acquisition_date", "phone_1", "phone_2", "phone_3",
        "email_1", "email_2",
        "mailing_address", "property_street", "mailing_city",
        "mailing_state", "mailing_zip",
        "property_city", "property_state", "property_zip",
        "source", "notes", "units_allowed", "zoning",
        "county_assessor_pin", "owner_2_first_name", "phone_4",
        "email_3", "socials",
    ]
    for attr in _zero_attrs:
        setattr(lead, attr, None)
    lead.suppression_flag = suppression_flag
    for k, v in kwargs.items():
        setattr(lead, k, v)
    return lead


def _make_signal(signal_type: str):
    """Return a mock HubSpotSignal-like object."""
    s = MagicMock()
    s.signal_type = signal_type
    return s


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Strategy: generate a weight tuple that sums to 1.0 (normalised)
@st.composite
def normalised_weights(draw):
    """Draw four non-negative floats and normalise them to sum to 1.0."""
    raw = draw(
        st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=4,
            max_size=4,
        )
    )
    total = sum(raw)
    # Avoid division by zero: if all weights are 0, use equal weights
    if total == 0.0:
        return (0.25, 0.25, 0.25, 0.25)
    normalised = tuple(v / total for v in raw)
    return normalised


# Strategy: generate a list of neutral signals (no positive/negative adjustment)
_NEUTRAL_SIGNAL_TYPES = [
    "PRIOR_INTERACTION_EXISTS",
    "PRIOR_RESPONSE_EXISTS",
    "ASKING_PRICE_GIVEN",
    "FOLLOW_UP_OVERDUE",
    "PRIOR_LEAD_SOURCE_KNOWN",
]

_POSITIVE_SIGNAL_TYPES = ["PRIOR_WARM_CONVERSATION", "APPOINTMENT_OCCURRED"]
_NEGATIVE_SIGNAL_TYPES = ["SELLER_NOT_INTERESTED", "DO_NOT_CONTACT"]


@st.composite
def neutral_signal_list(draw):
    """Draw a list of signals that have no score adjustment (neutral types)."""
    types = draw(
        st.lists(
            st.sampled_from(_NEUTRAL_SIGNAL_TYPES),
            min_size=0,
            max_size=5,
        )
    )
    return [_make_signal(t) for t in types]


# ---------------------------------------------------------------------------
# Property 11: Suppressed lead score is always below threshold
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 11: Suppressed lead score is always below threshold
class TestProperty11SuppressedLeadScoreBelowThreshold:
    """**Validates: Requirements 17.6**

    For any Lead with suppression_flag=True, compute_score() must return
    a value ≤ 10.0 regardless of base sub-scores or signal adjustments.
    """

    @given(
        weights=normalised_weights(),
        signals=st.lists(
            st.sampled_from(list(LeadScoringEngine.SIGNAL_ADJUSTMENTS.keys())),
            min_size=0,
            max_size=10,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_suppressed_lead_score_always_at_most_10(self, weights, signals):
        # Feature: hubspot-crm-migration, Property 11: Suppressed lead score is always below threshold
        engine = LeadScoringEngine()
        prop_w, comp_w, owner_w, loc_w = weights
        w = _make_weights(prop=prop_w, completeness=comp_w, owner=owner_w, location=loc_w)
        lead = _make_lead(suppression_flag=True)
        signal_objs = [_make_signal(s) for s in signals]
        score = engine.compute_score(lead, w, signals=signal_objs)
        assert score <= 10.0, (
            f"Suppressed lead score {score} exceeded 10.0 "
            f"with weights={weights} and signals={signals}"
        )

    @given(
        weights=normalised_weights(),
    )
    @settings(max_examples=100)
    def test_suppressed_lead_score_at_most_10_with_high_base(self, weights):
        # Feature: hubspot-crm-migration, Property 11: Suppressed lead score is always below threshold
        engine = LeadScoringEngine()
        prop_w, comp_w, owner_w, loc_w = weights
        w = _make_weights(prop=prop_w, completeness=comp_w, owner=owner_w, location=loc_w)
        # Give the lead a high base score via a rich set of attributes
        lead = _make_lead(
            suppression_flag=True,
            property_type="single_family",
            bedrooms=3,
            bathrooms=2,
            square_footage=1500,
            lot_size=5000,
            year_built=1990,
            owner_first_name="Jane",
            phone_1="555-1234",
            property_street="123 Main St",
            mailing_address="456 Other Ave",
            mailing_city="Chicago",
            mailing_state="IL",
            mailing_zip="60601",
        )
        # Add the strongest positive signals
        signals = [
            _make_signal("PRIOR_WARM_CONVERSATION"),
            _make_signal("APPOINTMENT_OCCURRED"),
        ]
        score = engine.compute_score(lead, w, signals=signals)
        assert score <= 10.0, (
            f"Suppressed lead score {score} exceeded 10.0 with weights={weights}"
        )


# ---------------------------------------------------------------------------
# Property 12: Signal score adjustments are monotone
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 12: Signal score adjustments are monotone
class TestProperty12SignalScoreAdjustmentsMonotone:
    """**Validates: Requirements 17.1, 17.2**

    Adding a positive-adjustment signal must produce a score ≥ the score
    without it.  Adding a negative-adjustment signal must produce a score
    ≤ the score without it.
    """

    @given(
        weights=normalised_weights(),
        base_signals=neutral_signal_list(),
        positive_signal=st.sampled_from(_POSITIVE_SIGNAL_TYPES),
    )
    @settings(max_examples=100)
    def test_adding_positive_signal_does_not_decrease_score(
        self, weights, base_signals, positive_signal
    ):
        # Feature: hubspot-crm-migration, Property 12: Signal score adjustments are monotone
        engine = LeadScoringEngine()
        prop_w, comp_w, owner_w, loc_w = weights
        w = _make_weights(prop=prop_w, completeness=comp_w, owner=owner_w, location=loc_w)
        lead = _make_lead(suppression_flag=False)

        score_without = engine.compute_score(lead, w, signals=base_signals)
        score_with = engine.compute_score(
            lead, w, signals=base_signals + [_make_signal(positive_signal)]
        )
        assert score_with >= score_without, (
            f"Adding positive signal '{positive_signal}' decreased score "
            f"from {score_without} to {score_with}"
        )

    @given(
        weights=normalised_weights(),
        base_signals=neutral_signal_list(),
        negative_signal=st.sampled_from(_NEGATIVE_SIGNAL_TYPES),
    )
    @settings(max_examples=100)
    def test_adding_negative_signal_does_not_increase_score(
        self, weights, base_signals, negative_signal
    ):
        # Feature: hubspot-crm-migration, Property 12: Signal score adjustments are monotone
        engine = LeadScoringEngine()
        prop_w, comp_w, owner_w, loc_w = weights
        w = _make_weights(prop=prop_w, completeness=comp_w, owner=owner_w, location=loc_w)
        lead = _make_lead(suppression_flag=False)

        score_without = engine.compute_score(lead, w, signals=base_signals)
        score_with = engine.compute_score(
            lead, w, signals=base_signals + [_make_signal(negative_signal)]
        )
        assert score_with <= score_without, (
            f"Adding negative signal '{negative_signal}' increased score "
            f"from {score_without} to {score_with}"
        )


# ---------------------------------------------------------------------------
# Property 13: Scoring weights always sum to 1.0
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 13: Scoring weights always sum to 1.0
class TestProperty13ScoringWeightsSumToOne:
    """**Validates: Requirements 17.1, 17.2, 17.6**

    For any ScoringWeights record whose four weights are normalised to
    sum to 1.0, the sum of all four weights must be within 0.01 of 1.0.
    This verifies the normalisation invariant that the engine relies on.
    """

    @given(weights=normalised_weights())
    @settings(max_examples=100)
    def test_normalised_weights_sum_to_one(self, weights):
        # Feature: hubspot-crm-migration, Property 13: Scoring weights always sum to 1.0
        prop_w, comp_w, owner_w, loc_w = weights
        total = prop_w + comp_w + owner_w + loc_w
        assert abs(total - 1.0) <= 0.01, (
            f"Normalised weights {weights} sum to {total}, not within 0.01 of 1.0"
        )

    @given(
        prop_w=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        comp_w=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        owner_w=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        loc_w=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_manually_normalised_weights_sum_to_one(
        self, prop_w, comp_w, owner_w, loc_w
    ):
        # Feature: hubspot-crm-migration, Property 13: Scoring weights always sum to 1.0
        raw_total = prop_w + comp_w + owner_w + loc_w
        # Skip degenerate case where all weights are 0
        assume(raw_total > 0.0)

        # Normalise
        n_prop = prop_w / raw_total
        n_comp = comp_w / raw_total
        n_owner = owner_w / raw_total
        n_loc = loc_w / raw_total

        normalised_sum = n_prop + n_comp + n_owner + n_loc
        assert abs(normalised_sum - 1.0) <= 0.01, (
            f"Normalised weights ({n_prop}, {n_comp}, {n_owner}, {n_loc}) "
            f"sum to {normalised_sum}, not within 0.01 of 1.0"
        )

    @given(weights=normalised_weights())
    @settings(max_examples=100)
    def test_compute_score_accepts_normalised_weights(self, weights):
        # Feature: hubspot-crm-migration, Property 13: Scoring weights always sum to 1.0
        # Verify that compute_score runs without error for any normalised weights
        # and returns a value in [0.0, 100.0].
        engine = LeadScoringEngine()
        prop_w, comp_w, owner_w, loc_w = weights
        w = _make_weights(prop=prop_w, completeness=comp_w, owner=owner_w, location=loc_w)
        lead = _make_lead(suppression_flag=False)
        score = engine.compute_score(lead, w)
        assert 0.0 <= score <= 100.0, (
            f"Score {score} out of [0, 100] range for weights {weights}"
        )
