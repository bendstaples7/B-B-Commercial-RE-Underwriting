"""Integration tests for the unified scoring engine and CookCountyAssessorPlugin.

Covers merged LeadScoringEngine features:
- HubSpot signal adjustments as post-processing
- suppression_flag cap
- Configurable weights
- Contact completeness checking
- ACTIVE_OUTREACH_THRESHOLD
- CookCountyAssessorPlugin instantiation and PIN parsing
"""
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.deterministic_scoring_engine import (
    DeterministicScoringEngine,
    ACTIVE_OUTREACH_THRESHOLD,
    DEFAULT_SCORING_WEIGHTS,
)
from app.services.lead_scoring_engine import LeadScoringEngine
from app.services.plugins.cook_county_assessor import CookCountyAssessorPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(**kwargs):
    """Return a minimal mock lead with all default attributes set to None/False."""
    lead = MagicMock()
    defaults = {
        "id": 1,
        "property_type": None,
        "property_city": None,
        "property_zip": None,
        "units": None,
        "mailing_address": None,
        "mailing_city": None,
        "mailing_state": None,
        "mailing_zip": None,
        "property_street": None,
        "acquisition_date": None,
        "notes": None,
        "manual_priority": None,
        "source_type": None,
        "tax_distress_data": None,
        "lead_category": "residential",
        "do_not_contact": False,
        "suppression_flag": False,
        "county_assessor_pin": None,
        "owner_first_name": None,
        "owner_last_name": None,
        "source": None,
        "data_source": None,
        "square_footage": None,
        "date_skip_traced": None,
        "phone_1": None,
        "email_1": None,
        "phone_2": None,
        "phone_3": None,
        "phone_4": None,
        "phone_5": None,
        "phone_6": None,
        "phone_7": None,
        "email_2": None,
        "email_3": None,
        "email_4": None,
        "email_5": None,
        "socials": None,
        "year_built": None,
        "lot_size": None,
        "mailer_history": None,
        "has_phone": False,
        "has_email": False,
        "follow_up_date": None,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(lead, k, v)
    return lead


# ---------------------------------------------------------------------------
# ACTIVE_OUTREACH_THRESHOLD
# ---------------------------------------------------------------------------

class TestActiveOutreachThreshold:
    """Verify ACTIVE_OUTREACH_THRESHOLD constant is available from the merged engine."""

    def test_constant_exists(self):
        assert ACTIVE_OUTREACH_THRESHOLD == 30.0

    def test_constant_exported(self):
        """Can import from services package."""
        from app.services import ACTIVE_OUTREACH_THRESHOLD as threshold
        assert threshold == 30.0


# ---------------------------------------------------------------------------
# SIGNAL_ADJUSTMENTS constant
# ---------------------------------------------------------------------------

class TestSignalAdjustments:
    """Verify SIGNAL_ADJUSTMENTS from LeadScoringEngine is present in merged engine."""

    def test_signal_adjustments_defined(self):
        assert isinstance(LeadScoringEngine.SIGNAL_ADJUSTMENTS, dict)
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["PRIOR_WARM_CONVERSATION"] == +15.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["APPOINTMENT_OCCURRED"] == +20.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["OFFER_PREVIOUSLY_SENT"] == +10.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["SELLER_SAID_MAYBE_LATER"] == -5.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["SELLER_NOT_INTERESTED"] == -40.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["DO_NOT_CONTACT"] == -50.0
        assert LeadScoringEngine.SIGNAL_ADJUSTMENTS["WRONG_NUMBER"] == -30.0

    def test_signal_adjustments_exported(self):
        from app.services.lead_scoring_engine import LeadScoringEngine as _LSE
        assert _LSE.SIGNAL_ADJUSTMENTS["PRIOR_WARM_CONVERSATION"] == +15.0


# ---------------------------------------------------------------------------
# apply_signal_adjustments
# ---------------------------------------------------------------------------

class TestApplySignalAdjustments:
    """Tests for DeterministicScoringEngine.apply_signal_adjustments."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_no_signals_returns_score_unchanged(self):
        result = self.engine.apply_signal_adjustments(50.0)
        assert result == 50.0

    def test_empty_signals_list_returns_score_unchanged(self):
        result = self.engine.apply_signal_adjustments(50.0, signals=[])
        assert result == 50.0

    def test_warm_conversation_adds_15(self):
        result = self.engine.apply_signal_adjustments(50.0, signals=["PRIOR_WARM_CONVERSATION"])
        assert result == 65.0

    def test_not_interested_subtracts_40(self):
        result = self.engine.apply_signal_adjustments(60.0, signals=["SELLER_NOT_INTERESTED"])
        assert result == 20.0

    def test_do_not_contact_subtracts_50(self):
        result = self.engine.apply_signal_adjustments(50.0, signals=["DO_NOT_CONTACT"])
        assert result == 0.0

    def test_multiple_signals_accumulate(self):
        result = self.engine.apply_signal_adjustments(
            50.0,
            signals=["PRIOR_WARM_CONVERSATION", "APPOINTMENT_OCCURRED"],
        )
        assert result == 85.0

    def test_score_clamped_to_0(self):
        result = self.engine.apply_signal_adjustments(
            10.0,
            signals=["DO_NOT_CONTACT"],
        )
        assert result == 0.0

    def test_score_clamped_to_100(self):
        result = self.engine.apply_signal_adjustments(90.0, signals=["PRIOR_WARM_CONVERSATION"])
        assert result == 100.0

    def test_score_rounded_to_2_decimal_places(self):
        result = self.engine.apply_signal_adjustments(55.555, signals=["PRIOR_WARM_CONVERSATION"])
        assert result == 70.56  # 55.555 + 15 = 70.555 -> rounded to 70.56

    def test_unrecognized_signal_ignored(self):
        result = self.engine.apply_signal_adjustments(50.0, signals=["UNKNOWN_SIGNAL"])
        assert result == 50.0

    def test_suppression_flag_caps_at_10(self):
        lead = _make_lead(suppression_flag=True)
        result = self.engine.apply_signal_adjustments(80.0, signals=[], lead=lead)
        assert result == 10.0

    def test_suppression_flag_with_negative_adjustment(self):
        """Suppression cap applies after signal adjustments."""
        lead = _make_lead(suppression_flag=True)
        result = self.engine.apply_signal_adjustments(
            5.0, signals=["DO_NOT_CONTACT"], lead=lead
        )
        # 5 + (-50) = -45 -> clamped to 0.0 (suppression cap is min(score, 10))
        assert result == 0.0

    def test_no_suppression_flag_normal_scoring(self):
        lead = _make_lead(suppression_flag=False)
        result = self.engine.apply_signal_adjustments(80.0, signals=[], lead=lead)
        assert result == 80.0

    def test_signal_string_type_via_object(self):
        """Accept signal objects with signal_type attribute (HubSpotSignal model)."""
        signal = MagicMock()
        signal.signal_type = "PRIOR_WARM_CONVERSATION"
        result = self.engine.apply_signal_adjustments(50.0, signals=[signal])
        assert result == 65.0


# ---------------------------------------------------------------------------
# apply_configurable_weights
# ---------------------------------------------------------------------------

class TestConfigurableWeights:
    """Tests for DeterministicScoringEngine.apply_configurable_weights."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_none_weights_returns_original_score(self):
        result = self.engine.apply_configurable_weights(50.0, {}, weights=None)
        assert result == 50.0

    def test_with_weights_recalculates(self):
        details = {
            "property_type_fit": 20.0,
            "neighborhood_fit": 10.0,
            "absentee_owner": 10.0,
            "owner_mailing_quality": 10.0,
        }
        weights = {
            "property_characteristics": 0.5,
            "data_completeness": 0.2,
            "owner_situation": 0.2,
            "location_desirability": 0.1,
        }
        result = self.engine.apply_configurable_weights(50.0, details, weights=weights)
        # property dims: 20.0 * 0.5 = 10.0
        # completeness dims: 10.0 * 0.2 = 2.0
        # owner dims: 10.0 * 0.2 = 2.0
        # location dims: 10.0 * 0.1 = 1.0
        # total = 15.0
        assert result == 15.0

    def test_empty_details_with_weights(self):
        result = self.engine.apply_configurable_weights(0.0, {}, weights=DEFAULT_SCORING_WEIGHTS)
        assert result == 0.0


# ---------------------------------------------------------------------------
# recalculate_lead_score with signals and weights
# ---------------------------------------------------------------------------

class TestRecalculateWithSignalsAndWeights:
    """Tests that recalculate_lead_score accepts signals and weights parameters."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @patch("app.services.deterministic_scoring_engine.db.session.commit")
    @patch("app.services.deterministic_scoring_engine.db.session.add")
    def test_recalculate_with_signals(self, mock_add, mock_commit):
        """recalculate_lead_score should accept signals and apply adjustments."""
        lead = _make_lead(
            property_type="single_family",
            property_city="Austin",
            property_zip="78701",
            units=2,
            mailing_address="456 Other Ave",
            property_street="123 Main St",
        )
        # Override lead.id to be an int for DB operations
        lead.id = 1

        result = self.engine.recalculate_lead_score(
            lead,
            signals=["PRIOR_WARM_CONVERSATION"],
        )
        # Should have the signal adjustment applied (+15)
        assert result.total_score >= 15.0

    @patch("app.services.deterministic_scoring_engine.db.session.commit")
    @patch("app.services.deterministic_scoring_engine.db.session.add")
    def test_recalculate_without_signals(self, mock_add, mock_commit):
        """recalculate_lead_score should work without optional parameters."""
        lead = _make_lead(
            property_type="single_family",
            property_city="Austin",
            property_zip="78701",
        )
        lead.id = 1

        result = self.engine.recalculate_lead_score(lead)
        assert result.total_score >= 0.0
        assert result.score_tier is not None
        assert result.recommended_action is not None


# ---------------------------------------------------------------------------
# _compute_recommended_action_from_signals
# ---------------------------------------------------------------------------

class TestRecommendedActionFromSignals:
    """Tests for _compute_recommended_action_from_signals (LeadScoringEngine compatibility)."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_no_signals_returns_none(self):
        assert self.engine._compute_recommended_action_from_signals(None) is None
        assert self.engine._compute_recommended_action_from_signals([]) is None

    def test_do_not_contact_returns_do_not_contact(self):
        result = self.engine._compute_recommended_action_from_signals(["DO_NOT_CONTACT"])
        assert result == "DO_NOT_CONTACT"

    def test_not_interested_returns_do_not_contact(self):
        result = self.engine._compute_recommended_action_from_signals(["SELLER_NOT_INTERESTED"])
        assert result == "DO_NOT_CONTACT"

    def test_maybe_later_returns_follow_up(self):
        result = self.engine._compute_recommended_action_from_signals(["SELLER_SAID_MAYBE_LATER"])
        assert result == "FOLLOW_UP_LATER"

    def test_offer_sent_returns_revisit(self):
        result = self.engine._compute_recommended_action_from_signals(["OFFER_PREVIOUSLY_SENT"])
        assert result == "REVISIT_OFFER"

    def test_highest_priority_wins(self):
        """DO_NOT_CONTACT (rank 1) should take priority over OFFER_PREVIOUSLY_SENT (rank 3)."""
        result = self.engine._compute_recommended_action_from_signals([
            "OFFER_PREVIOUSLY_SENT",
            "DO_NOT_CONTACT",
        ])
        assert result == "DO_NOT_CONTACT"

    def test_most_recent_for_same_priority(self):
        """Most recent signal of same priority should win."""
        result = self.engine._compute_recommended_action_from_signals([
            "DO_NOT_CONTACT",
            "SELLER_NOT_INTERESTED",  # Same priority (1) as DO_NOT_CONTACT, more recent
        ])
        # Both rank 1, SELLER_NOT_INTERESTED is more recent -> DO_NOT_CONTACT
        assert result == "DO_NOT_CONTACT"


# ---------------------------------------------------------------------------
# CookCountyAssessorPlugin — instantiation and PIN parsing
# ---------------------------------------------------------------------------

class TestCookCountyAssessorPlugin:
    """Smoke tests for CookCountyAssessorPlugin instantiation and PIN parsing."""

    def test_plugin_can_be_instantiated(self):
        plugin = CookCountyAssessorPlugin()
        assert plugin.name == "cook_county_assessor"
        assert isinstance(plugin, CookCountyAssessorPlugin)

    def test_plugin_has_lookup_method(self):
        plugin = CookCountyAssessorPlugin()
        assert hasattr(plugin, "lookup")
        assert callable(plugin.lookup)

    def test_plugin_has_lookup_by_pin_method(self):
        plugin = CookCountyAssessorPlugin()
        assert hasattr(plugin, "lookup_by_pin")
        assert callable(plugin.lookup_by_pin)

    def test_extract_pin_dashed_format(self):
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin("14-28-400-008-0000")
        assert pin == "14-28-400-008-0000"

    def test_extract_pin_condensed_format(self):
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin("14284000080000")
        assert pin == "14284000080000"

    def test_extract_pin_from_address_with_pin(self):
        """PIN embedded in address string."""
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin("123 Main St PIN 14-28-400-008-0000")
        # Dashes are stripped, so the condensed 14-digit form is returned
        assert pin == "14-28-400-008-0000" or pin == "14284000080000"

    def test_extract_pin_none_for_normal_address(self):
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin("123 Main Street, Chicago, IL 60614")
        assert pin is None

    def test_extract_pin_empty_string(self):
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin("")
        assert pin is None

    def test_extract_pin_none_input(self):
        plugin = CookCountyAssessorPlugin()
        pin = plugin._extract_pin(None)
        assert pin is None

    def test_plugin_returns_none_for_normal_address(self):
        """lookup() should return None for a regular address (no PIN)."""
        plugin = CookCountyAssessorPlugin()
        result = plugin.lookup("123 Main St, Chicago, IL", "John Doe")
        assert result is None

    def test_plugin_can_be_imported_via_services(self):
        from app.services import CookCountyAssessorPlugin as PluginClass
        assert PluginClass is CookCountyAssessorPlugin


# ---------------------------------------------------------------------------
# Integration: recalculate_lead_score with all merged features
# ---------------------------------------------------------------------------

class TestUnifiedScoringIntegration:
    """End-to-end integration test combining all merged features."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @patch("app.services.deterministic_scoring_engine.db.session.commit")
    @patch("app.services.deterministic_scoring_engine.db.session.add")
    def test_full_pipeline_with_signal_adjustment(self, mock_add, mock_commit):
        """Score a lead, apply signals, verify tier/action are computed correctly."""
        lead = _make_lead(
            property_type="multi_family",
            property_city="Chicago",
            property_zip="60614",
            units=3,
            mailing_address="456 Other Ave",
            property_street="123 Main St",
            county_assessor_pin="14-28-400-008-0000",
            source="foreclosure",
            tax_distress_data={"signal_type": "tax_delinquency"},
        )
        lead.id = 1

        result = self.engine.recalculate_lead_score(
            lead,
            signals=["PRIOR_WARM_CONVERSATION"],
        )

        # Verify all fields populated
        assert result.total_score > 0
        assert isinstance(result.total_score, float)
        assert result.score_tier in ("A", "B", "C", "D")
        assert result.score_version is not None
        assert isinstance(result.recommended_action, str)
        assert isinstance(result.top_signals, list)
        assert isinstance(result.score_details, dict)
        assert isinstance(result.missing_data, list)


# ---------------------------------------------------------------------------
# DEFAULT_SCORING_WEIGHTS availability
# ---------------------------------------------------------------------------

class TestDefaultScoringWeights:
    """Verify DEFAULT_SCORING_WEIGHTS constant is accessible."""

    def test_default_weights_defined(self):
        assert DEFAULT_SCORING_WEIGHTS["property_characteristics"] == 0.30
        assert DEFAULT_SCORING_WEIGHTS["data_completeness"] == 0.20
        assert DEFAULT_SCORING_WEIGHTS["owner_situation"] == 0.30
        assert DEFAULT_SCORING_WEIGHTS["location_desirability"] == 0.20