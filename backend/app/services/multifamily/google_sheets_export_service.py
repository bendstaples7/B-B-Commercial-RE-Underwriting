"""
Google Sheets export service for multifamily pro forma workbooks.

Exports a Deal to a new Google Sheets document using the same
``WORKBOOK_SHEETS`` spec as the Excel export, so the sheet structure
is identical between the two formats.

The caller supplies an OAuth token (either a raw dict of credentials or
a stored ``OAuthToken`` model instance).  The service builds a Google
Sheets API client, creates a new spreadsheet, adds one sheet per entry
in ``WORKBOOK_SHEETS``, and writes headers + data rows using the
``values.batchUpdate`` API.

Requirements: 12.5, 14.5
"""

from __future__ import annotations

import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Google Sheets API write scope
_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsExportService:
    """Exports a multifamily Deal to a new Google Sheets document.

    Reuses ``WORKBOOK_SHEETS`` from ``excel_workbook_spec`` so the sheet
    structure mirrors the Excel export exactly (Req 14.5).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_deal_to_sheets(self, deal_id: int, oauth_token: Any) -> str:
        """Export a Deal to a new Google Sheets document.

        Args:
            deal_id: Primary key of the Deal to export.
            oauth_token: Either an ``OAuthToken`` model instance (with an
                ``encrypted_refresh_token`` column) or a plain ``dict``
                containing OAuth2 credential fields (``refresh_token``,
                ``client_id``, ``client_secret``, and optionally ``token``).

        Returns:
            The shareable URL of the created Google Sheets document.

        Requirements: 12.5, 14.5
        """
        from app.models.deal import Deal
        from app.models.unit import Unit
        from app.models.rent_comp import RentComp
        from app.models.sale_comp import SaleComp
        from app.models.funding_source import FundingSource
        from app.models.deal_lender_selection import DealLenderSelection
        from app.services.multifamily.dashboard_service import DashboardService
        from app.services.multifamily.excel_workbook_spec import WORKBOOK_SHEETS

        deal = Deal.query.get(deal_id)
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        # Build the Sheets API service from the supplied token
        service = self._build_sheets_service(oauth_token)

        # Fetch computed pro forma for output sheets
        dashboard_service = DashboardService()
        pro_forma_dict = dashboard_service.get_pro_forma(deal_id)

        # Fetch ORM data for round-trippable sheets
        units = (
            Unit.query.filter_by(deal_id=deal_id)
            .order_by(Unit.unit_identifier)
            .all()
        )
        rent_comps = RentComp.query.filter_by(deal_id=deal_id).all()
        sale_comps = SaleComp.query.filter_by(deal_id=deal_id).all()
        funding_sources = FundingSource.query.filter_by(deal_id=deal_id).all()
        lender_selections = (
            DealLenderSelection.query.filter_by(deal_id=deal_id).all()
        )

        # Create a new spreadsheet with a descriptive title
        spreadsheet_title = (
            f"Multifamily Pro Forma — Deal {deal_id}"
            f" — {deal.property_address or 'Unknown Address'}"
        )
        spreadsheet_body = {"properties": {"title": spreadsheet_title}}
        spreadsheet = (
            service.spreadsheets().create(body=spreadsheet_body).execute()
        )
        spreadsheet_id: str = spreadsheet["spreadsheetId"]
        logger.info(
            "Created Google Sheets document %s for deal %s", spreadsheet_id, deal_id
        )

        # Google Sheets creates one default sheet ("Sheet1") on creation.
        # Rename it to the first spec sheet and add the remaining sheets.
        default_sheet_id: int = spreadsheet["sheets"][0]["properties"]["sheetId"]

        # Build batch requests to rename/add sheets
        structure_requests: list[dict] = []

        for idx, sheet_spec in enumerate(WORKBOOK_SHEETS):
            if idx == 0:
                # Rename the default sheet to the first spec sheet name
                structure_requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": default_sheet_id,
                                "title": sheet_spec.name,
                            },
                            "fields": "title",
                        }
                    }
                )
            else:
                # Add a new sheet for each subsequent spec sheet
                structure_requests.append(
                    {
                        "addSheet": {
                            "properties": {
                                "title": sheet_spec.name,
                                "index": idx,
                            }
                        }
                    }
                )

        # Execute the sheet-structure batch update so all sheets exist
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": structure_requests},
        ).execute()

        # Write data to each sheet via values.batchUpdate
        value_data: list[dict] = []

        for sheet_spec in WORKBOOK_SHEETS:
            rows: list[list[Any]] = []

            # Header row
            rows.append([col.header for col in sheet_spec.columns])

            # Data rows — dispatch by sheet name
            if sheet_spec.name == "S00a_Summary_ScenarioA":
                rows.extend(self._summary_rows(pro_forma_dict, "a"))
            elif sheet_spec.name == "S00b_Summary_ScenarioB":
                rows.extend(self._summary_rows(pro_forma_dict, "b"))
            elif sheet_spec.name == "S01_RentRoll_InPlace":
                rows.extend(self._rent_roll_rows(sheet_spec, units))
            elif sheet_spec.name == "S02_MarketRents_Comps":
                rows.extend(self._rent_comps_rows(sheet_spec, rent_comps))
            elif sheet_spec.name == "S03_SaleComps_CapRates":
                rows.extend(self._sale_comps_rows(sheet_spec, sale_comps))
            elif sheet_spec.name == "S04_Rehab_Timing":
                rows.extend(self._rehab_timing_rows(sheet_spec, units))
            elif sheet_spec.name == "S05_ProForma_24mo":
                rows.extend(self._pro_forma_schedule_rows(sheet_spec, pro_forma_dict))
            elif sheet_spec.name == "S06_Valuation":
                rows.extend(self._valuation_rows(sheet_spec, pro_forma_dict))
            elif sheet_spec.name == "S07_Lender_Assumptions":
                rows.extend(self._lender_assumptions_rows(sheet_spec, lender_selections))
            elif sheet_spec.name == "Funding_Sources":
                rows.extend(self._funding_sources_rows(sheet_spec, funding_sources))

            if rows:
                value_data.append(
                    {
                        "range": f"'{sheet_spec.name}'!A1",
                        "values": rows,
                    }
                )

        if value_data:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": value_data,
                },
            ).execute()

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        logger.info("Deal %s exported to Google Sheets: %s", deal_id, url)
        return url

    # ------------------------------------------------------------------
    # OAuth / API client helpers
    # ------------------------------------------------------------------

    def _build_sheets_service(self, oauth_token: Any):
        """Build a Google Sheets API service from an OAuth token."""
        from googleapiclient.discovery import build

        creds = self._resolve_credentials(oauth_token)
        return build("sheets", "v4", credentials=creds)

    def _resolve_credentials(self, oauth_token: Any) -> Any:
        """Return a ``google.oauth2.credentials.Credentials`` object.

        Handles two input shapes:
        - ``OAuthToken`` model instance — decrypts the stored refresh token.
        - ``dict`` — uses the dict fields directly (``refresh_token``,
          ``client_id``, ``client_secret``, optionally ``token``).
        """
        from google.oauth2.credentials import Credentials

        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        token_uri = "https://oauth2.googleapis.com/token"

        # OAuthToken model instance (has encrypted_refresh_token column)
        if hasattr(oauth_token, "encrypted_refresh_token"):
            from app.services.google_sheets_importer import _decrypt_token

            refresh_token = _decrypt_token(oauth_token.encrypted_refresh_token)
            return Credentials(
                token=None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri=token_uri,
                scopes=_SHEETS_SCOPES,
            )

        # Plain credentials dict
        if isinstance(oauth_token, dict):
            return Credentials(
                token=oauth_token.get("token"),
                refresh_token=oauth_token.get("refresh_token"),
                client_id=oauth_token.get("client_id", client_id),
                client_secret=oauth_token.get("client_secret", client_secret),
                token_uri=oauth_token.get("token_uri", token_uri),
                scopes=oauth_token.get("scopes", _SHEETS_SCOPES),
            )

        raise TypeError(
            f"oauth_token must be an OAuthToken model instance or a credentials dict, "
            f"got {type(oauth_token).__name__}"
        )

    # ------------------------------------------------------------------
    # Cell serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _cell(value: Any, kind: str) -> Any:
        """Convert a Python value to a Sheets-safe cell value.

        Google Sheets accepts strings, numbers, booleans, and None (empty).
        Dates are serialized as ISO-8601 strings so they display correctly.
        """
        if value is None:
            return ""
        if kind in ("decimal", "rate"):
            if isinstance(value, Decimal):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(Decimal(value))
                except Exception:
                    return value
            try:
                return float(value)
            except (TypeError, ValueError):
                return ""
        if kind == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return ""
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        if kind == "date":
            if isinstance(value, date):
                return value.isoformat()
            return str(value) if value else ""
        # str
        return str(value) if value is not None else ""

    def _model_row(self, sheet_spec: Any, data: dict) -> list[Any]:
        """Build a single data row list from a dict using the sheet spec column order."""
        return [
            self._cell(data.get(col.attr), col.kind)
            for col in sheet_spec.columns
        ]

    # ------------------------------------------------------------------
    # Per-sheet row builders
    # ------------------------------------------------------------------

    def _summary_rows(self, pro_forma_dict: dict, scenario_suffix: str) -> list[list[Any]]:
        """Build metric/value rows for a summary sheet (S00a or S00b)."""
        summary = pro_forma_dict.get("summary", {})
        sources_and_uses = pro_forma_dict.get(f"sources_and_uses_{scenario_suffix}")
        s = scenario_suffix.upper()

        metrics: list[tuple[str, Any]] = [
            ("In_Place_NOI", summary.get("in_place_noi")),
            ("Stabilized_NOI", summary.get("stabilized_noi")),
            (f"In_Place_DSCR_{s}", summary.get(f"in_place_dscr_{scenario_suffix}")),
            (f"Stabilized_DSCR_{s}", summary.get(f"stabilized_dscr_{scenario_suffix}")),
            (f"Cash_On_Cash_{s}", summary.get(f"cash_on_cash_{scenario_suffix}")),
        ]
        if sources_and_uses:
            metrics.extend(
                [
                    ("Loan_Amount", sources_and_uses.get("loan_amount")),
                    ("Initial_Cash_Investment", sources_and_uses.get("initial_cash_investment")),
                    ("Total_Uses", sources_and_uses.get("total_uses")),
                    ("Total_Sources", sources_and_uses.get("total_sources")),
                ]
            )

        rows = []
        for metric_name, value in metrics:
            cell_val: Any = ""
            if value is not None:
                try:
                    cell_val = float(Decimal(str(value)))
                except Exception:
                    cell_val = value
            rows.append([metric_name, cell_val])
        return rows

    def _rent_roll_rows(self, sheet_spec: Any, units: list) -> list[list[Any]]:
        rows = []
        for unit in units:
            rent_entry = unit.rent_roll_entry
            data = {
                "unit_identifier": unit.unit_identifier,
                "unit_type": unit.unit_type,
                "beds": unit.beds,
                "baths": unit.baths,
                "sqft": unit.sqft,
                "occupancy_status": unit.occupancy_status,
                "current_rent": rent_entry.current_rent if rent_entry else None,
                "lease_start_date": rent_entry.lease_start_date if rent_entry else None,
                "lease_end_date": rent_entry.lease_end_date if rent_entry else None,
                "notes": rent_entry.notes if rent_entry else None,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows

    def _rent_comps_rows(self, sheet_spec: Any, rent_comps: list) -> list[list[Any]]:
        rows = []
        for comp in rent_comps:
            data = {
                "address": comp.address,
                "neighborhood": comp.neighborhood,
                "unit_type": comp.unit_type,
                "observed_rent": comp.observed_rent,
                "sqft": comp.sqft,
                "rent_per_sqft": comp.rent_per_sqft,
                "observation_date": comp.observation_date,
                "source_url": comp.source_url,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows

    def _sale_comps_rows(self, sheet_spec: Any, sale_comps: list) -> list[list[Any]]:
        rows = []
        for comp in sale_comps:
            data = {
                "address": comp.address,
                "unit_count": comp.unit_count,
                "status": comp.status,
                "sale_price": comp.sale_price,
                "close_date": comp.close_date,
                "observed_cap_rate": comp.observed_cap_rate,
                "observed_ppu": comp.observed_ppu,
                "distance_miles": comp.distance_miles,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows

    def _rehab_timing_rows(self, sheet_spec: Any, units: list) -> list[list[Any]]:
        rows = []
        for unit in units:
            rehab = unit.rehab_plan_entry
            if rehab is None:
                continue
            data = {
                "unit_id": unit.unit_identifier,
                "renovate_flag": rehab.renovate_flag,
                "current_rent": rehab.current_rent,
                "suggested_post_reno_rent": rehab.suggested_post_reno_rent,
                "underwritten_post_reno_rent": rehab.underwritten_post_reno_rent,
                "rehab_start_month": rehab.rehab_start_month,
                "downtime_months": rehab.downtime_months,
                "rehab_budget": rehab.rehab_budget,
                "scope_notes": rehab.scope_notes,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows

    def _pro_forma_schedule_rows(
        self, sheet_spec: Any, pro_forma_dict: dict
    ) -> list[list[Any]]:
        rows = []
        for month_row in pro_forma_dict.get("monthly_schedule", []):
            rows.append(self._model_row(sheet_spec, month_row))
        return rows

    def _valuation_rows(
        self, sheet_spec: Any, pro_forma_dict: dict
    ) -> list[list[Any]]:
        valuation = pro_forma_dict.get("valuation")
        if not valuation:
            return []

        metric_rows = [
            {
                "metric": "Valuation_At_Cap_Rate",
                "min_value": valuation.get("valuation_at_cap_rate_min"),
                "median_value": valuation.get("valuation_at_cap_rate_median"),
                "average_value": valuation.get("valuation_at_cap_rate_average"),
                "max_value": valuation.get("valuation_at_cap_rate_max"),
            },
            {
                "metric": "Valuation_At_PPU",
                "min_value": valuation.get("valuation_at_ppu_min"),
                "median_value": valuation.get("valuation_at_ppu_median"),
                "average_value": valuation.get("valuation_at_ppu_average"),
                "max_value": valuation.get("valuation_at_ppu_max"),
            },
            {
                "metric": "Custom_Cap_Rate_Valuation",
                "min_value": valuation.get("valuation_at_custom_cap_rate"),
                "median_value": None,
                "average_value": None,
                "max_value": None,
            },
            {
                "metric": "Price_To_Rent_Ratio",
                "min_value": valuation.get("price_to_rent_ratio"),
                "median_value": None,
                "average_value": None,
                "max_value": None,
            },
        ]
        return [self._model_row(sheet_spec, row) for row in metric_rows]

    def _lender_assumptions_rows(
        self, sheet_spec: Any, lender_selections: list
    ) -> list[list[Any]]:
        rows = []
        for selection in lender_selections:
            profile = selection.lender_profile
            data = {
                "scenario": selection.scenario,
                "is_primary": selection.is_primary,
                "company": profile.company,
                "lender_type": profile.lender_type,
                "origination_fee_rate": profile.origination_fee_rate,
                "ltv_total_cost": profile.ltv_total_cost,
                "construction_rate": profile.construction_rate,
                "construction_io_months": profile.construction_io_months,
                "construction_term_months": profile.construction_term_months,
                "perm_rate": profile.perm_rate,
                "perm_amort_years": profile.perm_amort_years,
                "min_interest_or_yield": profile.min_interest_or_yield,
                "max_purchase_ltv": profile.max_purchase_ltv,
                "treasury_5y_rate": profile.treasury_5y_rate,
                "spread_bps": profile.spread_bps,
                "term_years": profile.term_years,
                "amort_years": profile.amort_years,
                "prepay_penalty_description": profile.prepay_penalty_description,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows

    def _funding_sources_rows(
        self, sheet_spec: Any, funding_sources: list
    ) -> list[list[Any]]:
        rows = []
        for source in funding_sources:
            data = {
                "source_type": source.source_type,
                "total_available": source.total_available,
                "interest_rate": source.interest_rate,
                "origination_fee_rate": source.origination_fee_rate,
            }
            rows.append(self._model_row(sheet_spec, data))
        return rows
