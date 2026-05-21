"""
Frozen dataclasses for the Commercial OM PDF Intake pipeline.

All monetary and rate fields use ``Decimal`` to avoid floating-point
rounding errors in financial arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Income / unit-mix primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OtherIncomeItem:
    """A single non-apartment income line item extracted from the OM.

    Requirements: 3.2 (income line items)
    """

    label: str
    annual_amount: Decimal


@dataclass(frozen=True)
class UnitMixRow:
    """One row in the OM's unit mix table.

    Requirements: 3.2 (Unit_Mix_Rows), 4.2 (market rent storage), 5.7
    """

    unit_type_label: str
    unit_count: int
    sqft: Decimal
    current_avg_rent: Decimal | None
    proforma_rent: Decimal | None
    market_rent_estimate: Decimal | None
    market_rent_low: Decimal | None
    market_rent_high: Decimal | None


# ---------------------------------------------------------------------------
# Scenario computation inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioInputs:
    """All inputs required by ``compute_scenarios`` to produce a
    ``ScenarioComparison``.

    Requirements: 4.3–4.8, 5.1–5.9
    """

    unit_mix: tuple[UnitMixRow, ...]
    proforma_vacancy_rate: Decimal
    proforma_gross_expenses: Decimal | None
    other_income_items: tuple[OtherIncomeItem, ...]

    # Asking / financing
    asking_price: Decimal | None
    loan_amount: Decimal | None
    interest_rate: Decimal | None
    amortization_years: int | None
    debt_service_annual: Decimal | None

    # Broker-stated current aggregates
    current_gross_potential_income: Decimal | None
    current_effective_gross_income: Decimal | None
    current_gross_expenses: Decimal | None
    current_noi: Decimal | None
    current_vacancy_rate: Decimal | None

    # Broker-stated pro-forma aggregates
    proforma_gross_potential_income: Decimal | None
    proforma_effective_gross_income: Decimal | None
    proforma_noi: Decimal | None


@dataclass(frozen=True)
class ScenarioMetrics:
    """Computed financial metrics for a single scenario (broker current,
    broker pro forma, or realistic).

    Requirements: 5.2, 5.3
    """

    gross_potential_income_annual: Decimal | None
    effective_gross_income_annual: Decimal | None
    gross_expenses_annual: Decimal | None
    noi_annual: Decimal | None
    cap_rate: Decimal | None
    grm: Decimal | None
    monthly_rent_total: Decimal | None
    dscr: Decimal | None
    cash_on_cash: Decimal | None


@dataclass(frozen=True)
class UnitMixComparisonRow:
    """Per-unit-type row in the ``ScenarioComparison.unit_mix_comparison``
    array, combining broker and market rent data for side-by-side display.

    Requirements: 5.7
    """

    unit_type_label: str
    unit_count: int
    sqft: Decimal
    current_avg_rent: Decimal | None
    proforma_rent: Decimal | None
    market_rent_estimate: Decimal | None
    market_rent_low: Decimal | None
    market_rent_high: Decimal | None


@dataclass(frozen=True)
class ScenarioComparison:
    """The three-scenario comparison object returned by ``compute_scenarios``
    and stored on the ``OMIntakeJob``.

    Requirements: 5.1, 5.4, 5.5, 5.6, 5.7
    """

    broker_current: ScenarioMetrics
    broker_proforma: ScenarioMetrics
    realistic: ScenarioMetrics
    unit_mix_comparison: tuple[UnitMixComparisonRow, ...]
    significant_variance_flag: bool | None
    realistic_cap_rate_below_proforma: bool | None


# ---------------------------------------------------------------------------
# PDF extraction result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PDFExtractionResult:
    """Raw output from ``PDFParserService.extract``.

    ``tables`` is a list of tables; each table is a list of rows; each row
    is a list of cell strings.

    Requirements: 2.1, 2.2, 2.7
    """

    raw_text: str
    tables: list  # list[list[list[str]]]
    table_extraction_warning: str | None


# ---------------------------------------------------------------------------
# Extracted OM data (Gemini response)
# ---------------------------------------------------------------------------


@dataclass
class ExtractedOMData:
    """Structured data produced by ``GeminiOMExtractorService.extract``.

    Every field is stored as a dict ``{"value": <value_or_null>,
    "confidence": float}`` where ``confidence`` is in ``[0.0, 1.0]``.

    This class is intentionally *not* frozen because the ``OMIntakeService``
    may patch individual fields after market rent research completes.

    Requirements: 3.2, 3.3, 3.4
    """

    # ------------------------------------------------------------------
    # Property fields
    # ------------------------------------------------------------------
    property_address: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    property_city: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    property_state: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    property_zip: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    neighborhood: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    asking_price: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    price_per_unit: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    price_per_sqft: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    building_sqft: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    year_built: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    lot_size: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    zoning: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    unit_count: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})

    # ------------------------------------------------------------------
    # Broker_Current metrics
    # ------------------------------------------------------------------
    current_noi: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_cap_rate: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_grm: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_gross_potential_income: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_effective_gross_income: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_vacancy_rate: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_gross_expenses: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})

    # ------------------------------------------------------------------
    # Broker_Pro_Forma metrics
    # ------------------------------------------------------------------
    proforma_noi: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_cap_rate: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_grm: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_gross_potential_income: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_effective_gross_income: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_vacancy_rate: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_gross_expenses: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})

    # ------------------------------------------------------------------
    # Unit mix (list of dicts with per-field confidence scores)
    # Each item mirrors UnitMixRow fields but stored as
    # {"unit_type_label": {"value": ..., "confidence": ...}, ...}
    # ------------------------------------------------------------------
    unit_mix: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Income line items
    # ------------------------------------------------------------------
    apartment_income_current: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    apartment_income_proforma: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    # list of {"label": {"value": ..., "confidence": ...},
    #          "annual_amount": {"value": ..., "confidence": ...}}
    other_income_items: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Expense line items
    # list of {"label": ..., "current_annual_amount": ...,
    #          "proforma_annual_amount": ...} — each sub-field wrapped in
    # {"value": ..., "confidence": ...}
    # ------------------------------------------------------------------
    expense_items: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Financing fields
    # ------------------------------------------------------------------
    down_payment_pct: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    loan_amount: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    interest_rate: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    amortization_years: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    debt_service_annual: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_dscr: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_dscr: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    current_cash_on_cash: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    proforma_cash_on_cash: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})

    # ------------------------------------------------------------------
    # Broker / listing fields
    # ------------------------------------------------------------------
    listing_broker_name: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    listing_broker_company: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    listing_broker_phone: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
    listing_broker_email: dict[str, Any] = field(default_factory=lambda: {"value": None, "confidence": 0.0})
