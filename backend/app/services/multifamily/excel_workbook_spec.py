"""
Excel workbook specification — single source of truth for export and import.

Declares the sheet names, column order, column types, and round-trippability
for the 10-sheet multifamily pro forma workbook. Both the ExcelExportService
and ExcelImportService read this module so that the workbook structure is
defined in exactly one place.

Requirements: 12.1, 12.2, 13.1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """Specification for a single column in a workbook sheet.

    Attributes:
        header: The column header text in the Excel sheet.
        attr: The dataclass field or model attribute name this column maps to.
        kind: The data type for serialization/deserialization.
        required: Whether the column must be present for import (default True).
    """

    header: str
    attr: str
    kind: Literal["str", "int", "decimal", "date", "bool", "rate"]
    required: bool = True


@dataclass(frozen=True)
class SheetSpec:
    """Specification for a single sheet in the workbook.

    Attributes:
        name: Exact sheet name (e.g. 'S01_RentRoll_InPlace').
        entity: Logical entity this sheet represents (e.g. 'Unit+RentRollEntry').
        columns: Ordered tuple of ColumnSpec defining the sheet's columns.
        round_trippable: True if this sheet carries input data that can be
            exported and re-imported without loss. False for computed-output sheets.
    """

    name: str
    entity: str
    columns: tuple[ColumnSpec, ...]
    round_trippable: bool


# ---------------------------------------------------------------------------
# Sheet definitions
# ---------------------------------------------------------------------------

# S00a — Summary Scenario A (computed output, not round-trippable)
_S00A_COLUMNS = (
    ColumnSpec("Metric", "metric", "str"),
    ColumnSpec("Value", "value", "decimal"),
)

# S00b — Summary Scenario B (computed output, not round-trippable)
_S00B_COLUMNS = (
    ColumnSpec("Metric", "metric", "str"),
    ColumnSpec("Value", "value", "decimal"),
)

# S01 — Rent Roll In-Place (round-trippable)
_S01_COLUMNS = (
    ColumnSpec("Unit_ID", "unit_identifier", "str"),
    ColumnSpec("Unit_Type", "unit_type", "str"),
    ColumnSpec("Beds", "beds", "int"),
    ColumnSpec("Baths", "baths", "decimal"),
    ColumnSpec("SqFt", "sqft", "int"),
    ColumnSpec("Occupancy_Status", "occupancy_status", "str"),
    ColumnSpec("Current_Rent", "current_rent", "decimal"),
    ColumnSpec("Lease_Start_Date", "lease_start_date", "date", required=False),
    ColumnSpec("Lease_End_Date", "lease_end_date", "date", required=False),
    ColumnSpec("Notes", "notes", "str", required=False),
)

# S02 — Market Rents & Comps (round-trippable)
_S02_COLUMNS = (
    ColumnSpec("Address", "address", "str"),
    ColumnSpec("Neighborhood", "neighborhood", "str", required=False),
    ColumnSpec("Unit_Type", "unit_type", "str"),
    ColumnSpec("Observed_Rent", "observed_rent", "decimal"),
    ColumnSpec("SqFt", "sqft", "int"),
    ColumnSpec("Rent_Per_SqFt", "rent_per_sqft", "decimal"),
    ColumnSpec("Observation_Date", "observation_date", "date", required=False),
    ColumnSpec("Source_URL", "source_url", "str", required=False),
)

# S03 — Sale Comps & Cap Rates (round-trippable)
_S03_COLUMNS = (
    ColumnSpec("Address", "address", "str"),
    ColumnSpec("Unit_Count", "unit_count", "int"),
    ColumnSpec("Status", "status", "str", required=False),
    ColumnSpec("Sale_Price", "sale_price", "decimal"),
    ColumnSpec("Close_Date", "close_date", "date", required=False),
    ColumnSpec("Observed_Cap_Rate", "observed_cap_rate", "rate"),
    ColumnSpec("Observed_PPU", "observed_ppu", "decimal"),
    ColumnSpec("Distance_Miles", "distance_miles", "decimal", required=False),
)

# S04 — Rehab Timing (round-trippable)
_S04_COLUMNS = (
    ColumnSpec("Unit_ID", "unit_id", "str"),
    ColumnSpec("Renovate_Flag", "renovate_flag", "bool"),
    ColumnSpec("Current_Rent", "current_rent", "decimal"),
    ColumnSpec("Suggested_Post_Reno_Rent", "suggested_post_reno_rent", "decimal", required=False),
    ColumnSpec("Underwritten_Post_Reno_Rent", "underwritten_post_reno_rent", "decimal", required=False),
    ColumnSpec("Rehab_Start_Month", "rehab_start_month", "int", required=False),
    ColumnSpec("Downtime_Months", "downtime_months", "int", required=False),
    ColumnSpec("Rehab_Budget", "rehab_budget", "decimal", required=False),
    ColumnSpec("Scope_Notes", "scope_notes", "str", required=False),
)

# S05 — Pro Forma 24-month (computed output, not round-trippable)
_S05_COLUMNS = (
    ColumnSpec("Month", "month", "int"),
    ColumnSpec("GSR", "gsr", "decimal"),
    ColumnSpec("Vacancy_Loss", "vacancy_loss", "decimal"),
    ColumnSpec("Other_Income", "other_income", "decimal"),
    ColumnSpec("EGI", "egi", "decimal"),
    ColumnSpec("OpEx_Total", "opex_total", "decimal"),
    ColumnSpec("NOI", "noi", "decimal"),
    ColumnSpec("Replacement_Reserves", "replacement_reserves", "decimal"),
    ColumnSpec("Net_Cash_Flow", "net_cash_flow", "decimal"),
    ColumnSpec("Debt_Service_A", "debt_service_a", "decimal", required=False),
    ColumnSpec("Debt_Service_B", "debt_service_b", "decimal", required=False),
    ColumnSpec("Cash_Flow_After_Debt_A", "cash_flow_after_debt_a", "decimal", required=False),
    ColumnSpec("Cash_Flow_After_Debt_B", "cash_flow_after_debt_b", "decimal", required=False),
    ColumnSpec("CapEx_Spend", "capex_spend", "decimal"),
    ColumnSpec("Cash_Flow_After_CapEx_A", "cash_flow_after_capex_a", "decimal", required=False),
    ColumnSpec("Cash_Flow_After_CapEx_B", "cash_flow_after_capex_b", "decimal", required=False),
)

# S06 — Valuation (computed output, not round-trippable)
_S06_COLUMNS = (
    ColumnSpec("Metric", "metric", "str"),
    ColumnSpec("Min", "min_value", "decimal", required=False),
    ColumnSpec("Median", "median_value", "decimal", required=False),
    ColumnSpec("Average", "average_value", "decimal", required=False),
    ColumnSpec("Max", "max_value", "decimal", required=False),
)

# S07 — Lender Assumptions (round-trippable)
_S07_COLUMNS = (
    ColumnSpec("Scenario", "scenario", "str"),
    ColumnSpec("Is_Primary", "is_primary", "bool"),
    ColumnSpec("Company", "company", "str"),
    ColumnSpec("Lender_Type", "lender_type", "str"),
    ColumnSpec("Origination_Fee_Rate", "origination_fee_rate", "rate"),
    ColumnSpec("LTV_Total_Cost", "ltv_total_cost", "rate", required=False),
    ColumnSpec("Construction_Rate", "construction_rate", "rate", required=False),
    ColumnSpec("Construction_IO_Months", "construction_io_months", "int", required=False),
    ColumnSpec("Construction_Term_Months", "construction_term_months", "int", required=False),
    ColumnSpec("Perm_Rate", "perm_rate", "rate", required=False),
    ColumnSpec("Perm_Amort_Years", "perm_amort_years", "int", required=False),
    ColumnSpec("Min_Interest_Or_Yield", "min_interest_or_yield", "decimal", required=False),
    ColumnSpec("Max_Purchase_LTV", "max_purchase_ltv", "rate", required=False),
    ColumnSpec("Treasury_5Y_Rate", "treasury_5y_rate", "rate", required=False),
    ColumnSpec("Spread_Bps", "spread_bps", "int", required=False),
    ColumnSpec("Term_Years", "term_years", "int", required=False),
    ColumnSpec("Amort_Years", "amort_years", "int", required=False),
    ColumnSpec("Prepay_Penalty_Description", "prepay_penalty_description", "str", required=False),
)

# Funding Sources (round-trippable)
_FUNDING_COLUMNS = (
    ColumnSpec("Source_Type", "source_type", "str"),
    ColumnSpec("Total_Available", "total_available", "decimal"),
    ColumnSpec("Interest_Rate", "interest_rate", "rate"),
    ColumnSpec("Origination_Fee_Rate", "origination_fee_rate", "rate"),
)


# ---------------------------------------------------------------------------
# Master workbook spec
# ---------------------------------------------------------------------------

WORKBOOK_SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec("S00a_Summary_ScenarioA", "Summary_A", _S00A_COLUMNS, round_trippable=False),
    SheetSpec("S00b_Summary_ScenarioB", "Summary_B", _S00B_COLUMNS, round_trippable=False),
    SheetSpec("S01_RentRoll_InPlace", "Unit+RentRollEntry", _S01_COLUMNS, round_trippable=True),
    SheetSpec("S02_MarketRents_Comps", "MarketRent+RentComp", _S02_COLUMNS, round_trippable=True),
    SheetSpec("S03_SaleComps_CapRates", "SaleComp", _S03_COLUMNS, round_trippable=True),
    SheetSpec("S04_Rehab_Timing", "RehabPlan", _S04_COLUMNS, round_trippable=True),
    SheetSpec("S05_ProForma_24mo", "Monthly", _S05_COLUMNS, round_trippable=False),
    SheetSpec("S06_Valuation", "Valuation", _S06_COLUMNS, round_trippable=False),
    SheetSpec("S07_Lender_Assumptions", "DealLenders+Profile", _S07_COLUMNS, round_trippable=True),
    SheetSpec("Funding_Sources", "FundingSource", _FUNDING_COLUMNS, round_trippable=True),
)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def get_sheet_by_name(name: str) -> SheetSpec | None:
    """Look up a SheetSpec by its exact sheet name."""
    for sheet in WORKBOOK_SHEETS:
        if sheet.name == name:
            return sheet
    return None


def get_round_trippable_sheets() -> tuple[SheetSpec, ...]:
    """Return only the sheets that participate in the round-trip property."""
    return tuple(s for s in WORKBOOK_SHEETS if s.round_trippable)


def get_required_columns(sheet: SheetSpec) -> tuple[ColumnSpec, ...]:
    """Return only the required columns for a given sheet."""
    return tuple(c for c in sheet.columns if c.required)
