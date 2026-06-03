"""Unit tests for DeterministicScoringEngine — source_type_distress dimension.

Covers task 10.1 requirements:
- source_type_distress dimension for qualifying source types (foreclosure, tax_distress, long_owned)
- Non-qualifying source types → 0 points
- null source_type → 0 points
- Unknown source_type → 0 points; no exception
- tax_distress_data bonus (+5) when non-null
- Combined cap of 15
- absentee_owner short-circuit: always 10 in absentee_owner dimension
- manual_priority passed to _manual_priority_score when non-null
- Tax distress language absent from top_signals
- Tax distress language absent from recommended_action
- Malformed tax_distress_data JSON → log warning; treat as null; no exception

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services.deterministic_scoring_engine import (
    DeterministicScoringEngine,
    SOURCE_TYPE_DISTRESS_QUALIFYING,
    SOURCE_TYPE_DISTRESS_BASE_POINTS,
    SOURCE_TYPE_DISTRESS_TAX_BONUS,
    SOURCE_TYPE_DISTRESS_COMBINED_CAP,
    TAX_DISTRESS_FORBIDDEN_TERMS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(**kwargs):
    """Return a minimal mock lead.  All attributes default to None unless overridden."""
    lead = MagicMock()
    # Zero out all scoring-relevant attributes
    _defaults = {
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
        "county_assessor_pin": None,
        "owner_first_name": None,
        "owner_last_name": None,
        "source": None,
        "data_source": None,
        "square_footage": None,
        "date_skip_traced": None,
        "phone_1": None,
        "email_1": None,
    }
    _defaults.update(kwargs)
    for k, v in _defaults.items():
        setattr(lead, k, v)
    return lead


# ---------------------------------------------------------------------------
# _source_type_distress_score — qualifying source types
# ---------------------------------------------------------------------------

class TestSourceTypeDistressScoreQualifying:
    """Requirement 12.1: 10 points for foreclosure, tax_distress, long_owned."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @pytest.mark.parametrize("source_type", ["foreclosure", "tax_distress", "long_owned"])
    def test_qualifying_source_type_scores_10(self, source_type):
        lead = _make_lead(source_type=source_type)
        score = self.engine._source_type_distress_score(lead)
        assert score == 10.0, (
            f"Expected 10 for source_type={source_type!r}, got {score}"
        )

    @pytest.mark.parametrize("source_type", ["foreclosure", "tax_distress", "long_owned"])
    def test_qualifying_source_type_does_not_exceed_10_without_tax_data(self, source_type):
        lead = _make_lead(source_type=source_type, tax_distress_data=None)
        score = self.engine._source_type_distress_score(lead)
        assert score <= 10.0

    def test_qualifying_source_types_constant_coverage(self):
        """All values in SOURCE_TYPE_DISTRESS_QUALIFYING score exactly 10."""
        for source_type in SOURCE_TYPE_DISTRESS_QUALIFYING:
            lead = _make_lead(source_type=source_type, tax_distress_data=None)
            score = self.engine._source_type_distress_score(lead)
            assert score == float(SOURCE_TYPE_DISTRESS_BASE_POINTS), (
                f"source_type={source_type!r} expected {SOURCE_TYPE_DISTRESS_BASE_POINTS}, got {score}"
            )


# ---------------------------------------------------------------------------
# _source_type_distress_score — non-qualifying source types
# ---------------------------------------------------------------------------

class TestSourceTypeDistressScoreNonQualifying:
    """Non-qualifying and unknown source types → 0 points, no exception."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @pytest.mark.parametrize("source_type", [
        "absentee_owner",   # handled via short-circuit, not this dimension
        "manual_distress",
        "unknown_type",
        "FORECLOSURE",      # wrong case — not in the set
        "",
    ])
    def test_non_qualifying_source_type_scores_0(self, source_type):
        lead = _make_lead(source_type=source_type, tax_distress_data=None)
        score = self.engine._source_type_distress_score(lead)
        assert score == 0.0, (
            f"Expected 0 for source_type={source_type!r}, got {score}"
        )

    def test_null_source_type_scores_0(self):
        lead = _make_lead(source_type=None, tax_distress_data=None)
        score = self.engine._source_type_distress_score(lead)
        assert score == 0.0

    def test_unknown_source_type_no_exception(self):
        lead = _make_lead(source_type="some_completely_unknown_type")
        # Must not raise
        score = self.engine._source_type_distress_score(lead)
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# _source_type_distress_score — tax_distress_data bonus
# ---------------------------------------------------------------------------

class TestSourceTypeDistressTaxBonus:
    """Requirement 12.2: +5 bonus when tax_distress_data is non-null, combined cap = 15."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_non_null_tax_distress_data_adds_5_for_qualifying(self):
        lead_with = _make_lead(
            source_type="foreclosure",
            tax_distress_data={"signal_type": "tax_delinquency", "delinquent_amount": 1000.0, "tax_year": 2022},
        )
        lead_without = _make_lead(source_type="foreclosure", tax_distress_data=None)

        score_with = self.engine._source_type_distress_score(lead_with)
        score_without = self.engine._source_type_distress_score(lead_without)

        assert score_with - score_without == float(SOURCE_TYPE_DISTRESS_TAX_BONUS), (
            f"Expected exactly +5 bonus, got diff={score_with - score_without}"
        )

    def test_combined_cap_enforced_at_15(self):
        lead = _make_lead(
            source_type="tax_distress",
            tax_distress_data={"signal_type": "tax_sale"},
        )
        score = self.engine._source_type_distress_score(lead)
        assert score == float(SOURCE_TYPE_DISTRESS_COMBINED_CAP), (
            f"Expected combined cap of {SOURCE_TYPE_DISTRESS_COMBINED_CAP}, got {score}"
        )
        assert score <= 15.0

    def test_non_null_tax_data_on_non_qualifying_source_type(self):
        """Bonus applies only on top of base; 0 base + 5 bonus = 5 (not capped further)."""
        lead = _make_lead(
            source_type="manual_distress",
            tax_distress_data={"signal_type": "tax_delinquency"},
        )
        score = self.engine._source_type_distress_score(lead)
        # 0 (base) + 5 (bonus) = 5
        assert score == 5.0

    def test_tax_distress_data_empty_dict_counts_as_non_null(self):
        """An empty dict is still non-null → bonus applies."""
        lead = _make_lead(source_type="foreclosure", tax_distress_data={})
        score = self.engine._source_type_distress_score(lead)
        assert score == 15.0  # 10 + 5

    def test_malformed_tax_distress_data_json_string_treated_as_null(self):
        """Malformed JSON string → warn, treat as null, no exception."""
        lead = _make_lead(source_type="foreclosure", tax_distress_data="{invalid json}")
        score = self.engine._source_type_distress_score(lead)
        # Malformed → treated as null → only base 10, no bonus
        assert score == 10.0

    def test_malformed_tax_distress_data_logs_warning(self):
        lead = _make_lead(source_type="foreclosure", tax_distress_data="{bad}")
        with patch("app.services.deterministic_scoring_engine.logger") as mock_logger:
            self.engine._source_type_distress_score(lead)
            mock_logger.warning.assert_called_once()

    def test_valid_json_string_tax_distress_data_parsed_and_bonus_applied(self):
        """A valid JSON string is parsed and bonus applies."""
        import json
        data = {"signal_type": "tax_sale"}
        lead = _make_lead(source_type="foreclosure", tax_distress_data=json.dumps(data))
        score = self.engine._source_type_distress_score(lead)
        assert score == 15.0


# ---------------------------------------------------------------------------
# calculate_residential_score — source_type_distress in score_details
# ---------------------------------------------------------------------------

class TestResidentialScoreSourceTypeDistressDimension:
    """source_type_distress must appear in score_details returned by calculate_residential_score."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_source_type_distress_in_score_details(self):
        lead = _make_lead(source_type="foreclosure")
        result = self.engine.calculate_residential_score(lead)
        assert "source_type_distress" in result["score_details"], (
            "source_type_distress dimension missing from score_details"
        )

    def test_source_type_distress_value_correct_foreclosure(self):
        lead = _make_lead(source_type="foreclosure", tax_distress_data=None)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["source_type_distress"] == 10.0

    def test_source_type_distress_value_correct_with_tax_data(self):
        lead = _make_lead(
            source_type="tax_distress",
            tax_distress_data={"signal_type": "tax_sale"},
        )
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["source_type_distress"] == 15.0

    def test_source_type_distress_value_0_for_null_source_type(self):
        lead = _make_lead(source_type=None)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["source_type_distress"] == 0.0

    def test_source_type_distress_contributes_to_total_score(self):
        lead_without = _make_lead(source_type=None)
        lead_with = _make_lead(source_type="long_owned")
        result_without = self.engine.calculate_residential_score(lead_without)
        result_with = self.engine.calculate_residential_score(lead_with)
        assert result_with["total_score"] - result_without["total_score"] == 10.0


# ---------------------------------------------------------------------------
# absentee_owner short-circuit
# ---------------------------------------------------------------------------

class TestAbsenteeOwnerShortCircuit:
    """Requirement 12.5: source_type='absentee_owner' always scores 10 in absentee_owner
    dimension regardless of mailing/property address comparison."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_absentee_owner_source_type_scores_10_no_addresses(self):
        """No mailing address — normally 0, but short-circuit gives 10."""
        lead = _make_lead(
            source_type="absentee_owner",
            mailing_address=None,
            property_street=None,
        )
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["absentee_owner"] == 10.0

    def test_absentee_owner_source_type_scores_10_same_addresses(self):
        """Even when mailing == property (would normally be 0), short-circuit gives 10."""
        lead = _make_lead(
            source_type="absentee_owner",
            mailing_address="123 Main St",
            property_street="123 Main St",
        )
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["absentee_owner"] == 10.0

    def test_absentee_owner_source_type_scores_10_different_addresses(self):
        """When mailing != property — short-circuit still gives 10 (same result, correct path)."""
        lead = _make_lead(
            source_type="absentee_owner",
            mailing_address="456 Other Ave",
            property_street="123 Main St",
        )
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["absentee_owner"] == 10.0

    def test_non_absentee_source_type_uses_mailing_address_logic(self):
        """For other source types, normal mailing-address logic applies."""
        # Same address → 0
        lead_same = _make_lead(
            source_type="foreclosure",
            mailing_address="123 Main St",
            property_street="123 Main St",
        )
        result_same = self.engine.calculate_residential_score(lead_same)
        assert result_same["score_details"]["absentee_owner"] == 0.0

        # Different address → 10
        lead_diff = _make_lead(
            source_type="foreclosure",
            mailing_address="456 Other Ave",
            property_street="123 Main St",
        )
        result_diff = self.engine.calculate_residential_score(lead_diff)
        assert result_diff["score_details"]["absentee_owner"] == 10.0


# ---------------------------------------------------------------------------
# manual_priority integration
# ---------------------------------------------------------------------------

class TestManualPriorityIntegration:
    """Requirement 12.4: manual_priority is passed through to the scoring method."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_null_manual_priority_scores_0(self):
        lead = _make_lead(manual_priority=None)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["manual_priority"] == 0.0

    def test_manual_priority_5_scores_5(self):
        lead = _make_lead(manual_priority=5)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["manual_priority"] == 5.0

    def test_manual_priority_10_capped_at_max(self):
        lead = _make_lead(manual_priority=10)
        result = self.engine.calculate_residential_score(lead)
        # Max for residential is 10
        assert result["score_details"]["manual_priority"] == 10.0

    def test_manual_priority_above_max_clamped(self):
        lead = _make_lead(manual_priority=50)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["manual_priority"] == 10.0  # clamped at max


# ---------------------------------------------------------------------------
# Tax distress language absent from top_signals
# ---------------------------------------------------------------------------

class TestTaxDistressLanguageAbsentFromTopSignals:
    """Requirement 12.3: forbidden terms must not appear in top_signals."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @pytest.mark.parametrize("forbidden_term", [
        "tax_delinquency", "tax_sale", "delinquent",
        "tax delinquency", "tax sale",
    ])
    def test_forbidden_term_not_in_top_signals_dimension_names(self, forbidden_term):
        """A hypothetical dimension with a forbidden name must be filtered out."""
        # Inject forbidden dimension directly into score_details
        score_details = {
            "property_type_fit": 10.0,
            forbidden_term: 8.0,  # this should be filtered
            "source_type_distress": 10.0,
        }
        signals = self.engine.extract_top_signals(score_details)
        dim_names = [s["dimension"] for s in signals]
        assert forbidden_term not in dim_names, (
            f"Forbidden term {forbidden_term!r} appeared in top_signals: {signals}"
        )

    def test_source_type_distress_dimension_name_is_allowed(self):
        """'source_type_distress' is not a forbidden term and must appear in signals."""
        score_details = {"source_type_distress": 10.0, "property_type_fit": 5.0}
        signals = self.engine.extract_top_signals(score_details)
        dim_names = [s["dimension"] for s in signals]
        assert "source_type_distress" in dim_names

    def test_zero_point_dimensions_excluded(self):
        """Dimensions with 0 points are not included in top_signals."""
        score_details = {"source_type_distress": 0.0, "property_type_fit": 10.0}
        signals = self.engine.extract_top_signals(score_details)
        dim_names = [s["dimension"] for s in signals]
        assert "source_type_distress" not in dim_names

    def test_top_signals_sorted_descending(self):
        score_details = {"a": 5.0, "b": 15.0, "c": 10.0}
        signals = self.engine.extract_top_signals(score_details)
        points = [s["points"] for s in signals]
        assert points == sorted(points, reverse=True)


# ---------------------------------------------------------------------------
# Tax distress language absent from recommended_action
# ---------------------------------------------------------------------------

class TestTaxDistressLanguageAbsentFromRecommendedAction:
    """Requirement 12.3: recommended_action must never contain forbidden tax terms."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @pytest.mark.parametrize("source_type", ["foreclosure", "tax_distress", "long_owned"])
    def test_recommended_action_contains_no_tax_distress_language(self, source_type):
        lead = _make_lead(source_type=source_type)
        # Score across several tiers to cover all action paths
        for score_tier in ["A", "B", "C", "D"]:
            for dq_score in [30.0, 70.0, 90.0]:
                action = self.engine.get_recommended_action(
                    lead, total_score=50.0, data_quality_score=dq_score,
                    score_tier=score_tier,
                )
                action_lower = action.lower()
                for term in TAX_DISTRESS_FORBIDDEN_TERMS:
                    assert term not in action_lower, (
                        f"Forbidden term {term!r} found in recommended_action={action!r} "
                        f"for source_type={source_type!r}, tier={score_tier!r}"
                    )

    def test_all_allowed_actions_free_of_forbidden_terms(self):
        from app.services.deterministic_scoring_engine import ALLOWED_ACTIONS
        for action in ALLOWED_ACTIONS:
            action_lower = action.lower()
            for term in TAX_DISTRESS_FORBIDDEN_TERMS:
                assert term not in action_lower, (
                    f"ALLOWED_ACTION {action!r} contains forbidden term {term!r}"
                )


# ---------------------------------------------------------------------------
# score_details completeness
# ---------------------------------------------------------------------------

class TestScoreDetailsCompleteness:
    """score_details must contain 'source_type_distress' key for all residential scores."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    @pytest.mark.parametrize("source_type", [
        None, "foreclosure", "tax_distress", "long_owned",
        "absentee_owner", "manual_distress", "unknown_xyz",
    ])
    def test_source_type_distress_always_present_in_score_details(self, source_type):
        lead = _make_lead(source_type=source_type)
        result = self.engine.calculate_residential_score(lead)
        assert "source_type_distress" in result["score_details"], (
            f"source_type_distress missing from score_details for source_type={source_type!r}"
        )

    @pytest.mark.parametrize("source_type", [
        None, "foreclosure", "tax_distress", "long_owned",
        "absentee_owner", "manual_distress",
    ])
    def test_source_type_distress_value_is_non_negative(self, source_type):
        lead = _make_lead(source_type=source_type)
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["source_type_distress"] >= 0.0

    @pytest.mark.parametrize("source_type", [
        None, "foreclosure", "tax_distress", "long_owned",
        "absentee_owner", "manual_distress",
    ])
    def test_source_type_distress_value_does_not_exceed_cap(self, source_type):
        lead = _make_lead(
            source_type=source_type,
            tax_distress_data={"signal_type": "tax_delinquency"},
        )
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["source_type_distress"] <= float(SOURCE_TYPE_DISTRESS_COMBINED_CAP)
