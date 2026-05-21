"""Tests for LeadScoringEngine.compute_score signal adjustments (task 19.1).

Covers:
- SIGNAL_ADJUSTMENTS class constant exists with correct values
- compute_score with no signals behaves identically to the original
- compute_score applies positive signal adjustments
- compute_score applies negative signal adjustments
- compute_score accepts HubSpotSignal-like objects (with .signal_type)
- compute_score accepts plain signal-type strings
- compute_score handles mixed lists (objects + strings)
- Unknown signal types are silently ignored
- suppression_flag=True clamps score to max 10.0 after signal adjustments
- Final score is always clamped to [0.0, 100.0]
- Final score is rounded to 2 decimal places
"""
import pytest
from unittest.mock import MagicMock
from app.services.lead_scoring_engine import LeadScoringEngine
from app import create_app, db
import os


# ---------------------------------------------------------------------------
# App context fixture — required because sub-scorers query the DB
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def app_ctx():
    """Push a minimal Flask app context so DB queries don't raise RuntimeError."""
    previous_db = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()
    if previous_db is not None:
        os.environ['DATABASE_URL'] = previous_db
    elif 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_weights(
    prop=0.25,
    completeness=0.25,
    owner=0.25,
    location=0.25,
):
    """Return a mock ScoringWeights object."""
    w = MagicMock()
    w.property_characteristics_weight = prop
    w.data_completeness_weight = completeness
    w.owner_situation_weight = owner
    w.location_desirability_weight = location
    return w


def _make_lead(suppression_flag=False, **kwargs):
    """Return a minimal mock Lead object.

    All scoring sub-methods return 0 unless the relevant attributes are set.
    Uses a MagicMock configured so that any attribute not explicitly set
    returns None (falsy), ensuring a zero base score by default.
    """
    lead = MagicMock()
    # Explicitly set every attribute used by sub-scorers to None/falsy
    # so the base score is 0.0 when no kwargs are provided.
    _zero_attrs = [
        # property characteristics
        "property_type", "bedrooms", "bathrooms", "square_footage",
        "lot_size", "year_built",
        # owner situation
        "owner_first_name", "owner_last_name", "ownership_type",
        "acquisition_date", "phone_1", "phone_2", "phone_3",
        "email_1", "email_2",
        # location
        "mailing_address", "property_street", "mailing_city",
        "mailing_state", "mailing_zip",
        # completeness fields not covered above
        "property_city", "property_state", "property_zip",
        "source", "notes", "units_allowed", "zoning",
        "county_assessor_pin", "owner_2_first_name", "phone_4",
        "email_3", "socials",
    ]
    for attr in _zero_attrs:
        setattr(lead, attr, None)
    lead.suppression_flag = suppression_flag
    # Apply any overrides
    for k, v in kwargs.items():
        setattr(lead, k, v)
    return lead


def _make_signal(signal_type: str):
    """Return a mock HubSpotSignal-like object."""
    s = MagicMock()
    s.signal_type = signal_type
    return s


# ---------------------------------------------------------------------------
# SIGNAL_ADJUSTMENTS constant
# ---------------------------------------------------------------------------

class TestSignalAdjustmentsConstant:
    def test_constant_exists(self):
        assert hasattr(LeadScoringEngine, "SIGNAL_ADJUSTMENTS")

    def test_constant_is_dict(self):
        assert isinstance(LeadScoringEngine.SIGNAL_ADJUSTMENTS, dict)

    def test_positive_adjustments(self):
        adj = LeadScoringEngine.SIGNAL_ADJUSTMENTS
        assert adj["PRIOR_WARM_CONVERSATION"] == 15.0
        assert adj["APPOINTMENT_OCCURRED"] == 20.0
        assert adj["OFFER_PREVIOUSLY_SENT"] == 10.0

    def test_negative_adjustments(self):
        adj = LeadScoringEngine.SIGNAL_ADJUSTMENTS
        assert adj["SELLER_SAID_MAYBE_LATER"] == -5.0
        assert adj["SELLER_NOT_INTERESTED"] == -40.0
        assert adj["DO_NOT_CONTACT"] == -50.0
        assert adj["WRONG_NUMBER"] == -30.0


# ---------------------------------------------------------------------------
# compute_score — no signals (backward compatibility)
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("app_ctx")
class TestComputeScoreNoSignals:
    def setup_method(self):
        self.engine = LeadScoringEngine()
        self.weights = _make_weights()

    def test_no_signals_returns_base_score(self):
        lead = _make_lead()
        score_no_arg = self.engine.compute_score(lead, self.weights)
        score_none = self.engine.compute_score(lead, self.weights, signals=None)
        assert score_no_arg == score_none

    def test_empty_signals_list_returns_base_score(self):
        lead = _make_lead()
        base = self.engine.compute_score(lead, self.weights)
        with_empty = self.engine.compute_score(lead, self.weights, signals=[])
        assert base == with_empty

    def test_score_is_float(self):
        lead = _make_lead()
        score = self.engine.compute_score(lead, self.weights)
        assert isinstance(score, float)

    def test_score_clamped_to_zero_minimum(self):
        lead = _make_lead()
        score = self.engine.compute_score(lead, self.weights)
        assert score >= 0.0

    def test_score_clamped_to_100_maximum(self):
        lead = _make_lead(
            property_type="single_family",
            bedrooms=3,
            bathrooms=2,
            square_footage=1500,
            lot_size=5000,
            year_built=1990,
            owner_first_name="Jane",
            owner_last_name="Doe",
            ownership_type="individual",
            phone_1="555-1234",
            property_street="123 Main St",
            mailing_address="456 Other Ave",
            mailing_city="Chicago",
            mailing_state="IL",
            mailing_zip="60601",
        )
        score = self.engine.compute_score(lead, self.weights)
        assert score <= 100.0

    def test_score_rounded_to_2_decimal_places(self):
        lead = _make_lead()
        score = self.engine.compute_score(lead, self.weights)
        assert score == round(score, 2)


# ---------------------------------------------------------------------------
# compute_score — signal adjustments via string list
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("app_ctx")
class TestComputeScoreStringSignals:
    def setup_method(self):
        self.engine = LeadScoringEngine()
        # Equal weights, all sub-scores = 0 → base = 0.0
        self.weights = _make_weights()
        self.lead = _make_lead()

    def test_prior_warm_conversation_adds_15(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["PRIOR_WARM_CONVERSATION"]
        )
        assert score == 15.0

    def test_appointment_occurred_adds_20(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["APPOINTMENT_OCCURRED"]
        )
        assert score == 20.0

    def test_offer_previously_sent_adds_10(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["OFFER_PREVIOUSLY_SENT"]
        )
        assert score == 10.0

    def test_seller_said_maybe_later_subtracts_5(self):
        # Base is 0, so -5 → clamped to 0
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["SELLER_SAID_MAYBE_LATER"]
        )
        assert score == 0.0

    def test_seller_not_interested_subtracts_40(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["SELLER_NOT_INTERESTED"]
        )
        assert score == 0.0  # clamped at 0

    def test_do_not_contact_subtracts_50(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["DO_NOT_CONTACT"]
        )
        assert score == 0.0  # clamped at 0

    def test_wrong_number_subtracts_30(self):
        score = self.engine.compute_score(
            self.lead, self.weights, signals=["WRONG_NUMBER"]
        )
        assert score == 0.0  # clamped at 0

    def test_multiple_positive_signals_accumulate(self):
        score = self.engine.compute_score(
            self.lead,
            self.weights,
            signals=["PRIOR_WARM_CONVERSATION", "APPOINTMENT_OCCURRED"],
        )
        assert score == 35.0  # 15 + 20

    def test_positive_and_negative_signals_combine(self):
        # APPOINTMENT_OCCURRED (+20) + SELLER_SAID_MAYBE_LATER (-5) = +15
        score = self.engine.compute_score(
            self.lead,
            self.weights,
            signals=["APPOINTMENT_OCCURRED", "SELLER_SAID_MAYBE_LATER"],
        )
        assert score == 15.0

    def test_unknown_signal_type_ignored(self):
        base = self.engine.compute_score(self.lead, self.weights)
        with_unknown = self.engine.compute_score(
            self.lead, self.weights, signals=["TOTALLY_UNKNOWN_SIGNAL"]
        )
        assert base == with_unknown

    def test_score_does_not_exceed_100(self):
        # Stack many positive signals — result must still be ≤ 100
        many_positive = ["PRIOR_WARM_CONVERSATION"] * 10
        score = self.engine.compute_score(self.lead, self.weights, signals=many_positive)
        assert score <= 100.0

    def test_score_does_not_go_below_0(self):
        many_negative = ["DO_NOT_CONTACT"] * 10
        score = self.engine.compute_score(self.lead, self.weights, signals=many_negative)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# compute_score — signal adjustments via HubSpotSignal-like objects
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("app_ctx")
class TestComputeScoreObjectSignals:
    def setup_method(self):
        self.engine = LeadScoringEngine()
        self.weights = _make_weights()
        self.lead = _make_lead()

    def test_signal_object_with_signal_type_attr(self):
        sig = _make_signal("APPOINTMENT_OCCURRED")
        score = self.engine.compute_score(self.lead, self.weights, signals=[sig])
        assert score == 20.0

    def test_signal_object_negative_adjustment(self):
        sig = _make_signal("SELLER_NOT_INTERESTED")
        score = self.engine.compute_score(self.lead, self.weights, signals=[sig])
        assert score == 0.0  # clamped

    def test_multiple_signal_objects(self):
        signals = [
            _make_signal("PRIOR_WARM_CONVERSATION"),
            _make_signal("OFFER_PREVIOUSLY_SENT"),
        ]
        score = self.engine.compute_score(self.lead, self.weights, signals=signals)
        assert score == 25.0  # 15 + 10

    def test_signal_object_unknown_type_ignored(self):
        sig = _make_signal("NONEXISTENT_TYPE")
        base = self.engine.compute_score(self.lead, self.weights)
        with_unknown = self.engine.compute_score(self.lead, self.weights, signals=[sig])
        assert base == with_unknown


# ---------------------------------------------------------------------------
# compute_score — mixed list (objects + strings)
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("app_ctx")
class TestComputeScoreMixedSignals:
    def setup_method(self):
        self.engine = LeadScoringEngine()
        self.weights = _make_weights()
        self.lead = _make_lead()

    def test_mixed_list_applies_all_adjustments(self):
        signals = [
            _make_signal("APPOINTMENT_OCCURRED"),   # +20
            "OFFER_PREVIOUSLY_SENT",                # +10
        ]
        score = self.engine.compute_score(self.lead, self.weights, signals=signals)
        assert score == 30.0


# ---------------------------------------------------------------------------
# compute_score — suppression_flag clamping
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("app_ctx")
class TestComputeScoreSuppressionFlag:
    def setup_method(self):
        self.engine = LeadScoringEngine()
        self.weights = _make_weights()

    def test_suppression_flag_caps_score_at_10(self):
        # Give the lead a high base score via a positive signal
        lead = _make_lead(suppression_flag=True)
        score = self.engine.compute_score(
            lead, self.weights, signals=["APPOINTMENT_OCCURRED"]
        )
        assert score <= 10.0

    def test_suppression_flag_with_no_signals_caps_at_10(self):
        # Even without signals, a suppressed lead with a high base score
        # should be capped at 10.
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
        score = self.engine.compute_score(lead, self.weights)
        assert score <= 10.0

    def test_suppression_flag_false_does_not_cap(self):
        lead = _make_lead(suppression_flag=False)
        score = self.engine.compute_score(
            lead, self.weights, signals=["APPOINTMENT_OCCURRED"]
        )
        assert score == 20.0  # not capped

    def test_suppression_flag_with_low_score_stays_low(self):
        # If the score is already below 10, suppression flag doesn't raise it
        lead = _make_lead(suppression_flag=True)
        score = self.engine.compute_score(lead, self.weights)
        assert score <= 10.0

    def test_suppression_flag_applied_after_signal_adjustments(self):
        # Positive signals push score above 10, then suppression caps it
        lead = _make_lead(suppression_flag=True)
        score = self.engine.compute_score(
            lead,
            self.weights,
            signals=["PRIOR_WARM_CONVERSATION", "APPOINTMENT_OCCURRED"],  # +35
        )
        assert score == 10.0

    def test_suppression_flag_missing_attribute_treated_as_false(self):
        # Lead without suppression_flag attribute should not be capped
        lead = _make_lead()
        del lead.suppression_flag  # remove the attribute entirely
        score = self.engine.compute_score(
            lead, self.weights, signals=["APPOINTMENT_OCCURRED"]
        )
        assert score == 20.0
