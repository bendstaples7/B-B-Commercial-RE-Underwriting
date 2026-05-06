"""
Dashboard service for multifamily underwriting.

Composes the Summary Dashboard by reading or recomputing the cached
ProFormaResult, then assembling per-scenario summary fields for
side-by-side comparison.

The service implements a read-through cache:
  1. Build the current DealInputs snapshot.
  2. Compute the inputs_hash.
  3. If a cached ProFormaResult exists with a matching hash, return it.
  4. Otherwise, call compute_pro_forma, persist the result, and return it.

Requirements: 11.1, 11.2, 15.1, 15.2, 15.4
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from app import db
from app.models.pro_forma_result import ProFormaResult
from app.services.multifamily.deal_service import DealService
from app.services.multifamily.inputs_hash import compute_inputs_hash
from app.services.multifamily.pro_forma_engine import compute_pro_forma
from app.services.multifamily.valuation_engine import (
    SaleCompRollup,
    compute_valuation,
)
from app.services.multifamily.sale_comp_service import SaleCompService

logger = logging.getLogger(__name__)


class DashboardService:
    """Service for composing the multifamily Summary Dashboard.

    Provides a read-through cache over the ProFormaEngine: on cache hit
    (inputs_hash match) returns the stored result; on miss, recomputes,
    persists, and returns.

    The Dashboard response includes per-scenario summary fields (Req 11.1)
    and propagates missing_inputs as null-valued fields (Req 11.2).
    """

    def get_dashboard(self, deal_id: int) -> dict[str, Any]:
        """Get the full Dashboard for a Deal.

        Reads the cached ProFormaResult if the inputs_hash matches the
        current state of the Deal. Otherwise recomputes, upserts the cache
        row, and returns the freshly-composed Dashboard.

        Args:
            deal_id: The Deal to compute the dashboard for.

        Returns:
            Dict with per-scenario summary, valuation, sources_and_uses,
            missing_inputs, and warnings.

        Requirements: 11.1, 11.2, 15.1, 15.2, 15.4
        """
        deal_service = DealService()

        # Build the current inputs snapshot
        deal_inputs = deal_service.build_inputs_snapshot(deal_id)

        # Compute the current inputs hash
        current_hash = compute_inputs_hash(deal_inputs)

        # Check for cached result (Req 15.2)
        cached = ProFormaResult.query.filter_by(deal_id=deal_id).first()

        if cached is not None and cached.inputs_hash == current_hash:
            logger.info(
                "Dashboard cache hit for deal_id=%d, hash=%s",
                deal_id,
                current_hash[:8],
            )
            computation_dict = cached.result_json
        else:
            # Cache miss — recompute (Req 15.4)
            logger.info(
                "Dashboard cache miss for deal_id=%d, recomputing (hash=%s)",
                deal_id,
                current_hash[:8],
            )
            computation = compute_pro_forma(deal_inputs)
            computation_dict = computation.to_canonical_dict()

            # Upsert the cache row (Req 15.1)
            if cached is not None:
                cached.inputs_hash = current_hash
                cached.computed_at = datetime.utcnow()
                cached.result_json = computation_dict
            else:
                cached = ProFormaResult(
                    deal_id=deal_id,
                    inputs_hash=current_hash,
                    computed_at=datetime.utcnow(),
                    result_json=computation_dict,
                )
                db.session.add(cached)

            db.session.flush()

        # Compose the Dashboard response from the computation dict
        return self._compose_dashboard(deal_id, deal_inputs, computation_dict)

    def get_pro_forma(self, deal_id: int) -> dict[str, Any]:
        """Get the full ProFormaComputation result (cached or recomputed).

        Similar to get_dashboard but returns the raw computation result
        rather than the composed dashboard view.

        Args:
            deal_id: The Deal to get the pro forma for.

        Returns:
            The full ProFormaComputation as a canonical dict.
        """
        deal_service = DealService()
        deal_inputs = deal_service.build_inputs_snapshot(deal_id)
        current_hash = compute_inputs_hash(deal_inputs)

        cached = ProFormaResult.query.filter_by(deal_id=deal_id).first()

        if cached is not None and cached.inputs_hash == current_hash:
            logger.info(
                "Pro forma cache hit for deal_id=%d, hash=%s",
                deal_id,
                current_hash[:8],
            )
            return cached.result_json
        else:
            logger.info(
                "Pro forma cache miss for deal_id=%d, recomputing (hash=%s)",
                deal_id,
                current_hash[:8],
            )
            computation = compute_pro_forma(deal_inputs)
            computation_dict = computation.to_canonical_dict()

            if cached is not None:
                cached.inputs_hash = current_hash
                cached.computed_at = datetime.utcnow()
                cached.result_json = computation_dict
            else:
                cached = ProFormaResult(
                    deal_id=deal_id,
                    inputs_hash=current_hash,
                    computed_at=datetime.utcnow(),
                    result_json=computation_dict,
                )
                db.session.add(cached)

            db.session.flush()
            return computation_dict

    def force_recompute(self, deal_id: int) -> dict[str, Any]:
        """Force recompute the pro forma, ignoring any cached result.

        Args:
            deal_id: The Deal to recompute.

        Returns:
            The freshly-computed ProFormaComputation as a canonical dict.
        """
        deal_service = DealService()
        deal_inputs = deal_service.build_inputs_snapshot(deal_id)
        current_hash = compute_inputs_hash(deal_inputs)

        computation = compute_pro_forma(deal_inputs)
        computation_dict = computation.to_canonical_dict()

        # Upsert the cache row
        cached = ProFormaResult.query.filter_by(deal_id=deal_id).first()
        if cached is not None:
            cached.inputs_hash = current_hash
            cached.computed_at = datetime.utcnow()
            cached.result_json = computation_dict
        else:
            cached = ProFormaResult(
                deal_id=deal_id,
                inputs_hash=current_hash,
                computed_at=datetime.utcnow(),
                result_json=computation_dict,
            )
            db.session.add(cached)

        db.session.flush()

        logger.info(
            "Pro forma force-recomputed for deal_id=%d, hash=%s",
            deal_id,
            current_hash[:8],
        )
        return computation_dict

    def get_valuation(self, deal_id: int) -> dict[str, Any]:
        """Get the valuation for a Deal.

        Uses the cached/recomputed pro forma to extract stabilized_noi,
        then runs the valuation engine with sale comp rollup data.

        Args:
            deal_id: The Deal to get valuation for.

        Returns:
            Valuation result as a canonical dict.
        """
        deal_service = DealService()
        deal_inputs = deal_service.build_inputs_snapshot(deal_id)

        # Get the pro forma result (cached or fresh)
        pro_forma_dict = self.get_pro_forma(deal_id)

        # Extract stabilized_noi from the summary
        summary = pro_forma_dict.get("summary", {})
        stabilized_noi_str = summary.get("stabilized_noi")
        stabilized_noi = (
            Decimal(stabilized_noi_str) if stabilized_noi_str is not None else None
        )

        # Get month 1 GSR from the monthly schedule
        monthly_schedule = pro_forma_dict.get("monthly_schedule", [])
        month_1_gsr = Decimal("0")
        if monthly_schedule:
            month_1_gsr_str = monthly_schedule[0].get("gsr", "0")
            month_1_gsr = Decimal(month_1_gsr_str)

        # Get sale comp rollup
        sale_comp_service = SaleCompService()
        rollup_data = sale_comp_service.get_comps_rollup(deal_id)

        sale_comp_rollup = SaleCompRollup(
            cap_rate_min=rollup_data.get("cap_rate_min"),
            cap_rate_median=rollup_data.get("cap_rate_median"),
            cap_rate_average=rollup_data.get("cap_rate_average"),
            cap_rate_max=rollup_data.get("cap_rate_max"),
            ppu_min=rollup_data.get("ppu_min"),
            ppu_median=rollup_data.get("ppu_median"),
            ppu_average=rollup_data.get("ppu_average"),
            ppu_max=rollup_data.get("ppu_max"),
        )

        valuation = compute_valuation(
            stabilized_noi=stabilized_noi,
            purchase_price=deal_inputs.deal.purchase_price,
            month_1_gsr=month_1_gsr,
            unit_count=deal_inputs.deal.unit_count,
            sale_comp_rollup=sale_comp_rollup,
            custom_cap_rate=deal_inputs.deal.custom_cap_rate,
        )

        return valuation.to_canonical_dict()

    def get_sources_and_uses(self, deal_id: int) -> dict[str, Any]:
        """Get Sources & Uses for both scenarios.

        Args:
            deal_id: The Deal to get sources and uses for.

        Returns:
            Dict with scenario_a and scenario_b sources and uses.
        """
        pro_forma_dict = self.get_pro_forma(deal_id)

        return {
            "scenario_a": pro_forma_dict.get("sources_and_uses_a"),
            "scenario_b": pro_forma_dict.get("sources_and_uses_b"),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compose_dashboard(
        self,
        deal_id: int,
        deal_inputs: Any,
        computation_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Compose the Dashboard response from a ProFormaComputation dict.

        Returns per-scenario summary fields (Req 11.1) with missing_inputs
        propagated as null-valued fields (Req 11.2).

        Args:
            deal_id: The Deal ID.
            deal_inputs: The frozen DealInputs snapshot.
            computation_dict: The canonical dict of the ProFormaComputation.

        Returns:
            Dashboard dict with scenario_a, scenario_b, valuation, and metadata.
        """
        summary = computation_dict.get("summary", {})
        missing_a = computation_dict.get("missing_inputs_a", [])
        missing_b = computation_dict.get("missing_inputs_b", [])
        sources_and_uses_a = computation_dict.get("sources_and_uses_a")
        sources_and_uses_b = computation_dict.get("sources_and_uses_b")
        monthly_schedule = computation_dict.get("monthly_schedule", [])

        # Extract lender info from inputs
        lender_a = deal_inputs.lender_scenario_a
        lender_b = deal_inputs.lender_scenario_b

        # Month 1 and Month 24 net cash flow
        month_1_ncf = None
        month_24_ncf = None
        if monthly_schedule:
            month_1_ncf = monthly_schedule[0].get("net_cash_flow")
            if len(monthly_schedule) >= 24:
                month_24_ncf = monthly_schedule[23].get("net_cash_flow")

        # Build Scenario A summary (Req 11.1)
        scenario_a: dict[str, Any]
        if missing_a:
            # Req 11.2: missing inputs -> null-valued fields
            scenario_a = {
                "purchase_price": str(deal_inputs.deal.purchase_price),
                "loan_amount": None,
                "interest_rate": None,
                "amort_years": None,
                "io_period_months": None,
                "in_place_noi": None,
                "stabilized_noi": None,
                "in_place_dscr": None,
                "stabilized_dscr": None,
                "price_to_rent_ratio": None,
                "valuation_at_cap_rate": None,
                "valuation_at_ppu": None,
                "sources_and_uses": None,
                "initial_cash_investment": None,
                "month_1_net_cash_flow": None,
                "month_24_net_cash_flow": None,
                "cash_on_cash_return": None,
                "missing_inputs": missing_a,
            }
        else:
            scenario_a = {
                "purchase_price": str(deal_inputs.deal.purchase_price),
                "loan_amount": (
                    sources_and_uses_a.get("loan_amount")
                    if sources_and_uses_a
                    else None
                ),
                "interest_rate": (
                    str(lender_a.construction_rate)
                    if lender_a and lender_a.construction_rate
                    else None
                ),
                "amort_years": (
                    lender_a.perm_amort_years if lender_a else None
                ),
                "io_period_months": (
                    lender_a.construction_io_months if lender_a else None
                ),
                "in_place_noi": summary.get("in_place_noi"),
                "stabilized_noi": summary.get("stabilized_noi"),
                "in_place_dscr": summary.get("in_place_dscr_a"),
                "stabilized_dscr": summary.get("stabilized_dscr_a"),
                "price_to_rent_ratio": None,
                "valuation_at_cap_rate": None,
                "valuation_at_ppu": None,
                "sources_and_uses": sources_and_uses_a,
                "initial_cash_investment": (
                    sources_and_uses_a.get("initial_cash_investment")
                    if sources_and_uses_a
                    else None
                ),
                "month_1_net_cash_flow": month_1_ncf,
                "month_24_net_cash_flow": month_24_ncf,
                "cash_on_cash_return": summary.get("cash_on_cash_a"),
                "missing_inputs": missing_a,
            }

        # Build Scenario B summary (Req 11.1)
        scenario_b: dict[str, Any]
        if missing_b:
            scenario_b = {
                "purchase_price": str(deal_inputs.deal.purchase_price),
                "loan_amount": None,
                "interest_rate": None,
                "amort_years": None,
                "io_period_months": None,
                "in_place_noi": None,
                "stabilized_noi": None,
                "in_place_dscr": None,
                "stabilized_dscr": None,
                "price_to_rent_ratio": None,
                "valuation_at_cap_rate": None,
                "valuation_at_ppu": None,
                "sources_and_uses": None,
                "initial_cash_investment": None,
                "month_1_net_cash_flow": None,
                "month_24_net_cash_flow": None,
                "cash_on_cash_return": None,
                "missing_inputs": missing_b,
            }
        else:
            # For Scenario B, all_in_rate is precomputed in the LenderProfileSnapshot
            all_in_rate = str(lender_b.all_in_rate) if lender_b and lender_b.all_in_rate is not None else None

            scenario_b = {
                "purchase_price": str(deal_inputs.deal.purchase_price),
                "loan_amount": (
                    sources_and_uses_b.get("loan_amount")
                    if sources_and_uses_b
                    else None
                ),
                "interest_rate": all_in_rate,
                "amort_years": (
                    lender_b.amort_years if lender_b else None
                ),
                "io_period_months": 0,  # Scenario B has no IO period
                "in_place_noi": summary.get("in_place_noi"),
                "stabilized_noi": summary.get("stabilized_noi"),
                "in_place_dscr": summary.get("in_place_dscr_b"),
                "stabilized_dscr": summary.get("stabilized_dscr_b"),
                "price_to_rent_ratio": None,
                "valuation_at_cap_rate": None,
                "valuation_at_ppu": None,
                "sources_and_uses": sources_and_uses_b,
                "initial_cash_investment": (
                    sources_and_uses_b.get("initial_cash_investment")
                    if sources_and_uses_b
                    else None
                ),
                "month_1_net_cash_flow": month_1_ncf,
                "month_24_net_cash_flow": month_24_ncf,
                "cash_on_cash_return": summary.get("cash_on_cash_b"),
                "missing_inputs": missing_b,
            }

        # Valuation (shared across scenarios)
        valuation_dict = computation_dict.get("valuation")

        # Populate valuation fields into scenarios if available
        if valuation_dict:
            for scenario in (scenario_a, scenario_b):
                if not scenario.get("missing_inputs"):
                    scenario["price_to_rent_ratio"] = valuation_dict.get(
                        "price_to_rent_ratio"
                    )
                    scenario["valuation_at_cap_rate"] = {
                        "min": valuation_dict.get("valuation_at_cap_rate_min"),
                        "median": valuation_dict.get("valuation_at_cap_rate_median"),
                        "average": valuation_dict.get("valuation_at_cap_rate_average"),
                        "max": valuation_dict.get("valuation_at_cap_rate_max"),
                    }
                    scenario["valuation_at_ppu"] = {
                        "min": valuation_dict.get("valuation_at_ppu_min"),
                        "median": valuation_dict.get("valuation_at_ppu_median"),
                        "average": valuation_dict.get("valuation_at_ppu_average"),
                        "max": valuation_dict.get("valuation_at_ppu_max"),
                    }

        return {
            "deal_id": deal_id,
            "scenario_a": scenario_a,
            "scenario_b": scenario_b,
            "valuation": valuation_dict,
            "warnings": computation_dict.get("warnings", []),
        }
