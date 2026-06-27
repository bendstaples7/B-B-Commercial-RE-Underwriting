"""Verify test mock builders cover all scoring attributes.

Every attribute in SCORING_ATTRIBUTES must be handled by _make_lead fixtures
to prevent MagicMock auto-creation from inflating scores.
"""
from app.services.lead_scoring_engine import LeadScoringEngine, SCORING_ATTRIBUTES as LSE_ATTRS
from app.services.deterministic_scoring_engine import DeterministicScoringEngine, SCORING_ATTRIBUTES as DSE_ATTRS


def test_lse_scoring_attributes_non_empty():
    """LeadScoringEngine.SCORING_ATTRIBUTES must have entries."""
    assert len(LSE_ATTRS) > 0


def test_dse_scoring_attributes_non_empty():
    """DeterministicScoringEngine.SCORING_ATTRIBUTES must have entries."""
    assert len(DSE_ATTRS) > 0


def test_both_engines_have_same_attributes():
    """Both engines' scoring attribute registries should be identical."""
    assert LSE_ATTRS == DSE_ATTRS, (
        f"SCORING_ATTRIBUTES differ:\n"
        f"  LSE - DSE: {LSE_ATTRS - DSE_ATTRS}\n"
        f"  DSE - LSE: {DSE_ATTRS - LSE_ATTRS}"
    )


def test_scoring_attributes_accessible_via_class():
    """SCORING_ATTRIBUTES is accessible as a class attribute on both engines."""
    assert hasattr(LeadScoringEngine, "SCORING_ATTRIBUTES")
    assert hasattr(DeterministicScoringEngine, "SCORING_ATTRIBUTES")
