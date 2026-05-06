"""
Pro forma constants for the multifamily underwriting engine.

Centralises the 24-month horizon, stabilized-period range, Decimal
quantization policy, scenario identifiers, and missing-input codes so that
no magic numbers or strings are scattered across the codebase.

Requirements: 8.1-8.14
"""

from decimal import Decimal
from enum import Enum

# ---------------------------------------------------------------------------
# Horizon
# ---------------------------------------------------------------------------

HORIZON_MONTHS: int = 24
"""The fixed pro forma projection horizon in months."""

STABILIZED_MONTHS: range = range(13, 25)
"""Months 13 through 24 (inclusive) — the stabilized operating period."""

# ---------------------------------------------------------------------------
# Decimal quantization helpers
# ---------------------------------------------------------------------------

MONEY_Q: Decimal = Decimal("0.01")
"""Quantize to 2 decimal places for monetary values."""

RATE_Q: Decimal = Decimal("0.000001")
"""Quantize to 6 decimal places for rate values."""


def quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to 2 decimal places (monetary precision)."""
    return value.quantize(MONEY_Q)


def quantize_rate(value: Decimal) -> Decimal:
    """Round a Decimal to 6 decimal places (rate precision)."""
    return value.quantize(RATE_Q)


# ---------------------------------------------------------------------------
# Scenario enum
# ---------------------------------------------------------------------------

class Scenario(str, Enum):
    """Debt scenario identifier.

    A = Construction-to-Perm (single lender funds purchase + renovation)
    B = Self-Funded Renovation (lender funds purchase only; reno from funding sources)
    """

    A = "A"
    B = "B"


# ---------------------------------------------------------------------------
# Missing-input codes (Req 8.14)
# ---------------------------------------------------------------------------

RENT_ROLL_INCOMPLETE: str = "RENT_ROLL_INCOMPLETE"
"""Fewer rent roll entries than the Deal's unit_count."""

REHAB_PLAN_MISSING: str = "REHAB_PLAN_MISSING"
"""A Unit with renovate_flag=True lacks a rehab_start_month."""

OPEX_ASSUMPTIONS_MISSING: str = "OPEX_ASSUMPTIONS_MISSING"
"""One or more of the seven annual OpEx inputs is NULL."""

PRIMARY_LENDER_MISSING_A: str = "PRIMARY_LENDER_MISSING_A"
"""No primary lender attached for Scenario A (Construction-to-Perm)."""

PRIMARY_LENDER_MISSING_B: str = "PRIMARY_LENDER_MISSING_B"
"""No primary lender attached for Scenario B (Self-Funded Renovation)."""

FUNDING_INSUFFICIENT: str = "FUNDING_INSUFFICIENT"
"""Cumulative funding sources < required equity (soft warning, non-blocking)."""
