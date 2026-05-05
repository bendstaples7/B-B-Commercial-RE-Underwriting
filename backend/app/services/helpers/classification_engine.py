"""Classification engine for condo filter analysis.

Applies deterministic priority-ordered rules to address group metrics
to produce a condo risk classification and building sale assessment.
"""
from dataclasses import dataclass


@dataclass
class AddressGroupMetrics:
    """Computed metrics for an address group (set of leads sharing a normalized address)."""

    property_count: int
    pin_count: int
    owner_count: int
    has_unit_number: bool
    has_condo_language: bool
    missing_pin_count: int
    missing_owner_count: int


@dataclass
class ClassificationResult:
    """Result of applying classification rules to an address group's metrics."""

    condo_risk_status: str          # likely_not_condo | likely_condo | partial_condo_possible | needs_review | unknown
    building_sale_possible: str     # yes | no | maybe | unknown
    triggered_rules: list[str]      # e.g., ["rule_1_unit_number"]
    reason: str                     # human-readable explanation
    confidence: str                 # high | medium | low


def classify(metrics: AddressGroupMetrics) -> ClassificationResult:
    """Apply deterministic priority-ordered rules to produce classification.

    Rule priority (first match wins):
    1. has_unit_number=True → likely_condo / no / high confidence
    2. has_condo_language=True → likely_condo / no / high confidence
    3. pin_count >= 4 AND owner_count >= 2 → likely_condo / no / high confidence
    4. pin_count=1 AND owner_count=1 AND no unit AND no condo language
       → likely_not_condo / yes / high confidence
    5. pin_count >= 2 AND owner_count=1 AND no unit
       → partial_condo_possible / maybe / medium confidence
    6. pin_count >= 2 AND owner_count > 1 AND no unit AND no condo language
       → needs_review / unknown / medium confidence
    7. missing_pin_count > 0 OR missing_owner_count > 0
       → needs_review / unknown / low confidence
    8. Default fallback → needs_review / unknown / low confidence

    Deterministic: identical metrics always produce identical results.

    Parameters
    ----------
    metrics : AddressGroupMetrics
        The computed metrics for an address group.

    Returns
    -------
    ClassificationResult
        The classification result with status, triggered rules, reason,
        and confidence.
    """
    # Rule 1: Unit number detected
    if metrics.has_unit_number:
        return ClassificationResult(
            condo_risk_status="likely_condo",
            building_sale_possible="no",
            triggered_rules=["rule_1_unit_number"],
            reason="Address contains unit/apartment/suite marker indicating individual units",
            confidence="high",
        )

    # Rule 2: Condo language detected
    if metrics.has_condo_language:
        return ClassificationResult(
            condo_risk_status="likely_condo",
            building_sale_possible="no",
            triggered_rules=["rule_2_condo_language"],
            reason="Property type or assessor class contains condo-related terminology",
            confidence="high",
        )

    # Rule 3: Multiple PINs and multiple owners
    if metrics.pin_count >= 4 and metrics.owner_count >= 2:
        return ClassificationResult(
            condo_risk_status="likely_condo",
            building_sale_possible="no",
            triggered_rules=["rule_3_multiple_pins_owners"],
            reason=(
                f"Multiple PINs ({metrics.pin_count}) and multiple owners "
                f"({metrics.owner_count}) suggest fragmented ownership"
            ),
            confidence="high",
        )

    # Rule 4: Single PIN, single owner, no condo indicators
    if (
        metrics.pin_count == 1
        and metrics.owner_count == 1
        and not metrics.has_unit_number
        and not metrics.has_condo_language
    ):
        return ClassificationResult(
            condo_risk_status="likely_not_condo",
            building_sale_possible="yes",
            triggered_rules=["rule_4_single_pin_owner"],
            reason="Single PIN and single owner with no condo indicators suggests whole-building ownership",
            confidence="high",
        )

    # Rule 5: Multiple PINs, single owner, no unit marker
    if (
        metrics.pin_count >= 2
        and metrics.owner_count == 1
        and not metrics.has_unit_number
    ):
        return ClassificationResult(
            condo_risk_status="partial_condo_possible",
            building_sale_possible="maybe",
            triggered_rules=["rule_5_multiple_pins_single_owner"],
            reason=(
                f"Multiple PINs ({metrics.pin_count}) but single owner — "
                f"may be partially condoized or multi-parcel ownership"
            ),
            confidence="medium",
        )

    # Rule 6: Multiple PINs, multiple owners, no unit, no condo language
    if (
        metrics.pin_count >= 2
        and metrics.owner_count > 1
        and not metrics.has_unit_number
        and not metrics.has_condo_language
    ):
        return ClassificationResult(
            condo_risk_status="needs_review",
            building_sale_possible="unknown",
            triggered_rules=["rule_6_multiple_pins_owners_no_indicators"],
            reason=(
                f"Multiple PINs ({metrics.pin_count}) and owners "
                f"({metrics.owner_count}) without condo indicators — manual review recommended"
            ),
            confidence="medium",
        )

    # Rule 7: Missing data
    if metrics.missing_pin_count > 0 or metrics.missing_owner_count > 0:
        return ClassificationResult(
            condo_risk_status="needs_review",
            building_sale_possible="unknown",
            triggered_rules=["rule_7_missing_data"],
            reason=(
                f"Incomplete data (missing PINs: {metrics.missing_pin_count}, "
                f"missing owners: {metrics.missing_owner_count}) — cannot classify reliably"
            ),
            confidence="low",
        )

    # Rule 8: Default fallback
    return ClassificationResult(
        condo_risk_status="needs_review",
        building_sale_possible="unknown",
        triggered_rules=["rule_8_default_fallback"],
        reason="Does not match any specific classification rule — manual review recommended",
        confidence="low",
    )
