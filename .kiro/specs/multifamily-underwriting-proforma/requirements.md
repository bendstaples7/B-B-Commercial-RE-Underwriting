# Requirements Document

## Introduction

The Multifamily Underwriting Pro Forma feature extends the Real Estate Analysis Platform into commercial multifamily (5+ unit apartment) underwriting. Whereas the existing single-family workflow produces an ARV via comp-based valuation, the multifamily workflow values assets on stabilized Net Operating Income (NOI) divided by market cap rate, and is structured around lender-focused metrics (DSCR, LTV, Cash-on-Cash) and a time-series pro forma that models per-unit renovation and stabilization.

The feature automates the calculation logic currently encoded in the user's `B-B Commercial Multi Pro Forma v22.xlsx` workbook. It captures a per-unit rent roll, market-rent and sales comps, a staggered rehab plan, a 24-month monthly pro forma, two debt scenarios (Construction-to-Perm and Self-Funded Renovation) with up to three lenders each, and a down-payment funding waterfall (cash plus up to two HELOCs). It produces the Summary Dashboard outputs (In-Place and Stabilized NOI, DSCR, Valuation at cap rate and price-per-unit, Sources & Uses, Cash-on-Cash) and exports a lender-ready Excel workbook that mirrors the source workbook's structure.

The feature lives as a distinct commercial-multifamily track alongside the existing single-family analysis workflow. It introduces its own entity model (Deal, Unit, Rent_Roll_Entry, Rehab_Plan_Entry, Rent_Comp, Sale_Comp, Lender_Profile, Funding_Source, Pro_Forma_Result) and its own service layer. It reuses the platform's authentication, Excel export infrastructure, and Lead integration points where applicable.

## Glossary

- **Deal**: The top-level multifamily underwriting record for a single property, containing all inputs and computed outputs. Distinct from the existing single-family Lead entity.
- **Unit**: A single rentable dwelling within a Deal, identified by a user-supplied Unit_ID. Each Unit has Beds, Baths, SqFt, Unit_Type, and Occupancy_Status.
- **Rent_Roll_Entry**: The in-place rent record for a single Unit, containing Current_Rent, Lease_Start_Date, Lease_End_Date, and Notes.
- **Market_Rent_Assumption**: The target market rent per Unit_Type, with pre-renovation Target_Rent and post-renovation Post_Reno_Target_Rent.
- **Rent_Comp**: A market comparable rental used to justify Market_Rent_Assumption, with Address, Neighborhood, Unit_Type, Observed_Rent, SqFt, Rent_Per_SqFt, Observation_Date, and Source_URL.
- **Sale_Comp**: A closed sale comparable used to derive market Cap_Rate and Price_Per_Unit, with Address, Unit_Count, Status, Sale_Price, Close_Date, Observed_Cap_Rate, Observed_PPU, and Distance_Miles.
- **Rehab_Plan_Entry**: The renovation plan for a single Unit, containing Current_Rent, Suggested_Post_Reno_Rent, Underwritten_Post_Reno_Rent, Renovate_Flag, Rehab_Start_Month (integer 1–24), Downtime_Months, Rehab_Budget, Scope_Notes, and derived Stabilized_Month.
- **Stabilized_Month**: The month (integer 1–24) in which a renovated Unit begins collecting Underwritten_Post_Reno_Rent, computed as Rehab_Start_Month + Downtime_Months.
- **Gross_Scheduled_Rent (GSR)**: Sum across all Units of the scheduled rent for a given month, where scheduled rent equals Underwritten_Post_Reno_Rent when the month is at or after Stabilized_Month (for renovated Units), Current_Rent before Rehab_Start_Month, and zero during the downtime window [Rehab_Start_Month, Stabilized_Month).
- **Vacancy_And_Credit_Loss**: A monthly deduction from GSR calculated as Vacancy_Rate × GSR, where Vacancy_Rate is a Deal-level assumption.
- **Other_Income**: Non-rent monthly income (laundry, parking, fees), specified as a Deal-level monthly amount.
- **Effective_Gross_Income (EGI)**: GSR − Vacancy_And_Credit_Loss + Other_Income for a given month.
- **Operating_Expenses (OpEx)**: The sum of Property_Taxes, Insurance, Utilities, Repairs_And_Maintenance, Admin_And_Marketing, Payroll, Other_OpEx, and Management_Fee for a given month. All OpEx line items except Management_Fee are specified as annual amounts and divided by 12.
- **Management_Fee**: A monthly OpEx line calculated as Management_Fee_Rate × EGI, where Management_Fee_Rate is a Deal-level percentage.
- **Net_Operating_Income (NOI)**: EGI − OpEx for a given month, before Replacement_Reserves.
- **Replacement_Reserves**: A monthly reserve amount, specified as Reserve_Per_Unit_Per_Year × Unit_Count ÷ 12.
- **Net_Cash_Flow**: NOI − Replacement_Reserves for a given month.
- **Debt_Service**: The monthly debt payment for a given Scenario, calculated per the Scenario's lender terms (see Scenario_A and Scenario_B).
- **Cash_Flow_After_Debt**: Net_Cash_Flow − Debt_Service for a given month and Scenario.
- **CapEx_Spend**: The renovation dollars deployed in a given month, equal to the sum of Rehab_Budget across Units whose Rehab_Start_Month equals that month. (Allocation method is configurable; default is lump-sum at start.)
- **Cash_Flow_After_CapEx**: Cash_Flow_After_Debt − CapEx_Spend for a given month and Scenario.
- **In_Place_NOI**: Month 1 NOI × 12, representing the annualized current-state NOI.
- **Stabilized_NOI**: The average monthly NOI across months 13 through 24, annualized by multiplying by 12.
- **Debt_Service_Coverage_Ratio (DSCR)**: NOI ÷ Debt_Service for a given month and Scenario. In_Place_DSCR uses Month 1; Stabilized_DSCR uses Month 24.
- **Loan_To_Value (LTV)**: Loan_Amount ÷ Total_Cost_Basis for Scenario_A, or Loan_Amount ÷ Purchase_Price for Scenario_B.
- **Price_Per_Unit (PPU)**: Sale_Price ÷ Unit_Count for a sale comp, or Valuation ÷ Unit_Count for a computed valuation.
- **Price_To_Rent_Ratio**: Purchase_Price ÷ (Annualized_In_Place_GSR).
- **Cap_Rate**: NOI ÷ Property_Value, expressed as a decimal (e.g., 0.065 for 6.5%).
- **Scenario_A (Construction_To_Perm)**: A debt scenario where a single lender funds purchase plus renovation; the loan is interest-only during construction at Construction_Rate for Construction_IO_Months, then converts to amortizing at Perm_Rate over Perm_Amort_Years.
- **Scenario_B (Self_Funded_Reno)**: A debt scenario where the lender funds only the purchase at Purchase_LTV, and renovation is funded from Funding_Sources. The all-in rate is calculated as Treasury_5Y_Rate + Spread_Bps ÷ 10000.
- **Lender_Profile**: A reusable lender record containing default terms for Scenario_A or Scenario_B, selectable into a Deal.
- **Funding_Source**: A tranche of renovation capital (Cash, HELOC_1, or HELOC_2), each with Total_Available, Interest_Rate, and Origination_Fee_Rate. Funding draws in priority order Cash → HELOC_1 → HELOC_2.
- **Sources_And_Uses**: A table summarizing all capital sources (Loan_Amount, Cash, HELOC draws) against all uses (Purchase_Price, Closing_Costs, Rehab_Budget_Total, Origination_Fees, Interest_Reserve).
- **Initial_Cash_Investment**: The total cash equity required at closing plus any out-of-pocket cash required through stabilization.
- **Cash_On_Cash_Return**: Annualized Cash_Flow_After_Debt ÷ Initial_Cash_Investment for a specified period.
- **Valuation_At_Cap_Rate**: Stabilized_NOI ÷ Cap_Rate, computed at min, median, average, and max of Sale_Comp observed cap rates.
- **Valuation_At_PPU**: Unit_Count × PPU, computed at min, median, average, and max of Sale_Comp observed PPU values.
- **Pro_Forma_Result**: The full computed output for a Deal, containing the 24-month monthly schedule, summary metrics, valuation table, Sources & Uses, and per-scenario DSCR and Cash-on-Cash.
- **Dashboard**: The Summary view showing side-by-side Scenario_A and Scenario_B outputs for a Deal.

## Requirements

### Requirement 1: Deal Management

**User Story:** As an investor, I want to create and manage multifamily Deal records, so that I can underwrite apartment properties separately from my single-family lead pipeline.

#### Acceptance Criteria

1. WHEN a user submits a new Deal with Property_Address, Unit_Count (integer ≥ 5), Purchase_Price, and Close_Date, THE Deal_Service SHALL persist a Deal record and return the Deal_ID.
2. IF a user submits a Deal with Unit_Count less than 5, THEN THE Deal_Service SHALL reject the request with a validation error identifying Unit_Count as out of range.
3. IF a user submits a Deal with a non-positive Purchase_Price, THEN THE Deal_Service SHALL reject the request with a validation error.
4. WHEN a user requests a Deal by Deal_ID, THE Deal_Service SHALL return the complete Deal record including all Units, Rent_Roll_Entries, Rent_Comps, Sale_Comps, Rehab_Plan_Entries, Lender_Profile selections, and Funding_Sources.
5. WHEN a user requests a list of Deals, THE Deal_Service SHALL return all Deals owned by the requesting user with summary fields Property_Address, Unit_Count, Purchase_Price, Status, Created_At, and Updated_At.
6. WHEN a user updates any field on a Deal, THE Deal_Service SHALL persist the change and update the Updated_At timestamp.
7. WHEN a user deletes a Deal, THE Deal_Service SHALL soft-delete the Deal and all associated child records.
8. WHERE an existing single-family Lead record corresponds to the same Property_Address, THE Deal_Service SHALL offer to link the Deal to the Lead so enrichment data is shared.

### Requirement 2: Rent Roll Capture

**User Story:** As an investor, I want to enter the per-unit in-place rent roll, so that the platform can compute current gross scheduled rent and occupancy.

#### Acceptance Criteria

1. WHEN a user adds a Unit to a Deal with Unit_ID, Unit_Type, Beds, Baths, SqFt, and Occupancy_Status in {Occupied, Vacant, Down}, THE Rent_Roll_Service SHALL persist the Unit and return the Unit_ID.
2. IF a user adds a Unit with a Unit_ID that already exists within the same Deal, THEN THE Rent_Roll_Service SHALL reject the request with a duplicate-identifier error.
3. WHEN a user sets Current_Rent, Lease_Start_Date, Lease_End_Date, and Notes on a Rent_Roll_Entry, THE Rent_Roll_Service SHALL persist the entry.
4. IF Lease_End_Date precedes Lease_Start_Date on a Rent_Roll_Entry, THEN THE Rent_Roll_Service SHALL reject the request with a validation error.
5. WHEN the rent roll for a Deal is queried, THE Rent_Roll_Service SHALL return Total_Unit_Count, Occupied_Unit_Count, Vacant_Unit_Count, Occupancy_Rate (Occupied_Unit_Count ÷ Total_Unit_Count), Total_In_Place_Rent (sum of Current_Rent across Occupied Units), and Average_Rent_Per_Occupied_Unit.
6. WHEN the number of Rent_Roll_Entries for a Deal is less than the Deal's Unit_Count, THE Rent_Roll_Service SHALL flag the Deal with a Rent_Roll_Incomplete status.

### Requirement 3: Market Rent Assumptions and Rent Comps

**User Story:** As an investor, I want to record market rent assumptions and supporting rent comps, so that post-renovation rents used in the pro forma are defensible.

#### Acceptance Criteria

1. WHEN a user sets Market_Rent_Assumption for a Unit_Type with Target_Rent and Post_Reno_Target_Rent, THE Market_Rent_Service SHALL persist the assumption keyed by (Deal_ID, Unit_Type).
2. WHEN a user adds a Rent_Comp with Address, Neighborhood, Unit_Type, Observed_Rent, SqFt, Observation_Date, and optional Source_URL, THE Market_Rent_Service SHALL persist the Rent_Comp and compute Rent_Per_SqFt as Observed_Rent ÷ SqFt.
3. IF a user adds a Rent_Comp with SqFt equal to zero, THEN THE Market_Rent_Service SHALL reject the request with a validation error.
4. WHEN Rent_Comps for a Deal are queried by Unit_Type, THE Market_Rent_Service SHALL return Average_Observed_Rent, Median_Observed_Rent, Average_Rent_Per_SqFt, and the full list of Rent_Comps.
5. WHEN a user does not supply a Target_Rent or Post_Reno_Target_Rent for a Unit_Type, THE Market_Rent_Service SHALL default those values to the Average_Observed_Rent for that Unit_Type if at least three Rent_Comps exist.

### Requirement 4: Sale Comps and Cap Rate Derivation

**User Story:** As an investor, I want to record sales comparables, so that the platform can derive market Cap_Rate and Price_Per_Unit used in valuation.

#### Acceptance Criteria

1. WHEN a user adds a Sale_Comp with Address, Unit_Count, Status, Sale_Price, Close_Date, Observed_Cap_Rate, and Distance_Miles, THE Sale_Comp_Service SHALL persist the Sale_Comp and compute Observed_PPU as Sale_Price ÷ Unit_Count.
2. IF a user adds a Sale_Comp with Unit_Count equal to zero, THEN THE Sale_Comp_Service SHALL reject the request with a validation error.
3. IF a user adds a Sale_Comp with Observed_Cap_Rate less than or equal to zero or greater than 0.25, THEN THE Sale_Comp_Service SHALL reject the request with an out-of-range error identifying Observed_Cap_Rate.
4. WHEN Sale_Comps for a Deal are queried, THE Sale_Comp_Service SHALL return Cap_Rate_Min, Cap_Rate_Median, Cap_Rate_Average, Cap_Rate_Max, PPU_Min, PPU_Median, PPU_Average, PPU_Max, and the full list of Sale_Comps.
5. WHEN fewer than three Sale_Comps exist for a Deal, THE Sale_Comp_Service SHALL flag the Deal with a Sale_Comps_Insufficient warning.

### Requirement 5: Rehab Plan and Timing

**User Story:** As an investor, I want to schedule per-unit renovations across a 24-month horizon, so that the pro forma reflects staggered downtime and stabilization.

#### Acceptance Criteria

1. WHEN a user sets a Rehab_Plan_Entry for a Unit with Renovate_Flag, Rehab_Start_Month, Downtime_Months, Rehab_Budget, Suggested_Post_Reno_Rent, Underwritten_Post_Reno_Rent, and Scope_Notes, THE Rehab_Service SHALL persist the entry and compute Stabilized_Month as Rehab_Start_Month + Downtime_Months.
2. IF Rehab_Start_Month is outside the range [1, 24], THEN THE Rehab_Service SHALL reject the request with an out-of-range error.
3. IF Downtime_Months is negative, THEN THE Rehab_Service SHALL reject the request with an out-of-range error.
4. IF Rehab_Start_Month + Downtime_Months exceeds 24, THEN THE Rehab_Service SHALL accept the entry and flag the Unit with a Stabilizes_After_Horizon warning so the user is aware the Unit will not contribute stabilized rent within the 24-month pro forma.
5. WHEN a Rehab_Plan_Entry has Renovate_Flag equal to false, THE Rehab_Service SHALL ignore Rehab_Start_Month, Downtime_Months, and Rehab_Budget for that Unit and set Stabilized_Month to null.
6. WHEN the rehab schedule for a Deal is queried, THE Rehab_Service SHALL return a monthly rollup for months 1–24 with Units_Starting_Rehab_Count, Units_Offline_Count, Units_Stabilizing_Count, and CapEx_Spend per month.
7. WHEN the total CapEx is queried, THE Rehab_Service SHALL return Rehab_Budget_Total as the sum of Rehab_Budget across Units where Renovate_Flag is true.

### Requirement 6: Lender Profiles

**User Story:** As an investor, I want to maintain reusable lender assumption profiles, so that I can compare up to three lenders per scenario across multiple Deals without re-entering terms.

#### Acceptance Criteria

1. WHEN a user creates a Lender_Profile of type Construction_To_Perm with Company, LTV_Total_Cost, Origination_Fee_Rate, Construction_Rate, Construction_IO_Months, Construction_Term_Months, Perm_Rate, Perm_Amort_Years, Prepay_Penalty_Description, and Min_Interest_Or_Yield, THE Lender_Service SHALL persist the profile.
2. WHEN a user creates a Lender_Profile of type Self_Funded_Reno with Company, Max_Purchase_LTV, Origination_Fee_Rate, Treasury_5Y_Rate, Spread_Bps, Term_Years, Amort_Years, and Prepay_Penalty_Description, THE Lender_Service SHALL persist the profile and compute All_In_Rate as Treasury_5Y_Rate + Spread_Bps ÷ 10000.
3. IF a user creates a Lender_Profile with any rate outside the range [0, 0.30], THEN THE Lender_Service SHALL reject the request with an out-of-range error.
4. IF a user creates a Lender_Profile with LTV outside the range [0, 1], THEN THE Lender_Service SHALL reject the request with an out-of-range error.
5. WHEN a user attaches up to three Lender_Profiles of type Construction_To_Perm to a Deal's Scenario_A, THE Deal_Service SHALL persist the selections and allow one to be marked Primary.
6. WHEN a user attaches up to three Lender_Profiles of type Self_Funded_Reno to a Deal's Scenario_B, THE Deal_Service SHALL persist the selections and allow one to be marked Primary.
7. IF a user attempts to attach more than three Lender_Profiles to a single Scenario on a Deal, THEN THE Deal_Service SHALL reject the request with a limit-exceeded error.

### Requirement 7: Down Payment Funding Waterfall

**User Story:** As an investor, I want to model my cash-stack funding sources, so that origination fees and carrying interest from HELOCs flow into the pro forma.

#### Acceptance Criteria

1. WHEN a user adds a Funding_Source to a Deal with Source_Type in {Cash, HELOC_1, HELOC_2}, Total_Available, Interest_Rate, and Origination_Fee_Rate, THE Funding_Service SHALL persist the Funding_Source.
2. IF a user adds two Funding_Sources with the same Source_Type to the same Deal, THEN THE Funding_Service SHALL reject the second request with a duplicate-source error.
3. WHEN Required_Equity for a Deal is computed, THE Funding_Service SHALL draw from Funding_Sources in priority order Cash → HELOC_1 → HELOC_2, capping each draw at the Source's Total_Available, and return the per-source draw amounts.
4. IF Required_Equity exceeds the sum of Total_Available across all Funding_Sources, THEN THE Funding_Service SHALL flag the Deal with an Insufficient_Funding warning identifying the shortfall amount.
5. WHEN Origination_Fees for Funding_Sources are computed, THE Funding_Service SHALL return the sum of (Draw_Amount × Origination_Fee_Rate) across all Funding_Sources with non-zero draws.
6. WHEN HELOC carrying interest is computed for a given month, THE Funding_Service SHALL return the sum of (Outstanding_Draw × Interest_Rate ÷ 12) for HELOC_1 and HELOC_2, using the outstanding balance at the start of that month.

### Requirement 8: 24-Month Pro Forma Engine

**User Story:** As an investor, I want the platform to compute a 24-month monthly pro forma from my inputs, so that I can see rent ramp, NOI, debt service, DSCR, and cash flow without touching a spreadsheet.

#### Acceptance Criteria

1. WHEN a user requests a Pro_Forma_Result for a Deal, THE Pro_Forma_Engine SHALL compute, for each month M in {1..24}, the per-Unit scheduled rent using the rule: if Renovate_Flag is false, scheduled rent equals Current_Rent; else if M < Rehab_Start_Month, scheduled rent equals Current_Rent; else if Rehab_Start_Month ≤ M < Stabilized_Month, scheduled rent equals zero; else scheduled rent equals Underwritten_Post_Reno_Rent.
2. WHEN computing monthly GSR, THE Pro_Forma_Engine SHALL sum the per-Unit scheduled rent across all Units for that month.
3. WHEN computing monthly EGI, THE Pro_Forma_Engine SHALL apply EGI = GSR − (Vacancy_Rate × GSR) + Other_Income.
4. WHEN computing monthly OpEx, THE Pro_Forma_Engine SHALL sum Property_Taxes_Annual ÷ 12, Insurance_Annual ÷ 12, Utilities_Annual ÷ 12, Repairs_And_Maintenance_Annual ÷ 12, Admin_And_Marketing_Annual ÷ 12, Payroll_Annual ÷ 12, Other_OpEx_Annual ÷ 12, and Management_Fee_Rate × EGI.
5. WHEN computing monthly NOI, THE Pro_Forma_Engine SHALL apply NOI = EGI − OpEx.
6. WHEN computing monthly Net_Cash_Flow, THE Pro_Forma_Engine SHALL apply Net_Cash_Flow = NOI − Replacement_Reserves, where Replacement_Reserves = Reserve_Per_Unit_Per_Year × Unit_Count ÷ 12.
7. WHEN computing monthly Debt_Service for Scenario_A, THE Pro_Forma_Engine SHALL use interest-only payment equal to Loan_Amount × Construction_Rate ÷ 12 for months 1 through Construction_IO_Months, and amortizing payment computed by the standard mortgage formula P × (r × (1+r)^n) ÷ ((1+r)^n − 1) with r = Perm_Rate ÷ 12 and n = Perm_Amort_Years × 12 for months after Construction_IO_Months.
8. WHEN computing monthly Debt_Service for Scenario_B, THE Pro_Forma_Engine SHALL use the amortizing payment formula with r = All_In_Rate ÷ 12 and n = Amort_Years × 12 applied for all 24 months.
9. WHEN computing monthly Cash_Flow_After_Debt, THE Pro_Forma_Engine SHALL apply Cash_Flow_After_Debt = Net_Cash_Flow − Debt_Service for each Scenario independently.
10. WHEN computing monthly CapEx_Spend, THE Pro_Forma_Engine SHALL sum Rehab_Budget across Units whose Rehab_Start_Month equals the current month (default lump-sum allocation).
11. WHEN computing monthly Cash_Flow_After_CapEx, THE Pro_Forma_Engine SHALL apply Cash_Flow_After_CapEx = Cash_Flow_After_Debt − CapEx_Spend for each Scenario independently.
12. WHEN computing annualized summary metrics, THE Pro_Forma_Engine SHALL return In_Place_NOI = Month_1_NOI × 12, Stabilized_NOI = Average(Month_13_NOI..Month_24_NOI) × 12, In_Place_DSCR = Month_1_NOI ÷ Month_1_Debt_Service per Scenario, and Stabilized_DSCR = Month_24_NOI ÷ Month_24_Debt_Service per Scenario.
13. IF Month_1_Debt_Service or Month_24_Debt_Service equals zero for a Scenario, THEN THE Pro_Forma_Engine SHALL report the corresponding DSCR as null rather than dividing by zero.
14. WHEN any required input (Rent_Roll, Rehab_Plan, OpEx assumptions, or an attached Primary Lender_Profile) is missing for a Scenario, THE Pro_Forma_Engine SHALL return a Pro_Forma_Result with a Missing_Inputs list identifying each absent input rather than raising an exception.

### Requirement 9: Valuation Engine

**User Story:** As an investor, I want the platform to compute stabilized valuation at cap rate and price-per-unit, so that I can compare the stabilized value against purchase price.

#### Acceptance Criteria

1. WHEN a user requests a Valuation for a Deal, THE Valuation_Engine SHALL compute Valuation_At_Cap_Rate as Stabilized_NOI ÷ Cap_Rate for each of Cap_Rate_Min, Cap_Rate_Median, Cap_Rate_Average, and Cap_Rate_Max derived from the Deal's Sale_Comps.
2. WHEN a user requests a Valuation for a Deal, THE Valuation_Engine SHALL compute Valuation_At_PPU as Unit_Count × PPU for each of PPU_Min, PPU_Median, PPU_Average, and PPU_Max derived from the Deal's Sale_Comps.
3. WHEN a user provides a Custom_Cap_Rate override, THE Valuation_Engine SHALL additionally return Valuation_At_Custom_Cap_Rate = Stabilized_NOI ÷ Custom_Cap_Rate.
4. IF Stabilized_NOI is less than or equal to zero, THEN THE Valuation_Engine SHALL return Valuation_At_Cap_Rate values as null and flag the Deal with a Non_Positive_Stabilized_NOI warning.
5. WHEN a Valuation is returned, THE Valuation_Engine SHALL include Price_To_Rent_Ratio = Purchase_Price ÷ (Month_1_GSR × 12).

### Requirement 10: Sources & Uses and Cash-on-Cash

**User Story:** As an investor, I want to see Sources & Uses and Cash-on-Cash returns for each scenario, so that I can evaluate the equity check and return on cash invested.

#### Acceptance Criteria

1. WHEN a Sources_And_Uses is computed for a Scenario, THE Pro_Forma_Engine SHALL return Uses including Purchase_Price, Closing_Costs, Rehab_Budget_Total, Loan_Origination_Fees, Funding_Source_Origination_Fees, and Interest_Reserve.
2. WHEN a Sources_And_Uses is computed for a Scenario, THE Pro_Forma_Engine SHALL return Sources including Loan_Amount per the Scenario's Primary Lender_Profile, and per-source draws from Funding_Sources in the priority order defined in Requirement 7.
3. WHEN Loan_Amount is computed for Scenario_A, THE Pro_Forma_Engine SHALL apply Loan_Amount = LTV_Total_Cost × (Purchase_Price + Closing_Costs + Rehab_Budget_Total).
4. WHEN Loan_Amount is computed for Scenario_B, THE Pro_Forma_Engine SHALL apply Loan_Amount = Max_Purchase_LTV × Purchase_Price.
5. WHEN Initial_Cash_Investment is computed for a Scenario, THE Pro_Forma_Engine SHALL return Total_Uses − Loan_Amount.
6. WHEN Cash_On_Cash_Return is computed for a Scenario, THE Pro_Forma_Engine SHALL return Stabilized_Annual_Cash_Flow_After_Debt ÷ Initial_Cash_Investment, where Stabilized_Annual_Cash_Flow_After_Debt equals the sum of Cash_Flow_After_Debt across months 13–24.
7. IF Initial_Cash_Investment is less than or equal to zero, THEN THE Pro_Forma_Engine SHALL report Cash_On_Cash_Return as null and flag the Scenario with a Non_Positive_Equity warning.

### Requirement 11: Summary Dashboard

**User Story:** As an investor, I want a side-by-side summary of both debt scenarios, so that I can evaluate Construction-to-Perm vs Self-Funded Renovation at a glance.

#### Acceptance Criteria

1. WHEN a user requests the Dashboard for a Deal, THE Dashboard_Service SHALL return, for each of Scenario_A and Scenario_B: Purchase_Price, Loan_Amount, Interest_Rate (Construction_Rate for A, All_In_Rate for B), Amort_Years, IO_Period_Months, In_Place_NOI, Stabilized_NOI, In_Place_DSCR, Stabilized_DSCR, Price_To_Rent_Ratio, Valuation_At_Cap_Rate (min, median, average, max), Valuation_At_PPU (min, median, average, max), Sources_And_Uses, Initial_Cash_Investment, Month_1_Net_Cash_Flow, Month_24_Net_Cash_Flow, and Cash_On_Cash_Return.
2. WHEN any Scenario has a Missing_Inputs list, THE Dashboard_Service SHALL return the Scenario's summary fields as null and include the Missing_Inputs list in the response.
3. WHEN the Dashboard is requested, THE Dashboard_Service SHALL complete in under 500 milliseconds for a Deal with up to 200 Units assuming a pre-computed Pro_Forma_Result is cached.

### Requirement 12: Excel Export

**User Story:** As an investor, I want to export a lender-ready Excel workbook matching my current format, so that I can share deals with lenders and partners without reformatting.

#### Acceptance Criteria

1. WHEN a user requests an Excel export of a Deal, THE Export_Service SHALL produce a workbook containing sheets named S00a_Summary_ScenarioA, S00b_Summary_ScenarioB, S01_RentRoll_InPlace, S02_MarketRents_Comps, S03_SaleComps_CapRates, S04_Rehab_Timing, S05_ProForma_24mo, S06_Valuation, S07_Lender_Assumptions, and Funding_Sources.
2. WHEN the Excel export is generated, THE Export_Service SHALL populate each sheet with the data fields defined in Requirements 1 through 11 in the order defined by the source workbook `B-B Commercial Multi Pro Forma v22.xlsx`.
3. WHEN the Excel export is generated, THE Export_Service SHALL include all computed values from the Pro_Forma_Result rather than writing formulas, so that recipients without formula access can view the numbers.
4. WHEN the Excel export is generated, THE Export_Service SHALL return the workbook as a downloadable .xlsx file within 5 seconds for a Deal with up to 200 Units.
5. WHERE a user has connected a Google Sheets account, THE Export_Service SHALL additionally offer export to a new Google Sheets document with identical sheet structure.

### Requirement 13: Excel Import (Round-Trip)

**User Story:** As an investor, I want to import my existing Excel pro forma workbook into the platform, so that I can automate deals I have already started without re-entering data.

#### Acceptance Criteria

1. WHEN a user uploads a workbook matching the `B-B Commercial Multi Pro Forma v22.xlsx` sheet structure, THE Import_Service SHALL parse sheets S01 through S07 and the Funding Sources tab into a Deal with Units, Rent_Roll_Entries, Rent_Comps, Sale_Comps, Rehab_Plan_Entries, Lender_Profiles, and Funding_Sources.
2. IF a required sheet is missing from the uploaded workbook, THEN THE Import_Service SHALL reject the upload with an error identifying the missing sheet by name.
3. IF a required column is missing from a recognized sheet, THEN THE Import_Service SHALL reject the upload with an error identifying the missing column and sheet.
4. WHEN an import succeeds, THE Import_Service SHALL return the Deal_ID and a parse report listing each sheet with rows parsed, rows skipped, and any warnings.
5. FOR ALL valid Deals produced by the platform, exporting the Deal to Excel and re-importing the resulting workbook SHALL produce an equivalent Deal where equivalence is defined as identical values in Units, Rent_Roll_Entries, Rent_Comps, Sale_Comps, Rehab_Plan_Entries, Lender_Profiles, and Funding_Sources (round-trip property).

### Requirement 14: Platform Integration

**User Story:** As an investor, I want multifamily Deals to integrate with the existing platform, so that I can navigate from my lead pipeline into underwriting without a separate login or data silo.

#### Acceptance Criteria

1. WHEN a user navigates the platform, THE Frontend SHALL expose a Multifamily section with routes for Deal list, Deal detail (with tabs for Rent Roll, Market Rents, Sale Comps, Rehab Plan, Lenders, Funding, Pro Forma, Dashboard), and Lender Profiles.
2. WHEN a user creates a Deal from an existing Lead record, THE Deal_Service SHALL pre-populate Property_Address from the Lead and create a bidirectional link between the Lead and the Deal.
3. WHEN a user has permission to access a Lead, THE Deal_Service SHALL grant the user permission to access any Deal linked to that Lead.
4. WHEN a Deal is created or updated, THE Deal_Service SHALL log the action to the existing audit trail with user identity, timestamp, and changed fields.
5. WHERE the platform's existing Excel export infrastructure (openpyxl) is available, THE Export_Service SHALL reuse that infrastructure rather than introducing a second Excel library.

### Requirement 15: Pro Forma Persistence and Recomputation

**User Story:** As an investor, I want computed pro forma results cached and automatically refreshed when inputs change, so that the dashboard loads quickly and never shows stale numbers.

#### Acceptance Criteria

1. WHEN a Pro_Forma_Result is computed for a Deal, THE Pro_Forma_Engine SHALL persist the result with a Computed_At timestamp and an Inputs_Hash derived from the Deal's current inputs.
2. WHEN a user requests a Pro_Forma_Result and the stored Inputs_Hash matches the Deal's current Inputs_Hash, THE Pro_Forma_Engine SHALL return the cached result.
3. WHEN a user updates any input that affects the pro forma (Rent_Roll_Entry, Rehab_Plan_Entry, OpEx assumption, Lender_Profile selection, Funding_Source, Purchase_Price, Closing_Costs, Vacancy_Rate, Other_Income, Management_Fee_Rate, or Reserve_Per_Unit_Per_Year), THE Deal_Service SHALL invalidate the cached Pro_Forma_Result.
4. WHEN a cached Pro_Forma_Result is invalidated, THE Pro_Forma_Engine SHALL recompute the result on the next request rather than on the write, so that write requests remain fast.
5. WHERE a bulk recomputation is requested across many Deals, THE Pro_Forma_Engine SHALL enqueue the work to Celery rather than blocking the request.
