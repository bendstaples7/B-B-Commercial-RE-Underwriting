# Implementation Plan: Multifamily Underwriting Pro Forma

## Overview

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

The plan builds bottom-up: exceptions and schemas first, then SQLAlchemy models and the Alembic migration, then the deterministic pure-function computation core (where 13 of the 16 correctness properties live), then CRUD services, REST controllers, caching and Celery, then Excel/Sheets interchange (Property 1 round-trip), and finally the React frontend.

Property tests for the pure computation layer (`pro_forma_engine`, `valuation_engine`, `sources_and_uses_service`, `funding_service.compute_draws`, `inputs_hash`, `excel_export_service`/`excel_import_service` round-trip) are required tasks because they are the acceptance criteria for the pure functions they validate. Example-based unit tests, integration tests, and controller smoke tests are marked optional with `*`.

Every property test task below uses the mandatory docstring tag:

```python
# Feature: multifamily-underwriting-proforma, Property N: <property body>
```

## Tasks

- [x] 1. Add exception classes and Marshmallow schemas
  - [x] 1.1 Append new exception classes to `backend/app/exceptions.py`
    - Add `DealValidationError` (400), `DuplicateUnitIdentifierError` (409), `DuplicateFundingSourceError` (409), `LenderAttachmentLimitError` (400), `ProFormaMissingInputsError` (422), `UnsupportedImportFormatError` (422)
    - Each extends `RealEstateAnalysisException` and follows the existing payload convention (`error_type`, plus field/constraint detail)
    - _Requirements: 1.2, 1.3, 2.2, 6.3, 6.4, 6.7, 7.2, 13.2, 13.3_

  - [x] 1.2 Append multifamily Marshmallow schemas to `backend/app/schemas.py`
    - `DealCreateSchema`, `DealUpdateSchema`, `DealResponseSchema`
    - `UnitCreateSchema`, `UnitUpdateSchema`, `RentRollEntrySchema`
    - `MarketRentAssumptionSchema`, `RentCompCreateSchema`, `RentCompResponseSchema`
    - `SaleCompCreateSchema`, `SaleCompResponseSchema`
    - `RehabPlanEntrySchema`
    - `LenderProfileCreateSchema` with `@validates_schema` enforcing per-`lender_type` required-field sets (Construction_To_Perm vs Self_Funded_Reno)
    - `DealLenderSelectionSchema`
    - `FundingSourceSchema`
    - Bound-check validators for rates (0..0.30), LTV (0..1), cap rate (0..0.25), unit_count (>= 5), purchase_price (> 0), sqft (> 0), unit_count on sale comps (> 0), rehab_start_month (1..24), downtime_months (>= 0), lease date ordering
    - _Requirements: 1.1-1.3, 2.1, 2.2, 2.4, 3.1-3.3, 4.1-4.3, 5.1-5.3, 6.1-6.4, 7.1_

  - [ ]* 1.3 Write unit tests for multifamily schemas
    - Known-good payloads accepted; out-of-range/duplicate/missing payloads rejected with the expected error_type
    - _Requirements: 1.2, 1.3, 2.2, 2.4, 3.3, 4.2, 4.3, 5.2, 5.3, 6.3, 6.4, 6.7, 7.2_

- [x] 2. Create SQLAlchemy models and the Alembic migration
  - [x] 2.1 Create the 13 SQLAlchemy model files under `backend/app/models/`
    - `deal.py` (CHECK unit_count >= 5, CHECK purchase_price > 0, soft-delete column)
    - `unit.py` (UNIQUE (deal_id, unit_identifier), CHECK occupancy_status IN ('Occupied','Vacant','Down'))
    - `rent_roll_entry.py` (one-to-one with Unit, CHECK lease_end_date >= lease_start_date)
    - `market_rent_assumption.py` (UNIQUE (deal_id, unit_type))
    - `rent_comp.py` (CHECK sqft > 0, computed rent_per_sqft at write-time)
    - `sale_comp.py` (CHECK unit_count > 0, CHECK observed_cap_rate in (0, 0.25], computed observed_ppu at write-time)
    - `rehab_plan_entry.py` (CHECK rehab_start_month IN [1,24] OR NULL, CHECK downtime_months >= 0 OR NULL, derived stabilized_month, stabilizes_after_horizon flag)
    - `lender_profile.py` (CHECK lender_type IN ('Construction_To_Perm','Self_Funded_Reno'), computed `all_in_rate` Python property for Self_Funded_Reno)
    - `deal_lender_selection.py` (UNIQUE (deal_id, scenario, lender_profile_id); partial-unique index on `is_primary` per (deal_id, scenario))
    - `funding_source.py` (UNIQUE (deal_id, source_type))
    - `pro_forma_result.py` (UNIQUE deal_id, JSONB result_json)
    - `lead_deal_link.py` (UNIQUE (lead_id, deal_id))
    - `deal_audit_trail.py` (mirrors existing `LeadAuditTrail` shape)
    - Re-export every model from `backend/app/models/__init__.py`
    - _Requirements: 1.1-1.7, 2.1-2.4, 3.1-3.3, 4.1-4.3, 5.1-5.5, 6.1-6.6, 7.1-7.2, 14.3-14.4, 15.1_

  - [x] 2.2 Create single additive Alembic migration `backend/alembic_migrations/versions/c3d4e5f6g7h8_multifamily_schema.py`
    - Create all 13 tables in dependency order: `lender_profiles` → `deals` → `units` → `rent_roll_entries` → `rehab_plan_entries` → `market_rent_assumptions` → `rent_comps` → `sale_comps` → `deal_lender_selections` → `funding_sources` → `pro_forma_results` → `lead_deal_links` → `deal_audit_trails`
    - All CHECK constraints listed in design §Data Models
    - Indexes on `deals.created_by_user_id`, `deals.property_address`, `lender_profiles.created_by_user_id`, `lead_deal_links.lead_id`, `lead_deal_links.deal_id`, and the partial-unique index for `is_primary`
    - Downgrade drops tables in reverse order
    - No existing table is modified
    - _Requirements: 1.1-1.7, 2.1-2.5, 3.1, 4.1, 5.1, 6.1-6.6, 7.1-7.2, 14.3-14.4, 15.1_

  - [ ]* 2.3 Write unit tests for model structure
    - Extend `backend/tests/test_models_structure.py` or create `test_multifamily_models.py` to assert table names, primary keys, FKs, CHECK constraints, and unique constraints are present
    - _Requirements: 1.1, 2.2, 4.3, 6.7, 7.2_

- [x] 3. Build the pure computation core (input snapshots + engine)
  - [x] 3.1 Create `backend/app/services/multifamily/pro_forma_constants.py`
    - `HORIZON_MONTHS = 24`, `STABILIZED_MONTHS = range(13, 25)`, Decimal quantization helpers (`MONEY_Q`, `RATE_Q`)
    - Scenario enum (`'A'`, `'B'`) and missing-input codes (`RENT_ROLL_INCOMPLETE`, `REHAB_PLAN_MISSING`, `OPEX_ASSUMPTIONS_MISSING`, `PRIMARY_LENDER_MISSING_A`, `PRIMARY_LENDER_MISSING_B`, `FUNDING_INSUFFICIENT`)
    - _Requirements: 8.1-8.14_

  - [x] 3.2 Create frozen input dataclasses in `backend/app/services/multifamily/pro_forma_inputs.py`
    - `DealSnapshot`, `UnitSnapshot`, `RentRollSnapshot`, `RehabPlanSnapshot`, `MarketRentSnapshot`, `OpExAssumptions`, `ReserveAssumptions`, `LenderProfileSnapshot`, `FundingSourceSnapshot`, `DealInputs` (all `@dataclass(frozen=True)`, Decimal everywhere)
    - `CapExAllocationStrategy` Protocol plus default `LumpSumAtStart` implementation
    - _Requirements: 8.1-8.11_

  - [x] 3.3 Create `backend/app/services/multifamily/pro_forma_result_dc.py`
    - `MonthlyRow`, `OpExBreakdown`, `ProFormaSummary`, `SourcesAndUses`, `Valuation`, `ProFormaComputation` (frozen dataclasses)
    - `to_canonical_dict()` helpers on each for stable JSON serialization
    - _Requirements: 8.12, 10.1-10.7, 11.1_

  - [x] 3.4 Implement `backend/app/services/multifamily/pro_forma_engine.py` (pure function `compute_pro_forma(inputs) -> ProFormaComputation`)
    - Pipeline: scan for missing inputs → per-unit schedule → monthly GSR → EGI → OpEx (fixed lines/12 + mgmt_fee_rate·EGI) → NOI → replacement_reserves → net_cash_flow → debt_service_A (IO then amortizing, with perm_rate=0 fallback to `loan / n`) → debt_service_B (amortizing all 24) → cash_flow_after_debt(A/B) → capex_spend (lump-sum at start) → cash_flow_after_capex(A/B) → summary (In_Place_NOI, Stabilized_NOI, In_Place_DSCR, Stabilized_DSCR, Cash_On_Cash with null guards)
    - Engine MUST NOT raise on user-driven missing-input conditions; populates `missing_inputs_a`/`missing_inputs_b` and sets scenario summary fields to `None`
    - All math in `Decimal` with documented quantization (2dp money, 6dp rates)
    - _Requirements: 8.1-8.14, 10.6, 10.7_

  - [x] 3.5 Write property test for per-unit scheduled rent + GSR
    - `backend/tests/generators/multifamily.py`: composite Hypothesis strategies `deal_inputs_st`, `deal_inputs_with_missing_st`, `amortization_inputs_st`, `funding_sources_st`, `cap_rate_st`
    - `backend/tests/test_multifamily_properties.py::test_scheduled_rent_rule`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 2: Per-unit scheduled rent rule and monthly GSR`
    - `@settings(max_examples=100, deadline=None)`
    - **Property 2** - **Validates: Requirements 8.1, 8.2**

  - [x] 3.6 Write property test for monthly math identity
    - `backend/tests/test_multifamily_properties.py::test_monthly_math_identity`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 3: Monthly math identity`
    - Asserts EGI, OpEx, NOI, net_cash_flow, cash_flow_after_debt, cash_flow_after_capex identities for every M in 1..24
    - **Property 3** - **Validates: Requirements 8.3, 8.4, 8.5, 8.6, 8.9, 8.11**

  - [x] 3.7 Write property test for amortization schedule recovers principal
    - `test_multifamily_properties.py::test_amortization_recovers_principal`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 5: Amortizing schedule recovers principal`
    - Asserts sum of principal components equals loan_amount within tolerance `0.01 * n`
    - **Property 5** - **Validates: Requirements 8.7 (amortizing branch), 8.8**

  - [x] 3.8 Write property test for interest-only debt service identity
    - `test_multifamily_properties.py::test_io_debt_service_identity`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 6: Interest-only debt service identity`
    - Asserts `debt_service_A(M) == loan_amount * construction_rate / 12` exactly for M in 1..construction_io_months
    - **Property 6** - **Validates: Requirement 8.7 (IO branch)**

  - [x] 3.9 Write property test for DSCR formula + null guard
    - `test_multifamily_properties.py::test_dscr_formula_and_null`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 8: DSCR formula and null guard`
    - For M in {1, 24} × scenario in {A, B}: zero debt service yields DSCR=None, non-zero yields NOI/DS
    - **Property 8** - **Validates: Requirements 8.12 (DSCR subset), 8.13**

  - [x] 3.10 Write property test for summary NOI identities
    - `test_multifamily_properties.py::test_summary_noi_identities`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 9: Summary NOI identities`
    - Asserts `In_Place_NOI == noi(1) * 12` and `Stabilized_NOI == average(noi(13..24)) * 12`
    - **Property 9** - **Validates: Requirement 8.12 (NOI subset)**

  - [x] 3.11 Write property test for Cash-on-Cash identity + null guard
    - `test_multifamily_properties.py::test_cash_on_cash_identity`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 13: Cash-on-Cash identity and null guard`
    - Positive equity: `cash_on_cash == sum(cfad(M in 13..24)) / initial_cash_investment`; non-positive equity: `None` with `Non_Positive_Equity` warning
    - **Property 13** - **Validates: Requirements 10.6, 10.7**

  - [x] 3.12 Write property test for missing-inputs path never raises
    - `test_multifamily_properties.py::test_missing_inputs_never_raises`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 14: Missing-inputs path never raises`
    - Uses `deal_inputs_with_missing_st` strategy; asserts no exception and scenario summaries are None
    - **Property 14** - **Validates: Requirements 8.14, 11.2**

  - [ ]* 3.13 Write example-based unit tests for `pro_forma_engine`
    - `backend/tests/test_pro_forma_engine.py` with 3-unit fixture exercising renovate-flag branches, IO→amortizing transition, and `perm_rate == 0` edge case
    - _Requirements: 8.1-8.14_

- [x] 4. Implement inputs hash and property-test cache determinism
  - [x] 4.1 Implement `backend/app/services/multifamily/inputs_hash.py`
    - `canonical_inputs(deal) -> dict` sorts lists by stable natural keys, serializes Decimal via `str()`, excludes timestamps and soft-deleted rows
    - `compute_inputs_hash(deal) -> str` is SHA-256 of canonical JSON with `sort_keys=True, separators=(",", ":")`
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 4.2 Write property test for cache determinism and invalidation
    - `test_multifamily_properties.py::test_cache_determinism` and `::test_cache_invalidation`
    - Docstring tags: `# Feature: multifamily-underwriting-proforma, Property 7: Cache determinism and invalidation`
    - Determinism: two calls on the same inputs yield identical `ProFormaComputation` (byte-equal canonical JSON) and identical `compute_inputs_hash`
    - Hash sensitivity: changing any field listed in Req 15.3 changes the hash
    - **Property 7** - **Validates: Requirements 15.1, 15.2, 15.3**

  - [ ]* 4.3 Write example-based unit tests for `inputs_hash`
    - `backend/tests/test_inputs_hash.py` with Decimal round-trip, None handling, row-order invariance
    - _Requirements: 15.1_

- [x] 5. Implement valuation engine
  - [x] 5.1 Implement `backend/app/services/multifamily/valuation_engine.py` as pure `compute_valuation(...)`
    - Computes `valuation_at_cap_rate_{min,median,average,max}`, `valuation_at_ppu_{min,median,average,max}`, optional `valuation_at_custom_cap_rate`, `price_to_rent_ratio`
    - Stabilized_NOI <= 0 → cap-rate valuations None and `Non_Positive_Stabilized_NOI` warning
    - _Requirements: 9.1-9.5_

  - [x] 5.2 Write property test for valuation cap-rate round-trip + null guard
    - `test_multifamily_properties.py::test_valuation_cap_rate_round_trip`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 12: Valuation cap-rate round-trip and null guard`
    - Positive NOI: `valuation(cap_rate) * cap_rate ≈ stabilized_noi`; non-positive NOI: all cap-rate valuations None and warning present
    - **Property 12** - **Validates: Requirements 9.1, 9.3, 9.4**

  - [ ]* 5.3 Write example-based unit tests for `valuation_engine`
    - `backend/tests/test_valuation_engine_multifamily.py` (distinct from existing single-family test) covering custom cap-rate path and zero sale comps
    - _Requirements: 9.2, 9.3, 9.5_

- [x] 6. Implement funding waterfall and property-test its invariants
  - [x] 6.1 Implement `backend/app/services/multifamily/funding_service.py`
    - `add_source`, `update_source`, `delete_source` (enforce Req 7.2 duplicate detection via `DuplicateFundingSourceError`)
    - Pure helper `compute_draws(required_equity, sources_by_type) -> (draws, shortfall)` in priority order Cash → HELOC_1 → HELOC_2
    - `compute_origination_fees(draws)` and `compute_heloc_carrying_interest(draws, month_index)`
    - _Requirements: 7.1-7.6_

  - [x] 6.2 Write property test for funding waterfall invariants
    - `test_multifamily_properties.py::test_funding_waterfall_invariants`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 4: Funding waterfall invariants`
    - All five invariants from design §Property 4
    - **Property 4** - **Validates: Requirements 7.3, 7.4, 7.5**

  - [ ]* 6.3 Write example-based unit tests for `funding_service`
    - `backend/tests/test_funding_service.py` covering duplicate rejection, partial coverage shortfall, zero sources
    - _Requirements: 7.1, 7.2, 7.4_

- [x] 7. Implement Sources & Uses helpers and property-test identities
  - [x] 7.1 Implement `backend/app/services/multifamily/sources_and_uses_service.py`
    - Pure helpers `compute_loan_amount_scenario_a(...)`, `compute_loan_amount_scenario_b(...)`, `build_sources_and_uses(...)`
    - `SourcesAndUses` populated with typed uses (purchase_price, closing_costs, rehab_budget_total, loan_origination_fees, funding_source_origination_fees, interest_reserve) and typed sources (loan_amount, cash_draw, heloc_1_draw, heloc_2_draw)
    - `initial_cash_investment = total_uses - loan_amount`
    - _Requirements: 10.1-10.5_

  - [x] 7.2 Wire Sources & Uses into `pro_forma_engine.compute_pro_forma`
    - Engine populates `sources_and_uses_a` and `sources_and_uses_b` in the returned `ProFormaComputation`
    - _Requirements: 10.1-10.5_

  - [x] 7.3 Write property test for Sources & Uses accounting identity
    - `test_multifamily_properties.py::test_sources_and_uses_identity`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 10: Sources & Uses accounting identity`
    - Asserts `total_uses`, `initial_cash_investment`, `total_sources` identities and the no-shortfall equivalence
    - **Property 10** - **Validates: Requirement 10.5, grounds 10.1, 10.2**

  - [x] 7.4 Write property test for loan amount identities
    - `test_multifamily_properties.py::test_loan_amount_identities`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 11: Loan amount identities`
    - `loan_amount_A == ltv_total_cost * (purchase_price + closing_costs + rehab_budget_total)` and `loan_amount_B == max_purchase_ltv * purchase_price`
    - **Property 11** - **Validates: Requirements 10.3, 10.4**

- [x] 8. Write consolidated computed-field property test
  - [x] 8.1 Write property test for computed-field identities
    - `test_multifamily_properties.py::test_computed_field_identities` (parameterised)
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities`
    - Covers `RentComp.rent_per_sqft`, `SaleComp.observed_ppu`, `LenderProfile.all_in_rate`, `RehabPlanEntry.stabilized_month`, `Valuation.price_to_rent_ratio`, `Valuation.valuation_at_ppu`
    - **Property 16** - **Validates: Requirements 3.2, 4.1, 5.1, 6.2, 9.2, 9.5**

- [x] 9. Checkpoint — pure computation layer
  - Ensure all tests pass, ask the user if questions arise.
  - All 13 property tests (P2-P14, P16) implemented and green against the pure engine
  - _Validates: Requirements 7.3-7.5, 8.1-8.14, 9.1-9.5, 10.3-10.7, 15.1-15.3, 16._

- [x] 10. Implement input CRUD services
  - [x] 10.1 Implement `backend/app/services/multifamily/deal_service.py`
    - `create_deal`, `get_deal`, `list_deals`, `update_deal` (invalidates pro_forma_results cache in same transaction), `soft_delete_deal`, `link_to_lead`, `suggest_lead_match`
    - `user_has_access(user_id, deal_id)` — returns True if direct owner OR any `LeadDealLink` points to a Lead the user can access
    - `build_inputs_snapshot(deal_id) -> DealInputs` (populates the frozen dataclasses from ORM rows)
    - Logs every mutation to `deal_audit_trails`
    - _Requirements: 1.1-1.8, 14.2-14.4, 15.3-15.4_

  - [x] 10.2 Implement `backend/app/services/multifamily/rent_roll_service.py`
    - `add_unit` (raises `DuplicateUnitIdentifierError` on Req 2.2 violation), `update_unit`, `delete_unit`, `set_rent_roll_entry`, `get_rent_roll_summary`
    - Flags `Rent_Roll_Incomplete` warning when entries < unit_count (Req 2.6)
    - _Requirements: 2.1-2.6_

  - [x] 10.3 Implement `backend/app/services/multifamily/market_rent_service.py`
    - `set_assumption`, `add_rent_comp` (computes `rent_per_sqft`), `delete_rent_comp`, `get_comps_rollup` (avg/median/avg_per_sqft), `default_assumptions_from_comps` (auto-fill when ≥3 comps per unit_type, Req 3.5)
    - _Requirements: 3.1-3.5_

  - [x] 10.4 Implement `backend/app/services/multifamily/sale_comp_service.py`
    - `add_sale_comp` (computes `observed_ppu`), `delete_sale_comp`, `get_comps_rollup` (min/median/avg/max for cap rates and PPU)
    - Flags `Sale_Comps_Insufficient` warning when < 3 comps (Req 4.5)
    - _Requirements: 4.1-4.5_

  - [x] 10.5 Implement `backend/app/services/multifamily/rehab_service.py`
    - `set_plan_entry` (computes `stabilized_month`, sets `stabilizes_after_horizon` flag when start+downtime > 24), `get_monthly_rollup` (Req 5.6), `get_rehab_budget_total` (Req 5.7)
    - Renovate_Flag=False → ignores rehab_start_month/downtime/budget and sets stabilized_month=NULL
    - _Requirements: 5.1-5.7_

  - [x] 10.6 Implement `backend/app/services/multifamily/lender_service.py`
    - `create_profile` with rate/LTV bounds validation (raises `DealValidationError`)
    - `list_profiles`, `update_profile`, `delete_profile`
    - `attach_to_deal(deal_id, scenario, profile_id, is_primary)` (raises `LenderAttachmentLimitError` when > 3 per scenario)
    - `detach_from_deal`
    - _Requirements: 6.1-6.7_

  - [x] 10.7 Re-export all services from `backend/app/services/multifamily/__init__.py`
    - _Requirements: 1-15_

  - [ ]* 10.8 Write example-based unit tests for input services
    - One file per service matching existing conventions: `test_deal_service_multifamily.py`, `test_rent_roll_service.py`, `test_rehab_service.py`, `test_lender_service.py`, `test_market_rent_service.py`, `test_sale_comp_service.py`
    - Covers validation, duplicate detection, rollups, default-from-comps fallback
    - _Requirements: 1.1-7.2_

- [x] 11. Write property test for Lead-based Deal permission inheritance
  - [x] 11.1 Write property test
    - `test_multifamily_properties.py::test_deal_access_via_lead`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 15: Lead-based Deal permission inheritance`
    - Uses Hypothesis to enumerate `(user, lead, deal, link_exists, user_has_lead_access)` combinations and asserts `DealService.user_has_access` matches the expected truth table
    - **Property 15** - **Validates: Requirement 14.3**

- [x] 12. Implement Flask Blueprint controllers
  - [x] 12.1 Create `backend/app/controllers/multifamily_deal_controller.py`
    - Blueprint `multifamily_deal_bp`, URL prefix `/api/multifamily`
    - Routes: `POST /deals`, `GET /deals`, `GET /deals/<id>`, `PATCH /deals/<id>`, `DELETE /deals/<id>`, `POST /deals/<id>/link-lead`
    - Uses `@handle_errors`, Marshmallow schemas for request/response, and `DealService.user_has_access` for permission checks
    - _Requirements: 1.1-1.8, 14.1-14.3_

  - [x] 12.2 Create `backend/app/controllers/multifamily_rent_roll_controller.py`
    - Routes: `POST /deals/<id>/units`, `PATCH /deals/<id>/units/<unit_id>`, `DELETE /deals/<id>/units/<unit_id>`, `PUT /deals/<id>/units/<unit_id>/rent-roll`, `GET /deals/<id>/rent-roll/summary`
    - _Requirements: 2.1-2.6_

  - [x] 12.3 Create `backend/app/controllers/multifamily_market_rent_controller.py`
    - Routes: `PUT /deals/<id>/market-rents/<unit_type>`, `POST /deals/<id>/rent-comps`, `DELETE /deals/<id>/rent-comps/<comp_id>`, `GET /deals/<id>/rent-comps/rollup`
    - _Requirements: 3.1-3.5_

  - [x] 12.4 Create `backend/app/controllers/multifamily_sale_comp_controller.py`
    - Routes: `POST /deals/<id>/sale-comps`, `DELETE /deals/<id>/sale-comps/<comp_id>`, `GET /deals/<id>/sale-comps/rollup`
    - _Requirements: 4.1-4.5_

  - [x] 12.5 Create `backend/app/controllers/multifamily_rehab_controller.py`
    - Routes: `PUT /deals/<id>/units/<unit_id>/rehab`, `GET /deals/<id>/rehab/rollup`
    - _Requirements: 5.1-5.7_

  - [x] 12.6 Create `backend/app/controllers/multifamily_lender_controller.py`
    - Routes: `POST /lender-profiles`, `GET /lender-profiles`, `PATCH /lender-profiles/<id>`, `DELETE /lender-profiles/<id>`, `POST /deals/<id>/scenarios/<A|B>/lenders`, `DELETE /deals/<id>/scenarios/<A|B>/lenders/<selection_id>`
    - _Requirements: 6.1-6.7_

  - [x] 12.7 Create `backend/app/controllers/multifamily_funding_controller.py`
    - Routes: `POST /deals/<id>/funding-sources`, `PATCH /deals/<id>/funding-sources/<source_id>`, `DELETE /deals/<id>/funding-sources/<source_id>`
    - _Requirements: 7.1-7.6_

  - [x] 12.8 Register all controllers in `backend/app/__init__.py` and `backend/app/controllers/__init__.py`
    - Add each blueprint to `__all__` and register in `create_app`
    - _Requirements: 14.1_

  - [ ]* 12.9 Write integration tests for CRUD controllers
    - `backend/tests/test_multifamily_controllers.py` — happy paths, validation errors, duplicate errors, 403 on unauthorized access, using the existing `client` fixture
    - _Requirements: 1.1-7.6_

- [x] 13. Build composition layer (Dashboard + caching + Celery)
  - [x] 13.1 Implement `backend/app/services/multifamily/dashboard_service.py`
    - `get_dashboard(deal_id)` reads current `inputs_hash`; on hash match returns cached `pro_forma_results.result_json`; otherwise calls `compute_pro_forma(build_inputs_snapshot(deal_id))`, upserts the cache row (inputs_hash + computed_at + result_json), and returns the freshly-composed Dashboard
    - Returns per-scenario summary (Req 11.1) and propagates `missing_inputs` as null-valued fields (Req 11.2)
    - _Requirements: 11.1, 11.2, 15.1, 15.2, 15.4_

  - [x] 13.2 Wire cache invalidation into input services
    - Every mutation in `deal_service`, `rent_roll_service`, `rehab_service`, `market_rent_service`, `funding_service`, `lender_service.attach_to_deal`/`detach_from_deal` deletes the `pro_forma_results` row for the affected deal in the same transaction as the write
    - _Requirements: 15.3, 15.4_

  - [x] 13.3 Create `backend/app/controllers/multifamily_pro_forma_controller.py`
    - Routes: `GET /deals/<id>/pro-forma`, `POST /deals/<id>/pro-forma/recompute`, `GET /deals/<id>/valuation`, `GET /deals/<id>/sources-and-uses`
    - Register in `backend/app/__init__.py`
    - _Requirements: 8.1-8.14, 9.1-9.5, 10.1-10.7_

  - [x] 13.4 Create `backend/app/controllers/multifamily_dashboard_controller.py`
    - Route: `GET /deals/<id>/dashboard`
    - Register in `backend/app/__init__.py`
    - _Requirements: 11.1, 11.2_

  - [x] 13.5 Create Celery bulk recompute task in `backend/app/tasks/multifamily_recompute.py`
    - Task `recompute_all_deals()` iterates deals, calls `DashboardService.get_dashboard(deal_id)` to force cache warm
    - Admin route `POST /admin/recompute-all` enqueues the task
    - _Requirements: 15.5_

  - [ ]* 13.6 Write integration tests for dashboard and caching
    - `backend/tests/test_multifamily_dashboard.py` — hash-hit short-circuit, hash-miss recompute path, missing-inputs scenario-null propagation, write-path cache invalidation
    - _Requirements: 11.1, 11.2, 15.1-15.4_

- [x] 14. Implement Excel workbook spec, exporter, and importer
  - [x] 14.1 Implement `backend/app/services/multifamily/excel_workbook_spec.py`
    - `ColumnSpec` and `SheetSpec` dataclasses
    - `WORKBOOK_SHEETS` tuple with the 10 sheets (`S00a_Summary_ScenarioA`, `S00b_Summary_ScenarioB`, `S01_RentRoll_InPlace`, `S02_MarketRents_Comps`, `S03_SaleComps_CapRates`, `S04_Rehab_Timing`, `S05_ProForma_24mo`, `S06_Valuation`, `S07_Lender_Assumptions`, `Funding_Sources`) with full `columns` tuples
    - `round_trippable=True` flag set for S01, S02, S03, S04, S07, Funding_Sources
    - _Requirements: 12.1, 12.2, 13.1_

  - [x] 14.2 Implement `backend/app/services/multifamily/excel_export_service.py`
    - `export_deal(deal_id) -> bytes` uses `openpyxl` and reads `WORKBOOK_SHEETS` as the single source of truth
    - Writes values only (no formulas, Req 12.3) for computed-output sheets S00a/S00b/S05/S06
    - Populates round-trippable sheets from the Deal's input snapshot
    - _Requirements: 12.1-12.4, 14.5_

  - [x] 14.3 Implement `backend/app/services/multifamily/excel_import_service.py`
    - `import_workbook(user_id, file) -> ImportResult` parses only round-trippable sheets
    - Raises `UnsupportedImportFormatError` for missing sheet (Req 13.2) or missing column (Req 13.3) with `missing_sheet` or `(missing_column, sheet)` payload
    - Creates Deal + child rows in one transaction; returns `ImportResult(deal_id, parse_report)` with per-sheet rows_parsed/rows_skipped/warnings
    - _Requirements: 13.1-13.4_

  - [x] 14.4 Write property test for Excel export/import round-trip
    - `backend/tests/test_multifamily_round_trip.py::test_round_trip_export_import`
    - Docstring tag: `# Feature: multifamily-underwriting-proforma, Property 1: For any valid Deal, import(export(deal)) equals deal over round-trippable fields`
    - `@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)`
    - Generates valid Deals via `deal_inputs_st`, exports to bytes, imports bytes, asserts equality over fields captured by sheets with `round_trippable=True`
    - **Property 1** - **Validates: Requirements 12.1, 12.2, 12.3, 13.1, 13.5**

  - [x] 14.5 Create `backend/app/controllers/multifamily_import_export_controller.py`
    - Routes: `GET /deals/<id>/export/excel` (streams .xlsx bytes), `POST /deals/import/excel` (`@limiter.limit("10 per hour")`)
    - Register in `backend/app/__init__.py`
    - _Requirements: 12.1-12.4, 13.1-13.4_

  - [ ]* 14.6 Write example-based tests for Excel spec and importer error paths
    - `backend/tests/test_excel_workbook_spec.py` — full small-deal round-trip fixture and missing-sheet/missing-column rejection
    - Fixture file `backend/tests/fixtures/sample_multifamily.xlsx` plus a `sample_multifamily_missing_s01.xlsx` variant
    - _Requirements: 12.1, 12.2, 13.2, 13.3_

- [x] 15. Implement Google Sheets export
  - [x] 15.1 Implement `backend/app/services/multifamily/google_sheets_export_service.py`
    - `export_deal_to_sheets(deal_id, oauth_token) -> str` reuses `google-api-python-client` and the existing OAuth token storage
    - Reuses the same `WORKBOOK_SHEETS` spec so sheet structure matches the Excel export
    - _Requirements: 12.5, 14.5_

  - [x] 15.2 Add `GET /deals/<id>/export/sheets` route to `multifamily_import_export_controller.py`
    - _Requirements: 12.5_

  - [ ]* 15.3 Write integration test for Google Sheets export (mocked)
    - `backend/tests/test_google_sheets_multifamily.py` uses a `google-api-python-client` mock, asserts the correct sheet structure is created
    - _Requirements: 12.5_

- [x] 16. Checkpoint — backend complete
  - Ensure all tests pass, ask the user if questions arise.
  - All 16 property tests green, all controllers wired, Excel round-trip green
  - _Validates: Backend requirements 1-15_

- [x] 17. Frontend foundation (types, API, routing, list pages)
  - [x] 17.1 Append multifamily types to `frontend/src/types/index.ts`
    - `Deal`, `Unit`, `RentRollEntry`, `MarketRentAssumption`, `RentComp`, `SaleComp`, `RehabPlanEntry`, `LenderProfile`, `DealLenderSelection`, `FundingSource`, `ProFormaResult`, `MonthlyRow`, `Dashboard`, `ImportResult`
    - Enums for `OccupancyStatus`, `LenderType`, `FundingSourceType`, `Scenario`
    - _Requirements: 14.1_

  - [x] 17.2 Append multifamily API methods to `frontend/src/services/api.ts`
    - One function per REST endpoint defined in tasks 12 and 13
    - _Requirements: 1-15 (all endpoints)_

  - [x] 17.3 Create `frontend/src/pages/multifamily/DealListPage.tsx`
    - React Query `useQuery` for `GET /api/multifamily/deals`
    - Table of deals with summary fields from Req 1.5
    - "Create Deal" button opens a dialog wired to `POST /api/multifamily/deals`
    - _Requirements: 1.5, 14.1_

  - [x] 17.4 Create `frontend/src/pages/multifamily/LenderProfilesPage.tsx`
    - CRUD UI for Lender_Profiles with per-type form (Construction_To_Perm vs Self_Funded_Reno)
    - _Requirements: 6.1-6.4, 14.1_

  - [x] 17.5 Add multifamily routes to `frontend/src/App.tsx`
    - `/multifamily/deals`, `/multifamily/deals/:id`, `/multifamily/lender-profiles`
    - Sidebar link to the multifamily section
    - _Requirements: 14.1_

  - [ ]* 17.6 Write component tests for list pages
    - `DealListPage.test.tsx`, `LenderProfilesPage.test.tsx` — render empty state, render rows, create-deal flow (mocked Axios)
    - _Requirements: 1.5, 6.1, 14.1_

- [x] 18. Frontend Deal Detail tabs
  - [x] 18.1 Create `frontend/src/pages/multifamily/DealDetailPage.tsx`
    - Tab router with eight tabs: Rent Roll, Market Rents, Sale Comps, Rehab Plan, Lenders, Funding, Pro Forma, Dashboard (Req 14.1)
    - Shared `useQuery` for `GET /deals/<id>` with React Query key `['deal', dealId]`
    - _Requirements: 14.1_

  - [x] 18.2 Create `frontend/src/components/multifamily/RentRollTab.tsx`
    - Table of units + rent roll entries, add/edit/delete dialogs wired to the API
    - Displays `RentRollSummary` (Req 2.5) including `Rent_Roll_Incomplete` warning
    - _Requirements: 2.1-2.6_

  - [x] 18.3 Create `frontend/src/components/multifamily/MarketRentsTab.tsx`
    - Per-unit-type assumption editor + rent comps list with auto-computed rent_per_sqft
    - Shows rollups (avg/median/avg_per_sqft)
    - _Requirements: 3.1-3.5_

  - [x] 18.4 Create `frontend/src/components/multifamily/SaleCompsTab.tsx`
    - Sale comps list + add/delete; displays Cap_Rate and PPU min/median/average/max; `Sale_Comps_Insufficient` warning when < 3
    - _Requirements: 4.1-4.5_

  - [x] 18.5 Create `frontend/src/components/multifamily/RehabPlanTab.tsx`
    - Per-unit rehab entry editor with Renovate_Flag toggle; monthly rollup chart (Units_Starting_Rehab_Count, Units_Offline_Count, Units_Stabilizing_Count, CapEx_Spend)
    - Shows `Stabilizes_After_Horizon` warning flag
    - _Requirements: 5.1-5.7_

  - [x] 18.6 Create `frontend/src/components/multifamily/LendersTab.tsx`
    - Select up to 3 Lender_Profiles per scenario (A, B) with one marked Primary; attach/detach; surfaces `LenderAttachmentLimitError` from the API
    - _Requirements: 6.5-6.7_

  - [x] 18.7 Create `frontend/src/components/multifamily/FundingTab.tsx`
    - Add/edit/delete Funding_Sources (Cash, HELOC_1, HELOC_2); shows draw plan and `Insufficient_Funding` warning
    - _Requirements: 7.1-7.6_

  - [x] 18.8 Create `frontend/src/components/multifamily/ProFormaTab.tsx`
    - 24-month table of MonthlyRow values (GSR, EGI, OpEx, NOI, Net_Cash_Flow, Debt_Service_A/B, CFAD_A/B, CapEx_Spend, CFAC_A/B)
    - Recharts line chart for NOI and cash flow
    - "Force recompute" button → `POST /deals/<id>/pro-forma/recompute`
    - _Requirements: 8.1-8.14_

  - [x] 18.9 Create `frontend/src/components/multifamily/DashboardTab.tsx`
    - Side-by-side Scenario_A / Scenario_B cards with every field from Req 11.1
    - When a scenario has missing_inputs, render the summary fields as "—" and display the `missing_inputs` list
    - _Requirements: 11.1, 11.2_

  - [ ]* 18.10 Write component tests for Deal Detail tabs
    - One `.test.tsx` per tab component; wrap in `QueryClientProvider` with a test `QueryClient` so cache-invalidation flows fire on mutation
    - `DealDetailPage.test.tsx` asserts the tab structure required by Req 14.1
    - _Requirements: 2-11, 14.1_

- [x] 19. Integration, performance, and Celery tests
  - [ ]* 19.1 End-to-end pro forma integration test
    - `backend/tests/test_multifamily_pro_forma_e2e.py` — create a 10-unit deal via CRUD endpoints, `GET /deals/<id>/pro-forma` and `GET /deals/<id>/dashboard`, assert response shape and numeric plausibility
    - _Requirements: 8.1-8.14, 11.1_

  - [ ]* 19.2 Dashboard performance test
    - Timed integration test seeds a 200-unit deal and asserts `GET /deals/<id>/dashboard` returns in under 500ms with warm cache
    - _Requirements: 11.3_

  - [ ]* 19.3 Excel export performance test
    - Timed integration test seeds a 200-unit deal and asserts `GET /deals/<id>/export/excel` returns in under 5s
    - _Requirements: 12.4_

  - [ ]* 19.4 Write-path timing test
    - Asserts a write to a cacheable input returns in under 50ms for a 200-unit deal (no synchronous recompute)
    - _Requirements: 15.4_

  - [ ]* 19.5 Celery bulk recompute integration test
    - Uses `CELERY_ALWAYS_EAGER=True`; asserts `recompute_all_deals` fans out and populates the cache for every deal
    - _Requirements: 15.5_

- [-] 20. Documentation and final wiring
  - [x] 20.1 Append multifamily section to `backend/API_DOCUMENTATION.md`
    - Document every endpoint from tasks 12, 13, 14, 15 with request/response schemas
    - Call out soft-warning list values (`Rent_Roll_Incomplete`, `Sale_Comps_Insufficient`, `Stabilizes_After_Horizon`, `Insufficient_Funding`, `Non_Positive_Stabilized_NOI`, `Non_Positive_Equity`)
    - _Requirements: 14.1_

  - [ ] 20.2 Add logging lines to engine per design
    - One INFO line per `compute_pro_forma` invocation with `deal_id`, `inputs_hash`, `ms_elapsed`, `cache_hit`; DEBUG for intermediate values
    - _Requirements: 14.4, 15.2_

- [x] 21. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Entire backend suite green, including all 16 property tests
  - Frontend vitest suite green
  - _Validates: Requirements 1-15_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. All property tests (tasks 3.5-3.12, 4.2, 5.2, 6.2, 7.3, 7.4, 8.1, 11.1, 14.4) are required because they are the acceptance criteria for the pure computation layer they validate.
- Each task references specific requirement clauses for traceability.
- The 16 correctness properties from the design document each map to exactly one required property-test task, tagged with the mandatory `# Feature: multifamily-underwriting-proforma, Property N: ...` docstring.
- Checkpoints at tasks 9, 16, and 21 force a user-visible moment to ensure the suite is green before advancing to the next layer.
- The plan is additive: no existing single-family code is modified. Every new file lives under `backend/app/services/multifamily/`, `backend/app/controllers/multifamily_*`, `backend/app/models/` (new files only), or `frontend/src/{pages,components}/multifamily/`.
