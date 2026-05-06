"""
Property test for Excel export/import round-trip.

# Feature: multifamily-underwriting-proforma, Property 1: For any valid Deal,
# import(export(deal)) equals deal over round-trippable fields

This test generates valid Deals via the `deal_inputs_st` strategy, persists
them to the database, exports to .xlsx bytes, imports the bytes into a fresh
Deal, and asserts equality over the fields captured by sheets with
`round_trippable=True`.

Requirements: 12.1, 12.2, 12.3, 13.1, 13.5
"""

import io
from decimal import Decimal

import pytest
from hypothesis import given, settings, HealthCheck

from tests.generators.multifamily import deal_inputs_st


@pytest.fixture
def app_context(app):
    """Provide an app context for the property test."""
    with app.app_context():
        yield app


def _quantize_2dp(val):
    """Quantize a Decimal to 2 decimal places for comparison."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val.quantize(Decimal("0.01"))
    return Decimal(str(val)).quantize(Decimal("0.01"))


def _quantize_1dp(val):
    """Quantize a Decimal to 1 decimal place for comparison (e.g. baths column Numeric(4,1))."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val.quantize(Decimal("0.1"))
    return Decimal(str(val)).quantize(Decimal("0.1"))


def _quantize_6dp(val):
    """Quantize a Decimal to 6 decimal places for rate comparison."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val.quantize(Decimal("0.000001"))
    return Decimal(str(val)).quantize(Decimal("0.000001"))


def _float_to_decimal_2dp(val):
    """Convert a float (from Excel) back to Decimal with 2dp precision."""
    if val is None:
        return None
    return Decimal(str(round(float(val), 2))).quantize(Decimal("0.01"))


def _float_to_decimal_6dp(val):
    """Convert a float (from Excel) back to Decimal with 6dp precision."""
    if val is None:
        return None
    return Decimal(str(round(float(val), 6))).quantize(Decimal("0.000001"))


@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(inputs=deal_inputs_st())
def test_round_trip_export_import(app_context, inputs):
    """Property 1: For any valid Deal, import(export(deal)) equals deal
    over round-trippable fields.

    # Feature: multifamily-underwriting-proforma, Property 1: For any valid Deal,
    # import(export(deal)) equals deal over round-trippable fields
    """
    from app import db
    from app.models.deal import Deal
    from app.models.unit import Unit
    from app.models.rent_roll_entry import RentRollEntry
    from app.models.rent_comp import RentComp
    from app.models.sale_comp import SaleComp
    from app.models.rehab_plan_entry import RehabPlanEntry
    from app.models.lender_profile import LenderProfile
    from app.models.deal_lender_selection import DealLenderSelection
    from app.models.funding_source import FundingSource
    from app.services.multifamily.excel_export_service import ExcelExportService
    from app.services.multifamily.excel_import_service import ExcelImportService

    # --- Step 1: Persist the generated DealInputs to the database ---
    deal = Deal(
        created_by_user_id="test-user",
        property_address="123 Test St",
        unit_count=inputs.deal.unit_count,
        purchase_price=inputs.deal.purchase_price,
        closing_costs=inputs.deal.closing_costs,
        vacancy_rate=inputs.deal.vacancy_rate,
        other_income_monthly=inputs.deal.other_income_monthly,
        management_fee_rate=inputs.deal.management_fee_rate,
        reserve_per_unit_per_year=inputs.deal.reserve_per_unit_per_year,
        interest_reserve_amount=inputs.deal.interest_reserve_amount,
        custom_cap_rate=inputs.deal.custom_cap_rate,
        property_taxes_annual=inputs.opex.property_taxes_annual,
        insurance_annual=inputs.opex.insurance_annual,
        utilities_annual=inputs.opex.utilities_annual,
        repairs_and_maintenance_annual=inputs.opex.repairs_and_maintenance_annual,
        admin_and_marketing_annual=inputs.opex.admin_and_marketing_annual,
        payroll_annual=inputs.opex.payroll_annual,
        other_opex_annual=inputs.opex.other_opex_annual,
        status="draft",
    )
    db.session.add(deal)
    db.session.flush()

    # Create units and rent roll entries
    unit_objs = {}
    for unit_snap in inputs.units:
        unit = Unit(
            deal_id=deal.id,
            unit_identifier=unit_snap.unit_id,
            unit_type=unit_snap.unit_type,
            beds=unit_snap.beds,
            baths=unit_snap.baths,
            sqft=unit_snap.sqft,
            occupancy_status=unit_snap.occupancy_status,
        )
        db.session.add(unit)
        db.session.flush()
        unit_objs[unit_snap.unit_id] = unit

    # Create rent roll entries
    for rr_snap in inputs.rent_roll:
        unit = unit_objs[rr_snap.unit_id]
        entry = RentRollEntry(
            unit_id=unit.id,
            current_rent=rr_snap.current_rent,
        )
        db.session.add(entry)

    # Create rehab plan entries
    for rehab_snap in inputs.rehab_plan:
        unit = unit_objs[rehab_snap.unit_id]
        stabilizes_after = False
        if (rehab_snap.renovate_flag and rehab_snap.stabilized_month is not None
                and rehab_snap.stabilized_month > 24):
            stabilizes_after = True
        entry = RehabPlanEntry(
            unit_id=unit.id,
            renovate_flag=rehab_snap.renovate_flag,
            current_rent=rehab_snap.current_rent,
            underwritten_post_reno_rent=rehab_snap.underwritten_post_reno_rent,
            rehab_start_month=rehab_snap.rehab_start_month,
            downtime_months=rehab_snap.downtime_months,
            stabilized_month=rehab_snap.stabilized_month,
            rehab_budget=rehab_snap.rehab_budget,
            stabilizes_after_horizon=stabilizes_after,
        )
        db.session.add(entry)

    # Create lender profiles and selections
    if inputs.lender_scenario_a is not None:
        lender_a = inputs.lender_scenario_a
        profile_a = LenderProfile(
            created_by_user_id="test-user",
            company="Test Lender A",
            lender_type=lender_a.lender_type,
            origination_fee_rate=lender_a.origination_fee_rate,
            ltv_total_cost=lender_a.ltv_total_cost,
            construction_rate=lender_a.construction_rate,
            construction_io_months=lender_a.construction_io_months,
            perm_rate=lender_a.perm_rate,
            perm_amort_years=lender_a.perm_amort_years,
        )
        db.session.add(profile_a)
        db.session.flush()
        sel_a = DealLenderSelection(
            deal_id=deal.id,
            lender_profile_id=profile_a.id,
            scenario="A",
            is_primary=True,
        )
        db.session.add(sel_a)

    if inputs.lender_scenario_b is not None:
        lender_b = inputs.lender_scenario_b
        profile_b = LenderProfile(
            created_by_user_id="test-user",
            company="Test Lender B",
            lender_type=lender_b.lender_type,
            origination_fee_rate=lender_b.origination_fee_rate,
            max_purchase_ltv=lender_b.max_purchase_ltv,
            treasury_5y_rate=(
                lender_b.all_in_rate - Decimal("0.02") if lender_b.all_in_rate else None
            ),
            spread_bps=200,
            amort_years=lender_b.amort_years,
        )
        db.session.add(profile_b)
        db.session.flush()
        sel_b = DealLenderSelection(
            deal_id=deal.id,
            lender_profile_id=profile_b.id,
            scenario="B",
            is_primary=True,
        )
        db.session.add(sel_b)

    # Create funding sources
    for fs_snap in inputs.funding_sources:
        fs = FundingSource(
            deal_id=deal.id,
            source_type=fs_snap.source_type,
            total_available=fs_snap.total_available,
            interest_rate=fs_snap.interest_rate,
            origination_fee_rate=fs_snap.origination_fee_rate,
        )
        db.session.add(fs)

    db.session.flush()

    # --- Step 2: Export the Deal to bytes ---
    export_service = ExcelExportService()
    xlsx_bytes = export_service.export_deal(deal.id)
    assert len(xlsx_bytes) > 0

    # --- Step 3: Import the bytes into a new Deal ---
    import_service = ExcelImportService()
    result = import_service.import_workbook("import-user", io.BytesIO(xlsx_bytes))
    db.session.flush()

    assert result.deal_id is not None
    assert result.deal_id != deal.id  # Should be a new deal

    # --- Step 4: Compare round-trippable fields ---
    imported_deal_id = result.deal_id

    # Compare S01 — Rent Roll
    original_units = (
        Unit.query.filter_by(deal_id=deal.id)
        .order_by(Unit.unit_identifier)
        .all()
    )
    imported_units = (
        Unit.query.filter_by(deal_id=imported_deal_id)
        .order_by(Unit.unit_identifier)
        .all()
    )

    assert len(imported_units) == len(original_units), (
        f"Unit count mismatch: {len(imported_units)} vs {len(original_units)}"
    )

    for orig_unit, imp_unit in zip(original_units, imported_units):
        assert imp_unit.unit_identifier == orig_unit.unit_identifier
        assert imp_unit.unit_type == orig_unit.unit_type
        assert imp_unit.beds == orig_unit.beds
        # Baths: stored as Numeric(4,1) so compare at 1dp precision
        if orig_unit.baths is not None:
            assert _quantize_1dp(imp_unit.baths) == _quantize_1dp(orig_unit.baths)
        assert imp_unit.sqft == orig_unit.sqft
        assert imp_unit.occupancy_status == orig_unit.occupancy_status

        # Rent roll entry
        orig_rr = orig_unit.rent_roll_entry
        imp_rr = imp_unit.rent_roll_entry
        if orig_rr is not None:
            assert imp_rr is not None, f"Missing rent roll for {orig_unit.unit_identifier}"
            assert _float_to_decimal_2dp(imp_rr.current_rent) == _quantize_2dp(orig_rr.current_rent)

    # Compare S04 — Rehab Timing
    for orig_unit, imp_unit in zip(original_units, imported_units):
        orig_rehab = orig_unit.rehab_plan_entry
        imp_rehab = imp_unit.rehab_plan_entry
        if orig_rehab is not None:
            assert imp_rehab is not None, f"Missing rehab for {orig_unit.unit_identifier}"
            assert imp_rehab.renovate_flag == orig_rehab.renovate_flag
            if orig_rehab.renovate_flag:
                assert imp_rehab.rehab_start_month == orig_rehab.rehab_start_month
                assert imp_rehab.downtime_months == orig_rehab.downtime_months
                if orig_rehab.current_rent is not None:
                    assert _float_to_decimal_2dp(imp_rehab.current_rent) == _quantize_2dp(orig_rehab.current_rent)
                if orig_rehab.rehab_budget is not None:
                    assert _float_to_decimal_2dp(imp_rehab.rehab_budget) == _quantize_2dp(orig_rehab.rehab_budget)

    # Compare Funding_Sources
    original_fs = (
        FundingSource.query.filter_by(deal_id=deal.id)
        .order_by(FundingSource.source_type)
        .all()
    )
    imported_fs = (
        FundingSource.query.filter_by(deal_id=imported_deal_id)
        .order_by(FundingSource.source_type)
        .all()
    )

    assert len(imported_fs) == len(original_fs), (
        f"Funding source count mismatch: {len(imported_fs)} vs {len(original_fs)}"
    )

    for orig, imp in zip(original_fs, imported_fs):
        assert imp.source_type == orig.source_type
        assert _float_to_decimal_2dp(imp.total_available) == _quantize_2dp(orig.total_available)
        assert _float_to_decimal_6dp(imp.interest_rate) == _quantize_6dp(orig.interest_rate)
        assert _float_to_decimal_6dp(imp.origination_fee_rate) == _quantize_6dp(orig.origination_fee_rate)

    # Compare S07 — Lender Assumptions
    original_selections = (
        DealLenderSelection.query.filter_by(deal_id=deal.id)
        .order_by(DealLenderSelection.scenario)
        .all()
    )
    imported_selections = (
        DealLenderSelection.query.filter_by(deal_id=imported_deal_id)
        .order_by(DealLenderSelection.scenario)
        .all()
    )

    assert len(imported_selections) == len(original_selections), (
        f"Lender selection count mismatch: {len(imported_selections)} vs {len(original_selections)}"
    )

    for orig_sel, imp_sel in zip(original_selections, imported_selections):
        assert imp_sel.scenario == orig_sel.scenario
        assert imp_sel.is_primary == orig_sel.is_primary
        orig_profile = orig_sel.lender_profile
        imp_profile = imp_sel.lender_profile
        assert imp_profile.company == orig_profile.company
        assert imp_profile.lender_type == orig_profile.lender_type
        assert _float_to_decimal_6dp(imp_profile.origination_fee_rate) == _quantize_6dp(orig_profile.origination_fee_rate)

    # --- Cleanup: rollback to avoid cross-test pollution ---
    db.session.rollback()
