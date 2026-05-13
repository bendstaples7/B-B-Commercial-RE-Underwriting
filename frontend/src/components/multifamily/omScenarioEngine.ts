/**
 * TypeScript mirror of the Python `compute_scenarios` function from
 * `backend/app/services/om_intake/scenario_engine.py`.
 *
 * This module is a pure-function scenario computation engine for the
 * Commercial OM PDF Intake pipeline. It has no I/O, no side effects, and
 * uses `number | null` arithmetic with explicit null/zero guards that
 * exactly match the Python zero-guard rules.
 *
 * The frontend uses this module to recalculate scenario metrics within
 * 300 ms when a user edits a field in the Intake Review UI, without a
 * server round-trip.
 *
 * Requirements: 6.3, 6.4, 6.5
 */

// ---------------------------------------------------------------------------
// Input types
// ---------------------------------------------------------------------------

export interface UnitMixInput {
  unit_type_label: string
  unit_count: number
  sqft: number
  current_avg_rent: number | null
  proforma_rent: number | null
  market_rent_estimate: number | null
  market_rent_low?: number | null
  market_rent_high?: number | null
}

export interface OtherIncomeInput {
  label: string
  annual_amount: number
}

export interface ScenarioEngineInputs {
  unit_mix: UnitMixInput[]
  proforma_vacancy_rate: number
  proforma_gross_expenses: number | null
  other_income_items: OtherIncomeInput[]
  asking_price: number | null
  // Broker-stated aggregates
  current_gross_potential_income: number | null
  current_effective_gross_income: number | null
  current_gross_expenses: number | null
  current_noi: number | null
  current_vacancy_rate: number | null
  proforma_gross_potential_income: number | null
  proforma_effective_gross_income: number | null
  proforma_noi: number | null
  // Financing (optional)
  loan_amount?: number | null
  interest_rate?: number | null
  debt_service_annual?: number | null
}

// ---------------------------------------------------------------------------
// Output types
// ---------------------------------------------------------------------------

export interface ScenarioMetricsOutput {
  gross_potential_income_annual: number | null
  effective_gross_income_annual: number | null
  gross_expenses_annual: number | null
  noi_annual: number | null
  cap_rate: number | null
  grm: number | null
  monthly_rent_total: number | null
  dscr: number | null
  cash_on_cash: null  // always null (requires equity data)
}

export interface ScenarioComparisonOutput {
  broker_current: ScenarioMetricsOutput
  broker_proforma: ScenarioMetricsOutput
  realistic: ScenarioMetricsOutput
  significant_variance_flag: boolean | null
  realistic_cap_rate_below_proforma: boolean | null
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Safe division: returns `numerator / denominator`, or `null` if either
 * operand is `null` or the denominator is zero.
 *
 * This is the single point of truth for all division operations in the
 * engine, enforcing the zero-guard rules from Requirements 4.7, 4.8, 5.8, 5.9.
 */
function safeDiv(numerator: number | null, denominator: number | null): number | null {
  if (numerator === null || denominator === null) return null
  if (denominator === 0) return null
  return numerator / denominator
}

/**
 * Compute DSCR only when financing data is fully available.
 *
 * Requirements 5.3: only compute if `loan_amount > 0` AND
 * `interest_rate > 0` AND `debt_service_annual > 0`.
 */
function computeDSCR(
  noiAnnual: number | null,
  debtServiceAnnual: number | null | undefined,
  loanAmount: number | null | undefined,
  interestRate: number | null | undefined,
): number | null {
  if (loanAmount == null || loanAmount <= 0) return null
  if (interestRate == null || interestRate <= 0) return null
  if (debtServiceAnnual == null || debtServiceAnnual <= 0) return null
  return safeDiv(noiAnnual, debtServiceAnnual)
}

// ---------------------------------------------------------------------------
// Exported formula functions
// ---------------------------------------------------------------------------

/**
 * realistic_gpi = sum(market_rent_estimate * unit_count) * 12
 *
 * Returns `null` if ANY `market_rent_estimate` is null.
 *
 * Requirements: 4.4
 */
export function computeRealisticGPI(unitMix: UnitMixInput[]): number | null {
  let total = 0
  for (const row of unitMix) {
    if (row.market_rent_estimate === null || row.market_rent_estimate === undefined) {
      return null
    }
    total += row.market_rent_estimate * row.unit_count
  }
  return total * 12
}

/**
 * realistic_egi = realistic_gpi * (1 - vacancy_rate) + sum(other_income annual)
 *
 * Returns `null` if `realisticGPI` is null.
 *
 * Requirements: 4.5
 */
export function computeRealisticEGI(
  realisticGPI: number | null,
  proformaVacancyRate: number,
  otherIncomeItems: OtherIncomeInput[],
): number | null {
  if (realisticGPI === null) return null
  const otherIncome = otherIncomeItems.reduce((sum, item) => sum + item.annual_amount, 0)
  return realisticGPI * (1 - proformaVacancyRate) + otherIncome
}

/**
 * realistic_noi = realistic_egi - proforma_gross_expenses
 *
 * Returns `null` if either operand is null.
 *
 * Requirements: 4.6
 */
export function computeRealisticNOI(
  realisticEGI: number | null,
  proformaGrossExpenses: number | null,
): number | null {
  if (realisticEGI === null || proformaGrossExpenses === null) return null
  return realisticEGI - proformaGrossExpenses
}

/**
 * cap_rate = noi / asking_price
 *
 * Returns `null` if `askingPrice` is null or 0, or if `noi` is null.
 *
 * Requirements: 4.7, 5.8
 */
export function computeCapRate(
  noi: number | null,
  askingPrice: number | null,
): number | null {
  if (askingPrice === null || askingPrice === 0) return null
  return safeDiv(noi, askingPrice)
}

/**
 * grm = asking_price / gpi
 *
 * Returns `null` if `gpi` is null or 0, or if `askingPrice` is null.
 *
 * Requirements: 4.8, 5.9
 */
export function computeGRM(
  askingPrice: number | null,
  gpi: number | null,
): number | null {
  if (gpi === null || gpi === 0) return null
  return safeDiv(askingPrice, gpi)
}

/**
 * significant_variance_flag:
 *   |realistic_noi - proforma_noi| / |proforma_noi| > 0.10
 *
 * Returns `null` if `proformaNOI` is null or 0, or if `realisticNOI` is null.
 *
 * Requirements: 5.4, 5.5
 */
export function computeSignificantVarianceFlag(
  realisticNOI: number | null,
  proformaNOI: number | null,
): boolean | null {
  if (proformaNOI === null || proformaNOI === 0) return null
  if (realisticNOI === null) return null
  const variance = Math.abs(realisticNOI - proformaNOI) / Math.abs(proformaNOI)
  return variance > 0.10
}

/**
 * realistic_cap_rate_below_proforma: realistic_cap_rate < proforma_cap_rate
 *
 * Returns `null` if either cap rate is null.
 *
 * Requirements: 5.6
 */
export function computeRealisticCapRateBelowProforma(
  realisticCapRate: number | null,
  proformaCapRate: number | null,
): boolean | null {
  if (realisticCapRate === null || proformaCapRate === null) return null
  return realisticCapRate < proformaCapRate
}

// ---------------------------------------------------------------------------
// Internal monthly rent total helpers (mirrors Python broker helpers)
// ---------------------------------------------------------------------------

/**
 * monthly_rent_total for the realistic scenario:
 *   sum(market_rent_estimate * unit_count)
 *
 * Returns `null` if ANY `market_rent_estimate` is null.
 */
function computeRealisticMonthlyRentTotal(unitMix: UnitMixInput[]): number | null {
  let total = 0
  for (const row of unitMix) {
    if (row.market_rent_estimate === null || row.market_rent_estimate === undefined) {
      return null
    }
    total += row.market_rent_estimate * row.unit_count
  }
  return total
}

/**
 * monthly_rent_total for the broker current scenario:
 *   sum(current_avg_rent * unit_count)
 *
 * Returns `null` if ANY `current_avg_rent` is null.
 */
function computeBrokerCurrentMonthlyRentTotal(unitMix: UnitMixInput[]): number | null {
  let total = 0
  for (const row of unitMix) {
    if (row.current_avg_rent === null || row.current_avg_rent === undefined) {
      return null
    }
    total += row.current_avg_rent * row.unit_count
  }
  return total
}

/**
 * monthly_rent_total for the broker proforma scenario:
 *   sum(proforma_rent * unit_count)
 *
 * Returns `null` if ANY `proforma_rent` is null.
 */
function computeBrokerProformaMonthlyRentTotal(unitMix: UnitMixInput[]): number | null {
  let total = 0
  for (const row of unitMix) {
    if (row.proforma_rent === null || row.proforma_rent === undefined) {
      return null
    }
    total += row.proforma_rent * row.unit_count
  }
  return total
}

// ---------------------------------------------------------------------------
// Main function
// ---------------------------------------------------------------------------

/**
 * Compute all three scenarios from the given inputs.
 *
 * This is a pure function: given the same `inputs` it always returns the
 * same `ScenarioComparisonOutput`. It performs no I/O and has no side effects.
 *
 * Mirrors `compute_scenarios` in
 * `backend/app/services/om_intake/scenario_engine.py`.
 *
 * Requirements: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.2, 5.3, 5.4, 5.5, 5.6,
 *               5.7, 5.8, 5.9, 6.3, 6.4, 6.5
 */
export function computeScenarios(inputs: ScenarioEngineInputs): ScenarioComparisonOutput {
  const {
    unit_mix,
    proforma_vacancy_rate,
    proforma_gross_expenses,
    other_income_items,
    asking_price,
    current_gross_potential_income,
    current_effective_gross_income,
    current_gross_expenses,
    current_noi,
    proforma_gross_potential_income,
    proforma_effective_gross_income,
    proforma_noi,
    loan_amount,
    interest_rate,
    debt_service_annual,
  } = inputs

  // ------------------------------------------------------------------
  // Realistic scenario
  // ------------------------------------------------------------------
  const realisticGPI = computeRealisticGPI(unit_mix)
  const realisticEGI = computeRealisticEGI(realisticGPI, proforma_vacancy_rate, other_income_items)
  const realisticNOI = computeRealisticNOI(realisticEGI, proforma_gross_expenses)

  const realisticCapRate = computeCapRate(realisticNOI, asking_price)
  const realisticGRM = computeGRM(asking_price, realisticGPI)
  const realisticMonthlyRentTotal = computeRealisticMonthlyRentTotal(unit_mix)
  const realisticDSCR = computeDSCR(realisticNOI, debt_service_annual, loan_amount, interest_rate)

  const realistic: ScenarioMetricsOutput = {
    gross_potential_income_annual: realisticGPI,
    effective_gross_income_annual: realisticEGI,
    gross_expenses_annual: proforma_gross_expenses,
    noi_annual: realisticNOI,
    cap_rate: realisticCapRate,
    grm: realisticGRM,
    monthly_rent_total: realisticMonthlyRentTotal,
    dscr: realisticDSCR,
    cash_on_cash: null,
  }

  // ------------------------------------------------------------------
  // Broker current scenario
  // ------------------------------------------------------------------
  const currentCapRate = computeCapRate(current_noi, asking_price)
  const currentGRM = computeGRM(asking_price, current_gross_potential_income)
  const currentMonthlyRentTotal = computeBrokerCurrentMonthlyRentTotal(unit_mix)
  const currentDSCR = computeDSCR(current_noi, debt_service_annual, loan_amount, interest_rate)

  const brokerCurrent: ScenarioMetricsOutput = {
    gross_potential_income_annual: current_gross_potential_income,
    effective_gross_income_annual: current_effective_gross_income,
    gross_expenses_annual: current_gross_expenses,
    noi_annual: current_noi,
    cap_rate: currentCapRate,
    grm: currentGRM,
    monthly_rent_total: currentMonthlyRentTotal,
    dscr: currentDSCR,
    cash_on_cash: null,
  }

  // ------------------------------------------------------------------
  // Broker proforma scenario
  // ------------------------------------------------------------------
  const proformaCapRate = computeCapRate(proforma_noi, asking_price)
  const proformaGRM = computeGRM(asking_price, proforma_gross_potential_income)
  const proformaMonthlyRentTotal = computeBrokerProformaMonthlyRentTotal(unit_mix)
  const proformaDSCR = computeDSCR(proforma_noi, debt_service_annual, loan_amount, interest_rate)

  const brokerProforma: ScenarioMetricsOutput = {
    gross_potential_income_annual: proforma_gross_potential_income,
    effective_gross_income_annual: proforma_effective_gross_income,
    gross_expenses_annual: proforma_gross_expenses,
    noi_annual: proforma_noi,
    cap_rate: proformaCapRate,
    grm: proformaGRM,
    monthly_rent_total: proformaMonthlyRentTotal,
    dscr: proformaDSCR,
    cash_on_cash: null,
  }

  // ------------------------------------------------------------------
  // Flags
  // ------------------------------------------------------------------
  const significantVarianceFlag = computeSignificantVarianceFlag(realisticNOI, proforma_noi)
  const realisticCapRateBelowProforma = computeRealisticCapRateBelowProforma(
    realisticCapRate,
    proformaCapRate,
  )

  return {
    broker_current: brokerCurrent,
    broker_proforma: brokerProforma,
    realistic,
    significant_variance_flag: significantVarianceFlag,
    realistic_cap_rate_below_proforma: realisticCapRateBelowProforma,
  }
}
