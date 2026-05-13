/**
 * Core type definitions for the application
 */

export enum PropertyType {
  SINGLE_FAMILY = 'SINGLE_FAMILY',
  MULTI_FAMILY = 'MULTI_FAMILY',
  COMMERCIAL = 'COMMERCIAL',
}

export enum ConstructionType {
  FRAME = 'FRAME',
  BRICK = 'BRICK',
  MASONRY = 'MASONRY',
}

export enum InteriorCondition {
  NEEDS_GUT = 'NEEDS_GUT',
  POOR = 'POOR',
  AVERAGE = 'AVERAGE',
  NEW_RENO = 'NEW_RENO',
  HIGH_END = 'HIGH_END',
}

export enum WorkflowStep {
  PROPERTY_FACTS = 1,
  COMPARABLE_SEARCH = 2,
  COMPARABLE_REVIEW = 3,
  WEIGHTED_SCORING = 4,
  VALUATION = 5,
  REPORT = 6,
}

export interface PropertyFacts {
  address: string
  propertyType: PropertyType
  units: number
  bedrooms: number
  bathrooms: number
  squareFootage: number
  lotSize: number
  yearBuilt: number
  constructionType: ConstructionType
  basement: boolean
  parkingSpaces: number
  lastSalePrice?: number
  lastSaleDate?: string
  assessedValue: number
  annualTaxes: number
  zoning: string
  interiorCondition: InteriorCondition
  coordinates: { lat: number; lng: number }
  dataSource: string
  userModifiedFields: string[]
}

export interface ComparableSale {
  id: string
  address: string
  saleDate: string
  salePrice: number
  propertyType: PropertyType
  units: number
  bedrooms: number
  bathrooms: number
  squareFootage: number
  lotSize: number
  yearBuilt: number
  constructionType: ConstructionType
  interiorCondition: InteriorCondition
  distanceMiles: number
  coordinates: { lat: number; lng: number }
}

export interface ScoringBreakdown {
  recencyScore: number
  proximityScore: number
  unitsScore: number
  bedsBathsScore: number
  sqftScore: number
  constructionScore: number
  interiorScore: number
}

export interface RankedComparable {
  comparable: ComparableSale
  totalScore: number
  scoreBreakdown: ScoringBreakdown
  rank: number
}

export interface Adjustment {
  category: string
  difference: number | string
  adjustmentAmount: number
  explanation: string
}

export interface ComparableValuation {
  comparable: ComparableSale
  pricePerSqft: number
  pricePerUnit: number
  pricePerBedroom: number
  adjustedValue: number
  adjustments: Adjustment[]
  narrative: string
}

export interface ARVRange {
  conservative: number
  likely: number
  aggressive: number
  allValuations: number[]
}

export interface ValuationResult {
  comparableValuations: ComparableValuation[]
  arvRange: ARVRange
  keyDrivers: string[]
}

export enum ScenarioType {
  WHOLESALE = 'WHOLESALE',
  FIX_FLIP = 'FIX_FLIP',
  BUY_HOLD = 'BUY_HOLD',
}

export interface WholesaleScenario {
  scenarioType: ScenarioType.WHOLESALE
  purchasePrice: number
  mao: number
  contractPrice: number
  assignmentFeeLow: number
  assignmentFeeHigh: number
  estimatedRepairs: number
}

export interface FixFlipScenario {
  scenarioType: ScenarioType.FIX_FLIP
  purchasePrice: number
  acquisitionCost: number
  renovationCost: number
  holdingCosts: number
  financingCosts: number
  closingCosts: number
  totalCost: number
  exitValue: number
  netProfit: number
  roi: number
  monthsToFlip: number
}

export interface CapitalStructure {
  name: string
  downPaymentPercent: number
  interestRate: number
  loanTermMonths: number
}

export interface PricePoint {
  purchasePrice: number
  downPayment: number
  loanAmount: number
  monthlyPayment: number
  monthlyRent: number
  monthlyExpenses: number
  monthlyCashFlow: number
  cashOnCashReturn: number
  capRate: number
}

export interface BuyHoldScenario {
  scenarioType: ScenarioType.BUY_HOLD
  purchasePrice: number
  capitalStructures: CapitalStructure[]
  marketRent: number
  pricePoints: PricePoint[]
}

export type Scenario = WholesaleScenario | FixFlipScenario | BuyHoldScenario

export interface Report {
  sessionId: string
  subjectProperty: PropertyFacts
  comparables: ComparableSale[]
  rankedComparables: RankedComparable[]
  valuationResult: ValuationResult
  scenarios: Scenario[]
  generatedAt: string
}

export interface AnalysisSession {
  sessionId: string
  userId: string
  createdAt: string
  currentStep: WorkflowStep
  subjectProperty?: PropertyFacts
  comparables: ComparableSale[]
  rankedComparables: RankedComparable[]
  valuationResult?: ValuationResult
  scenarios: Scenario[]
  report?: Report
}

// API Request/Response Types
export interface StartAnalysisRequest {
  address: string
}

export interface StartAnalysisResponse {
  sessionId: string
  message: string
  propertyFacts?: Record<string, any>
}

export interface UpdateStepDataRequest {
  data: Record<string, any>
}

export interface AdvanceStepRequest {
  approved?: boolean
}

export interface StepResult {
  success: boolean
  message: string
  data?: Record<string, any>
}

export interface ErrorResponse {
  error: string
  message: string
  details?: Record<string, any>
}

// ---------------------------------------------------------------------------
// Lead Management Types
// ---------------------------------------------------------------------------

export enum ImportJobStatus {
  PENDING = 'pending',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export enum OutreachStatus {
  NOT_CONTACTED = 'not_contacted',
  CONTACTED = 'contacted',
  RESPONDED = 'responded',
  CONVERTED = 'converted',
  OPTED_OUT = 'opted_out',
}

export interface Lead {
  id: number
  property_street: string
  property_city: string | null
  property_state: string | null
  property_zip: string | null
  property_type: string | null
  bedrooms: number | null
  bathrooms: number | null
  square_footage: number | null
  lot_size: number | null
  year_built: number | null
  owner_first_name: string
  owner_last_name: string
  ownership_type: string | null
  acquisition_date: string | null
  phone_1: string | null
  phone_2: string | null
  phone_3: string | null
  email_1: string | null
  email_2: string | null
  mailing_address: string | null
  mailing_city: string | null
  mailing_state: string | null
  mailing_zip: string | null
  lead_score: number
  lead_category: string
  data_source: string | null
  last_import_job_id: number | null
  created_at: string | null
  updated_at: string | null
  analysis_session_id: number | null
  // Research tracking
  source: string | null
  date_identified: string | null
  notes: string | null
  needs_skip_trace: boolean | null
  skip_tracer: string | null
  date_skip_traced: string | null
  date_added_to_hubspot: string | null
  // Additional property details
  units: number | null
  units_allowed: number | null
  zoning: string | null
  county_assessor_pin: string | null
  tax_bill_2021: number | null
  most_recent_sale: string | null
  // Second owner
  owner_2_first_name: string | null
  owner_2_last_name: string | null
  // Additional address
  address_2: string | null
  returned_addresses: string | null
  // Additional phones
  phone_4: string | null
  phone_5: string | null
  phone_6: string | null
  phone_7: string | null
  // Additional emails
  email_3: string | null
  email_4: string | null
  email_5: string | null
  // Social media
  socials: string | null
  // Mailing tracking
  up_next_to_mail: boolean | null
  mailer_history: Record<string, any> | null
}

export interface LeadSummary {
  id: number
  property_street: string
  property_city: string | null
  property_state: string | null
  property_zip: string | null
  property_type: string | null
  bedrooms: number | null
  bathrooms: number | null
  square_footage: number | null
  lot_size: number | null
  year_built: number | null
  units: number | null
  units_allowed: number | null
  zoning: string | null
  county_assessor_pin: string | null
  tax_bill_2021: number | null
  most_recent_sale: string | null
  owner_first_name: string
  owner_last_name: string
  owner_2_first_name: string | null
  owner_2_last_name: string | null
  ownership_type: string | null
  acquisition_date: string | null
  phone_1: string | null
  phone_2: string | null
  phone_3: string | null
  phone_4: string | null
  phone_5: string | null
  phone_6: string | null
  phone_7: string | null
  email_1: string | null
  email_2: string | null
  email_3: string | null
  email_4: string | null
  email_5: string | null
  socials: string | null
  mailing_address: string | null
  mailing_city: string | null
  mailing_state: string | null
  mailing_zip: string | null
  address_2: string | null
  returned_addresses: string | null
  lead_score: number
  lead_category: string
  data_source: string | null
  created_at: string | null
  updated_at: string | null
  source: string | null
  date_identified: string | null
  notes: string | null
  needs_skip_trace: boolean | null
  skip_tracer: string | null
  date_skip_traced: string | null
  date_added_to_hubspot: string | null
  up_next_to_mail: boolean | null
  mailer_history: Record<string, any> | null
}

export interface LeadDetail extends Lead {
  enrichment_records: EnrichmentRecord[]
  marketing_lists: LeadMarketingListMembership[]
  analysis_session: LeadAnalysisSession | null
}

export interface LeadAnalysisSession {
  id: number
  session_id: string
  current_step: string
  created_at: string | null
  updated_at: string | null
}

export interface LeadMarketingListMembership {
  marketing_list_id: number
  marketing_list_name: string | null
  outreach_status: string
  added_at: string | null
}

export interface ImportJob {
  id: number
  user_id: string
  spreadsheet_id: string
  sheet_name: string
  field_mapping_id: number | null
  status: ImportJobStatus
  total_rows: number
  rows_processed: number
  rows_imported: number
  rows_skipped: number
  error_log: Array<{ row: number; error: string }>
  started_at: string | null
  completed_at: string | null
  created_at: string | null
}

export interface FieldMapping {
  id: number
  user_id: string
  spreadsheet_id: string
  sheet_name: string
  mapping: Record<string, string>
  created_at: string | null
  updated_at: string | null
}

export interface ScoringWeights {
  id: number
  user_id: string
  property_characteristics_weight: number
  data_completeness_weight: number
  owner_situation_weight: number
  location_desirability_weight: number
  created_at: string | null
  updated_at: string | null
}

export interface MarketingList {
  id: number
  name: string
  user_id: string
  filter_criteria: Record<string, any> | null
  member_count: number
  created_at: string | null
  updated_at: string | null
}

export interface MarketingListMember {
  id: number
  marketing_list_id: number
  lead_id: number
  outreach_status: OutreachStatus
  added_at: string | null
  status_updated_at: string | null
  lead?: LeadSummary
}

export interface EnrichmentRecord {
  id: number
  lead_id: number
  data_source_id: number
  data_source_name: string | null
  status: string
  retrieved_data: Record<string, any> | null
  error_reason: string | null
  created_at: string | null
}

export interface DataSource {
  id: number
  name: string
  is_active: boolean
}

export interface SheetInfo {
  sheet_id: number
  title: string
  row_count: number
  column_count: number
}

// Pagination and filter types

export interface PaginatedResponse {
  total: number
  page: number
  per_page: number
  pages: number
}

export interface LeadListResponse extends PaginatedResponse {
  leads: LeadSummary[]
}

export interface ImportJobListResponse extends PaginatedResponse {
  jobs: ImportJob[]
}

export interface MarketingListsResponse extends PaginatedResponse {
  lists: MarketingList[]
}

export interface MarketingListMembersResponse extends PaginatedResponse {
  list_id: number
  list_name: string
  members: MarketingListMember[]
}

export interface LeadListFilters {
  page?: number
  per_page?: number
  property_type?: string
  lead_category?: 'residential' | 'commercial'
  city?: string
  state?: string
  zip?: string
  owner_name?: string
  score_min?: number
  score_max?: number
  marketing_list_id?: number
  sort_by?: 'lead_score' | 'created_at' | 'property_street'
  sort_order?: 'asc' | 'desc'
}

// ---------------------------------------------------------------------------
// Condo Filter Types
// ---------------------------------------------------------------------------

export type CondoRiskStatus = 'likely_condo' | 'likely_not_condo' | 'partial_condo_possible' | 'needs_review' | 'unknown'
export type BuildingSalePossible = 'yes' | 'no' | 'maybe' | 'unknown'

export interface AddressGroupAnalysis {
  id: number
  normalized_address: string
  source_type: string | null
  property_count: number
  pin_count: number
  owner_count: number
  has_unit_number: boolean
  has_condo_language: boolean
  missing_pin_count: number
  missing_owner_count: number
  condo_risk_status: CondoRiskStatus
  building_sale_possible: BuildingSalePossible
  analysis_details: {
    triggered_rules: string[]
    reason: string
    confidence: string
  } | null
  manually_reviewed: boolean
  manual_override_status: string | null
  manual_override_reason: string | null
  analyzed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AddressGroupDetail extends AddressGroupAnalysis {
  leads: AddressGroupLead[]
}

export interface AddressGroupLead {
  id: number
  property_street: string
  county_assessor_pin: string | null
  owner_first_name: string | null
  owner_last_name: string | null
  owner_2_first_name: string | null
  owner_2_last_name: string | null
  property_type: string | null
  assessor_class: string | null
}

export interface CondoFilterResultsResponse extends PaginatedResponse {
  results: AddressGroupAnalysis[]
}

export interface CondoAnalysisSummary {
  total_groups: number
  total_properties: number
  by_status: Record<CondoRiskStatus, number>
  by_building_sale: Record<BuildingSalePossible, number>
}

export interface CondoFilterParams {
  condo_risk_status?: CondoRiskStatus
  building_sale_possible?: BuildingSalePossible
  manually_reviewed?: boolean
  page?: number
  per_page?: number
}

export interface CondoOverrideRequest {
  condo_risk_status: CondoRiskStatus
  building_sale_possible: BuildingSalePossible
  reason: string
}

// ---------------------------------------------------------------------------
// Multifamily Underwriting Pro Forma Types
// ---------------------------------------------------------------------------

export enum OccupancyStatus {
  OCCUPIED = 'Occupied',
  VACANT = 'Vacant',
  DOWN = 'Down',
}

export enum MFLenderType {
  CONSTRUCTION_TO_PERM = 'Construction_To_Perm',
  SELF_FUNDED_RENO = 'Self_Funded_Reno',
}

export enum FundingSourceType {
  CASH = 'Cash',
  HELOC_1 = 'HELOC_1',
  HELOC_2 = 'HELOC_2',
}

export enum DealScenario {
  A = 'A',
  B = 'B',
}

export interface Deal {
  id: number
  created_by_user_id: string
  property_address: string
  property_city: string | null
  property_state: string | null
  property_zip: string | null
  unit_count: number
  purchase_price: string // Decimal serialized as string
  closing_costs: string
  close_date: string | null
  vacancy_rate: string
  other_income_monthly: string
  management_fee_rate: string
  reserve_per_unit_per_year: string
  property_taxes_annual: string | null
  insurance_annual: string | null
  utilities_annual: string | null
  repairs_and_maintenance_annual: string | null
  admin_and_marketing_annual: string | null
  payroll_annual: string | null
  other_opex_annual: string | null
  interest_reserve_amount: string
  custom_cap_rate: string | null
  status: string
  created_at: string | null
  updated_at: string | null
  deleted_at: string | null
  // Nested child records returned by GET /deals/:id
  units?: MFUnit[]
  rent_roll_entries?: RentRollEntry[]
  rehab_plan_entries?: RehabPlanEntry[]
  funding_sources?: FundingSource[]
  lender_selections?: DealLenderSelection[]
}

export interface DealSummary {
  id: number
  property_address: string
  unit_count: number
  purchase_price: string
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface DealCreatePayload {
  property_address: string
  unit_count: number
  purchase_price: number
  close_date?: string
  property_city?: string
  property_state?: string
  property_zip?: string
  closing_costs?: number
  vacancy_rate?: number
  other_income_monthly?: number
  management_fee_rate?: number
  reserve_per_unit_per_year?: number
  property_taxes_annual?: number
  insurance_annual?: number
  utilities_annual?: number
  repairs_and_maintenance_annual?: number
  admin_and_marketing_annual?: number
  payroll_annual?: number
  other_opex_annual?: number
  interest_reserve_amount?: number
  custom_cap_rate?: number
  status?: string
}

export interface MFUnit {
  id: number
  deal_id: number
  unit_identifier: string
  unit_type: string
  beds: number
  baths: number
  sqft: number
  occupancy_status: OccupancyStatus
  created_at: string | null
  updated_at: string | null
}

export interface RentRollEntry {
  id: number
  unit_id: number
  current_rent: string
  lease_start_date: string | null
  lease_end_date: string | null
  notes: string | null
}

export interface RentRollSummary {
  total_unit_count: number
  occupied_unit_count: number
  vacant_unit_count: number
  occupancy_rate: number
  total_in_place_rent: string
  average_rent_per_occupied_unit: string | null
  rent_roll_incomplete: boolean
}

export interface MarketRentAssumption {
  id: number
  deal_id: number
  unit_type: string
  target_rent: string | null
  post_reno_target_rent: string | null
}

export interface RentComp {
  id: number
  deal_id: number
  address: string
  neighborhood: string | null
  unit_type: string
  observed_rent: string
  sqft: number
  rent_per_sqft: string
  observation_date: string
  source_url: string | null
}

export interface RentCompRollup {
  unit_type: string
  average_observed_rent: string | null
  median_observed_rent: string | null
  average_rent_per_sqft: string | null
  comps: RentComp[]
}

export interface MFSaleComp {
  id: number
  deal_id: number
  address: string
  unit_count: number
  status: string
  sale_price: string
  close_date: string
  observed_cap_rate: string | null
  observed_ppu: string
  distance_miles: string | null
  noi: string | null
  /** 1.0 = stated directly, 0.5 = derived from NOI/price, 0.0 = unknown, null = not set */
  cap_rate_confidence: number | null
}

export interface SaleCompRollup {
  cap_rate_min: string | null
  cap_rate_median: string | null
  cap_rate_average: string | null
  cap_rate_max: string | null
  ppu_min: string | null
  ppu_median: string | null
  ppu_average: string | null
  ppu_max: string | null
  sale_comps_insufficient: boolean
  comps: MFSaleComp[]
}

export interface RehabPlanEntry {
  id: number
  unit_id: number
  renovate_flag: boolean
  current_rent: string
  suggested_post_reno_rent: string | null
  underwritten_post_reno_rent: string | null
  rehab_start_month: number | null
  downtime_months: number | null
  stabilized_month: number | null
  rehab_budget: string
  scope_notes: string | null
  stabilizes_after_horizon: boolean
}

export interface RehabMonthlyRollup {
  month: number
  units_starting_rehab_count: number
  units_offline_count: number
  units_stabilizing_count: number
  capex_spend: string
}

export interface LenderProfile {
  id: number
  created_by_user_id: string
  company: string
  lender_type: MFLenderType
  origination_fee_rate: string
  prepay_penalty_description: string | null
  // Construction_To_Perm fields
  ltv_total_cost: string | null
  construction_rate: string | null
  construction_io_months: number | null
  construction_term_months: number | null
  perm_rate: string | null
  perm_amort_years: number | null
  min_interest_or_yield: string | null
  // Self_Funded_Reno fields
  max_purchase_ltv: string | null
  treasury_5y_rate: string | null
  spread_bps: number | null
  term_years: number | null
  amort_years: number | null
  all_in_rate: string | null // computed
  created_at: string | null
  updated_at: string | null
}

export interface DealLenderSelection {
  id: number
  deal_id: number
  lender_profile_id: number
  scenario: DealScenario
  is_primary: boolean
  lender_profile?: LenderProfile
}

export interface FundingSource {
  id: number
  deal_id: number
  source_type: FundingSourceType
  total_available: string
  interest_rate: string
  origination_fee_rate: string
}

export interface FundingDrawPlan {
  cash_draw: string
  heloc_1_draw: string
  heloc_2_draw: string
  shortfall: string
  origination_fees: string
  insufficient_funding: boolean
}

export interface OpExBreakdown {
  property_taxes: string
  insurance: string
  utilities: string
  repairs_and_maintenance: string
  admin_and_marketing: string
  payroll: string
  other_opex: string
  management_fee: string
}

export interface MonthlyRow {
  month: number
  gsr: string
  vacancy_loss: string
  other_income: string
  egi: string
  opex_breakdown: OpExBreakdown
  opex_total: string
  noi: string
  replacement_reserves: string
  net_cash_flow: string
  debt_service_a: string | null
  debt_service_b: string | null
  cash_flow_after_debt_a: string | null
  cash_flow_after_debt_b: string | null
  capex_spend: string
  cash_flow_after_capex_a: string | null
  cash_flow_after_capex_b: string | null
}

export interface SourcesAndUses {
  // Uses
  purchase_price: string
  closing_costs: string
  rehab_budget_total: string
  loan_origination_fees: string
  funding_source_origination_fees: string
  interest_reserve: string
  total_uses: string
  // Sources
  loan_amount: string
  cash_draw: string
  heloc_1_draw: string
  heloc_2_draw: string
  total_sources: string
  initial_cash_investment: string
}

export interface ProFormaSummary {
  in_place_noi: string | null
  stabilized_noi: string | null
  in_place_dscr_a: string | null
  stabilized_dscr_a: string | null
  in_place_dscr_b: string | null
  stabilized_dscr_b: string | null
  cash_on_cash_a: string | null
  cash_on_cash_b: string | null
  warnings: string[]
}

export interface ProFormaResult {
  deal_id: number
  inputs_hash: string
  computed_at: string
  monthly_schedule: MonthlyRow[]
  summary: ProFormaSummary
  sources_and_uses_a: SourcesAndUses | null
  sources_and_uses_b: SourcesAndUses | null
  missing_inputs_a: string[]
  missing_inputs_b: string[]
}

export interface MFValuation {
  valuation_at_cap_rate_min: string | null
  valuation_at_cap_rate_median: string | null
  valuation_at_cap_rate_average: string | null
  valuation_at_cap_rate_max: string | null
  valuation_at_ppu_min: string | null
  valuation_at_ppu_median: string | null
  valuation_at_ppu_average: string | null
  valuation_at_ppu_max: string | null
  valuation_at_custom_cap_rate: string | null
  price_to_rent_ratio: string | null
  warnings: string[]
}

export interface DashboardScenario {
  scenario: DealScenario
  purchase_price: string
  loan_amount: string | null
  interest_rate: string | null
  amort_years: number | null
  io_period_months: number | null
  in_place_noi: string | null
  stabilized_noi: string | null
  in_place_dscr: string | null
  stabilized_dscr: string | null
  price_to_rent_ratio: string | null
  valuation_at_cap_rate_min: string | null
  valuation_at_cap_rate_median: string | null
  valuation_at_cap_rate_average: string | null
  valuation_at_cap_rate_max: string | null
  valuation_at_ppu_min: string | null
  valuation_at_ppu_median: string | null
  valuation_at_ppu_average: string | null
  valuation_at_ppu_max: string | null
  sources_and_uses: SourcesAndUses | null
  initial_cash_investment: string | null
  month_1_net_cash_flow: string | null
  month_24_net_cash_flow: string | null
  cash_on_cash_return: string | null
  missing_inputs: string[]
}

export interface Dashboard {
  deal_id: number
  scenario_a: DashboardScenario
  scenario_b: DashboardScenario
}

export interface MFImportResult {
  deal_id: number
  parse_report: Array<{
    sheet: string
    rows_parsed: number
    rows_skipped: number
    warnings: string[]
  }>
}

export interface DealListResponse {
  deals: DealSummary[]
}

// ---------------------------------------------------------------------------
// Lead Scoring Types
// ---------------------------------------------------------------------------

export type RecommendedAction =
  | 'review_now'
  | 'enrich_data'
  | 'mail_ready'
  | 'call_ready'
  | 'valuation_needed'
  | 'suppress'
  | 'nurture'
  | 'needs_manual_review'

export interface ScoreSignal {
  dimension: string
  points: number
}

export interface LeadScoreRecord {
  id: number
  lead_id: number
  property_id?: number | null
  score_version: string
  total_score: number
  score_tier: 'A' | 'B' | 'C' | 'D'
  data_quality_score: number
  recommended_action: RecommendedAction
  top_signals: ScoreSignal[]
  score_details: Record<string, number>
  missing_data: string[]
  created_at: string
}

export interface LeadScoreResponse {
  /**
   * The most recent LeadScoreRecord for the lead, or `null` when the lead
   * has never been scored.
   */
  latest: LeadScoreRecord | null
  history: LeadScoreRecord[]
}

export interface RecalculateRequest {
  lead_id?: number
  source_type?: string
  all?: boolean
}

export interface RecalculateResponse {
  success: boolean
  message: string
  score?: LeadScoreRecord
  count?: number
}

// ---------------------------------------------------------------------------
// Commercial OM PDF Intake Types
// ---------------------------------------------------------------------------

export enum IntakeStatus {
  PENDING = 'PENDING',
  PARSING = 'PARSING',
  EXTRACTING = 'EXTRACTING',
  RESEARCHING = 'RESEARCHING',
  REVIEW = 'REVIEW',
  CONFIRMED = 'CONFIRMED',
  FAILED = 'FAILED',
}

export interface OMFieldValue<T = unknown> {
  value: T | null
  confidence: number  // 0.0 to 1.0
}

export interface UnitMixRow {
  unit_type_label: OMFieldValue<string>
  unit_count: OMFieldValue<number>
  sqft: OMFieldValue<number>
  current_avg_rent: OMFieldValue<number>
  proforma_rent: OMFieldValue<number>
  market_rent_estimate?: OMFieldValue<number>
  market_rent_low?: OMFieldValue<number>
  market_rent_high?: OMFieldValue<number>
}

export interface ExtractedOMData {
  // Property fields
  property_address: OMFieldValue<string>
  property_city: OMFieldValue<string>
  property_state: OMFieldValue<string>
  property_zip: OMFieldValue<string>
  neighborhood: OMFieldValue<string>
  asking_price: OMFieldValue<number>
  price_per_unit: OMFieldValue<number>
  price_per_sqft: OMFieldValue<number>
  building_sqft: OMFieldValue<number>
  year_built: OMFieldValue<number>
  lot_size: OMFieldValue<number>
  zoning: OMFieldValue<string>
  unit_count: OMFieldValue<number>
  // Broker current metrics
  current_noi: OMFieldValue<number>
  current_cap_rate: OMFieldValue<number>
  current_grm: OMFieldValue<number>
  current_gross_potential_income: OMFieldValue<number>
  current_effective_gross_income: OMFieldValue<number>
  current_vacancy_rate: OMFieldValue<number>
  current_gross_expenses: OMFieldValue<number>
  // Broker proforma metrics
  proforma_noi: OMFieldValue<number>
  proforma_cap_rate: OMFieldValue<number>
  proforma_grm: OMFieldValue<number>
  proforma_gross_potential_income: OMFieldValue<number>
  proforma_effective_gross_income: OMFieldValue<number>
  proforma_vacancy_rate: OMFieldValue<number>
  proforma_gross_expenses: OMFieldValue<number>
  // Unit mix
  unit_mix: UnitMixRow[]
  // Income
  apartment_income_current: OMFieldValue<number>
  apartment_income_proforma: OMFieldValue<number>
  other_income_items: Array<{ label: OMFieldValue<string>; annual_amount: OMFieldValue<number> }>
  // Expenses
  expense_items: Array<{
    label: OMFieldValue<string>
    current_annual_amount: OMFieldValue<number>
    proforma_annual_amount: OMFieldValue<number>
  }>
  // Financing
  down_payment_pct: OMFieldValue<number>
  loan_amount: OMFieldValue<number>
  interest_rate: OMFieldValue<number>
  amortization_years: OMFieldValue<number>
  debt_service_annual: OMFieldValue<number>
  current_dscr: OMFieldValue<number>
  proforma_dscr: OMFieldValue<number>
  current_cash_on_cash: OMFieldValue<number>
  proforma_cash_on_cash: OMFieldValue<number>
  // Broker/listing
  listing_broker_name: OMFieldValue<string>
  listing_broker_company: OMFieldValue<string>
  listing_broker_phone: OMFieldValue<string>
  listing_broker_email: OMFieldValue<string>
}

export interface ScenarioMetrics {
  gross_potential_income_annual: string | null  // Decimal as string
  effective_gross_income_annual: string | null
  gross_expenses_annual: string | null
  noi_annual: string | null
  cap_rate: string | null
  grm: string | null
  monthly_rent_total: string | null
  dscr: string | null
  cash_on_cash: string | null
}

export interface UnitMixComparisonRow {
  unit_type_label: string
  unit_count: number
  sqft: string | null
  current_avg_rent: string | null
  proforma_rent: string | null
  market_rent_estimate: string | null
  market_rent_low: string | null
  market_rent_high: string | null
}

export interface ScenarioComparison {
  broker_current: ScenarioMetrics
  broker_proforma: ScenarioMetrics
  realistic: ScenarioMetrics
  unit_mix_comparison: UnitMixComparisonRow[]
  significant_variance_flag: boolean | null
  realistic_cap_rate_below_proforma: boolean | null
}

export interface OMIntakeJob {
  id: number
  user_id: string
  intake_status: IntakeStatus
  original_filename: string
  created_at: string
  updated_at: string
  expires_at: string
  error_message: string | null
  deal_id: number | null
}

export interface OMIntakeJobListItem {
  id: number
  intake_status: IntakeStatus
  original_filename: string
  created_at: string
  deal_id: number | null
  property_address: string | null
  asking_price: number | null
  unit_count: number | null
}

export interface OMIntakeReviewData {
  id: number
  intake_status: IntakeStatus
  original_filename: string
  created_at: string
  updated_at: string
  extracted_om_data: ExtractedOMData | null
  scenario_comparison: ScenarioComparison | null
  consistency_warnings: Array<Record<string, unknown>> | null
  market_research_warnings: Array<Record<string, unknown>> | null
  partial_realistic_scenario_warning: boolean | null
  asking_price_missing_error: boolean | null
  unit_count_missing_error: boolean | null
  deal_id: number | null
}

export interface OMIntakeConfirmRequest {
  asking_price?: number | null
  unit_count?: number | null
  unit_mix?: Array<{
    unit_type_label: string
    unit_count: number
    sqft: number
    current_avg_rent: number | null
    proforma_rent: number | null
    market_rent_estimate?: number | null
  }>
  expense_items?: Array<{
    label: string
    current_annual_amount: number | null
    proforma_annual_amount?: number | null
  }>
  other_income_items?: Array<{
    label: string
    annual_amount: number
  }>
  property_address?: string
  property_city?: string
  property_state?: string
  property_zip?: string
}
