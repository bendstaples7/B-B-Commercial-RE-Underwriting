"""
Pure scenario computation engine for the Commercial OM PDF Intake pipeline.

``compute_scenarios`` is a stateless module-level function that takes a
``ScenarioInputs`` frozen dataclass and returns a ``ScenarioComparison``
frozen dataclass.  It has no I/O, no database access, and no side effects,
making it straightforward to test with Hypothesis property-based tests.

All arithmetic uses ``Decimal`` throughout to avoid floating-point rounding
errors in financial calculations.

Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.2, 5.3, 5.4, 5.5, 5.6,
              5.7, 5.8, 5.9
"""

from __future__ import annotations

from decimal import Decimal

from .om_intake_dataclasses import (
    ScenarioComparison,
    ScenarioInputs,
    ScenarioMetrics,
    UnitMixComparisonRow,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_VARIANCE_THRESHOLD = Decimal("0.10")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_div(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """Return ``numerator / denominator``, or ``None`` if either is ``None``
    or the denominator is zero.

    This is the single point of truth for all division operations in the
    engine, enforcing the zero-guard rules from Requirements 4.7, 4.8, 5.8,
    5.9.
    """
    if numerator is None or denominator is None:
        return None
    if denominator == _ZERO:
        return None
    return numerator / denominator


def _compute_dscr(
    noi_annual: Decimal | None,
    debt_service_annual: Decimal | None,
    loan_amount: Decimal | None,
    interest_rate: Decimal | None,
) -> Decimal | None:
    """Compute DSCR only when financing data is fully available.

    Requirements 5.3: only compute if ``loan_amount > 0`` AND
    ``interest_rate > 0`` AND ``debt_service_annual > 0``.
    """
    if loan_amount is None or loan_amount <= _ZERO:
        return None
    if interest_rate is None or interest_rate <= _ZERO:
        return None
    if debt_service_annual is None or debt_service_annual <= _ZERO:
        return None
    return _safe_div(noi_annual, debt_service_annual)


# ---------------------------------------------------------------------------
# Realistic scenario helpers
# ---------------------------------------------------------------------------


def _compute_realistic_gpi(inputs: ScenarioInputs) -> Decimal | None:
    """``realistic_gpi = sum(market_rent_estimate * unit_count) * 12``.

    Returns ``None`` if ANY ``market_rent_estimate`` is ``None``.

    Requirements: 4.4
    """
    total = _ZERO
    for row in inputs.unit_mix:
        if row.market_rent_estimate is None:
            return None
        total += row.market_rent_estimate * Decimal(row.unit_count)
    return total * Decimal("12")


def _compute_realistic_monthly_rent_total(inputs: ScenarioInputs) -> Decimal | None:
    """``monthly_rent_total = sum(market_rent_estimate * unit_count)``.

    Returns ``None`` if ANY ``market_rent_estimate`` is ``None``.
    """
    total = _ZERO
    for row in inputs.unit_mix:
        if row.market_rent_estimate is None:
            return None
        total += row.market_rent_estimate * Decimal(row.unit_count)
    return total


def _compute_realistic_egi(
    realistic_gpi: Decimal | None,
    inputs: ScenarioInputs,
) -> Decimal | None:
    """``realistic_egi = realistic_gpi * (1 - vacancy_rate) + sum(other_income)``.

    Returns ``None`` if ``realistic_gpi`` is ``None``.

    Requirements: 4.5
    """
    if realistic_gpi is None:
        return None
    other_income = sum(
        (item.annual_amount for item in inputs.other_income_items),
        _ZERO,
    )
    return realistic_gpi * (_ONE - inputs.proforma_vacancy_rate) + other_income


def _compute_realistic_noi(
    realistic_egi: Decimal | None,
    proforma_gross_expenses: Decimal | None,
) -> Decimal | None:
    """``realistic_noi = realistic_egi - proforma_gross_expenses``.

    Returns ``None`` if either operand is ``None``.

    Requirements: 4.6
    """
    if realistic_egi is None or proforma_gross_expenses is None:
        return None
    return realistic_egi - proforma_gross_expenses


# ---------------------------------------------------------------------------
# Broker scenario helpers
# ---------------------------------------------------------------------------


def _compute_broker_current_monthly_rent_total(inputs: ScenarioInputs) -> Decimal | None:
    """``monthly_rent_total = sum(current_avg_rent * unit_count)``.

    Returns ``None`` if ANY ``current_avg_rent`` is ``None``.
    """
    total = _ZERO
    for row in inputs.unit_mix:
        if row.current_avg_rent is None:
            return None
        total += row.current_avg_rent * Decimal(row.unit_count)
    return total


def _compute_broker_proforma_monthly_rent_total(inputs: ScenarioInputs) -> Decimal | None:
    """``monthly_rent_total = sum(proforma_rent * unit_count)``.

    Returns ``None`` if ANY ``proforma_rent`` is ``None``.
    """
    total = _ZERO
    for row in inputs.unit_mix:
        if row.proforma_rent is None:
            return None
        total += row.proforma_rent * Decimal(row.unit_count)
    return total


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------


def _compute_significant_variance_flag(
    realistic_noi: Decimal | None,
    proforma_noi: Decimal | None,
) -> bool | None:
    """``|realistic_noi - proforma_noi| / |proforma_noi| > 0.10``.

    Returns ``None`` if ``proforma_noi`` is ``None`` or zero.

    Requirements: 5.4, 5.5
    """
    if proforma_noi is None or proforma_noi == _ZERO:
        return None
    if realistic_noi is None:
        return None
    variance = abs(realistic_noi - proforma_noi) / abs(proforma_noi)
    return variance > _VARIANCE_THRESHOLD


def _compute_realistic_cap_rate_below_proforma(
    realistic_cap_rate: Decimal | None,
    proforma_cap_rate: Decimal | None,
) -> bool | None:
    """``realistic_cap_rate < proforma_cap_rate``.

    Returns ``None`` if either cap rate is ``None``.

    Requirements: 5.6
    """
    if realistic_cap_rate is None or proforma_cap_rate is None:
        return None
    return realistic_cap_rate < proforma_cap_rate


# ---------------------------------------------------------------------------
# Unit mix comparison
# ---------------------------------------------------------------------------


def _build_unit_mix_comparison(
    inputs: ScenarioInputs,
) -> tuple[UnitMixComparisonRow, ...]:
    """One ``UnitMixComparisonRow`` per row in ``inputs.unit_mix``, copying
    all fields directly.

    Requirements: 5.7
    """
    rows = []
    for row in inputs.unit_mix:
        rows.append(
            UnitMixComparisonRow(
                unit_type_label=row.unit_type_label,
                unit_count=row.unit_count,
                sqft=row.sqft,
                current_avg_rent=row.current_avg_rent,
                proforma_rent=row.proforma_rent,
                market_rent_estimate=row.market_rent_estimate,
                market_rent_low=row.market_rent_low,
                market_rent_high=row.market_rent_high,
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_scenarios(inputs: ScenarioInputs) -> ScenarioComparison:
    """Compute the three-scenario comparison from ``inputs``.

    This is a pure function: given the same ``inputs`` it always returns the
    same ``ScenarioComparison``.  It performs no I/O and has no side effects.

    Parameters
    ----------
    inputs:
        All data required to compute the three scenarios.

    Returns
    -------
    ScenarioComparison
        A frozen dataclass containing ``broker_current``, ``broker_proforma``,
        ``realistic``, ``unit_mix_comparison``, ``significant_variance_flag``,
        and ``realistic_cap_rate_below_proforma``.

    Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.2, 5.3, 5.4, 5.5, 5.6,
                  5.7, 5.8, 5.9
    """
    asking_price = inputs.asking_price

    # ------------------------------------------------------------------
    # Realistic scenario
    # ------------------------------------------------------------------
    realistic_gpi = _compute_realistic_gpi(inputs)
    realistic_egi = _compute_realistic_egi(realistic_gpi, inputs)
    realistic_noi = _compute_realistic_noi(realistic_egi, inputs.proforma_gross_expenses)

    realistic_cap_rate = _safe_div(realistic_noi, asking_price)
    realistic_grm = _safe_div(asking_price, realistic_gpi)
    realistic_monthly_rent_total = _compute_realistic_monthly_rent_total(inputs)

    realistic_dscr = _compute_dscr(
        realistic_noi,
        inputs.debt_service_annual,
        inputs.loan_amount,
        inputs.interest_rate,
    )

    realistic = ScenarioMetrics(
        gross_potential_income_annual=realistic_gpi,
        effective_gross_income_annual=realistic_egi,
        gross_expenses_annual=inputs.proforma_gross_expenses,
        noi_annual=realistic_noi,
        cap_rate=realistic_cap_rate,
        grm=realistic_grm,
        monthly_rent_total=realistic_monthly_rent_total,
        dscr=realistic_dscr,
        cash_on_cash=None,  # Requires equity investment data not in ScenarioInputs
    )

    # ------------------------------------------------------------------
    # Broker current scenario
    # ------------------------------------------------------------------
    current_gpi = inputs.current_gross_potential_income
    current_noi = inputs.current_noi

    current_cap_rate = _safe_div(current_noi, asking_price)
    current_grm = _safe_div(asking_price, current_gpi)
    current_monthly_rent_total = _compute_broker_current_monthly_rent_total(inputs)

    current_dscr = _compute_dscr(
        current_noi,
        inputs.debt_service_annual,
        inputs.loan_amount,
        inputs.interest_rate,
    )

    broker_current = ScenarioMetrics(
        gross_potential_income_annual=current_gpi,
        effective_gross_income_annual=inputs.current_effective_gross_income,
        gross_expenses_annual=inputs.current_gross_expenses,
        noi_annual=current_noi,
        cap_rate=current_cap_rate,
        grm=current_grm,
        monthly_rent_total=current_monthly_rent_total,
        dscr=current_dscr,
        cash_on_cash=None,
    )

    # ------------------------------------------------------------------
    # Broker proforma scenario
    # ------------------------------------------------------------------
    proforma_gpi = inputs.proforma_gross_potential_income
    proforma_noi = inputs.proforma_noi

    proforma_cap_rate = _safe_div(proforma_noi, asking_price)
    proforma_grm = _safe_div(asking_price, proforma_gpi)
    proforma_monthly_rent_total = _compute_broker_proforma_monthly_rent_total(inputs)

    proforma_dscr = _compute_dscr(
        proforma_noi,
        inputs.debt_service_annual,
        inputs.loan_amount,
        inputs.interest_rate,
    )

    broker_proforma = ScenarioMetrics(
        gross_potential_income_annual=proforma_gpi,
        effective_gross_income_annual=inputs.proforma_effective_gross_income,
        gross_expenses_annual=inputs.proforma_gross_expenses,
        noi_annual=proforma_noi,
        cap_rate=proforma_cap_rate,
        grm=proforma_grm,
        monthly_rent_total=proforma_monthly_rent_total,
        dscr=proforma_dscr,
        cash_on_cash=None,
    )

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------
    significant_variance_flag = _compute_significant_variance_flag(
        realistic_noi, proforma_noi
    )
    realistic_cap_rate_below_proforma = _compute_realistic_cap_rate_below_proforma(
        realistic_cap_rate, proforma_cap_rate
    )

    # ------------------------------------------------------------------
    # Unit mix comparison
    # ------------------------------------------------------------------
    unit_mix_comparison = _build_unit_mix_comparison(inputs)

    return ScenarioComparison(
        broker_current=broker_current,
        broker_proforma=broker_proforma,
        realistic=realistic,
        unit_mix_comparison=unit_mix_comparison,
        significant_variance_flag=significant_variance_flag,
        realistic_cap_rate_below_proforma=realistic_cap_rate_below_proforma,
    )
