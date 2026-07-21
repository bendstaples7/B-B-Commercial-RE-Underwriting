/**
 * Core type definitions for the application
 *
 * ----------------------------------------------------------------------------
 * OpenAPI Type Generation Workflow
 * ----------------------------------------------------------------------------
 * The backend exposes a machine-readable OpenAPI 3.0 spec at:
 *   GET /api/openapi.json
 *
 * To regenerate TypeScript types from the live spec, run:
 *   npm run generate-types
 *
 * This requires the backend dev server to be running on port 5000:
 *   python backend/run.py
 *
 * The generated types are written to `src/types/generated.ts`.
 * They are NOT automatically imported here — use them selectively for new
 * features or when migrating existing types.  The hand-written types in this
 * file remain the source of truth until a full migration is completed.
 * ----------------------------------------------------------------------------
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
  similarityNotes?: string | null
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
  loading: boolean
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
  latitude?: number
  longitude?: number
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
// Property Management Types (formerly "Lead Management Types")
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

export interface Property {
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
  owner_first_name: string | null
  owner_last_name: string | null
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
  source_type?: 'foreclosure' | 'long_owned' | 'absentee_owner' | 'tax_distress' | 'manual_distress' | null
  tax_distress_data?: {
    signal_type: 'tax_delinquency' | 'tax_sale'
    delinquent_amount: number | null
    tax_year: number | null
  } | null
  manual_priority?: number | null
  last_import_job_id: number | null
  created_at: string | null
  updated_at: string | null
  analysis_session_id: number | null
  // Research tracking
  source: string | null
  deal_source: string | null
  deal_description: string | null
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
  mailer_history: Record<string, any> | any[] | string | null
}

/** @deprecated Use `Property` instead */
export type Lead = Property

export interface PropertySummary {
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
  most_recent_sale_display?: string | null
  owner_first_name: string | null
  owner_last_name: string | null
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
  mailer_history: Record<string, any> | any[] | string | null
  score_tier?: 'A' | 'B' | 'C' | 'D' | null
  data_quality_score?: number | null
  recommended_action?: string | null
  recommended_contact_method?: ContactMethod | null
  top_signal?: string | null
  missing_data?: string[]
  missing_data_count?: number | null
}

/** @deprecated Use `PropertySummary` instead */
export type LeadSummary = PropertySummary

export interface MotivationSignalSummaryItem {
  signal_type: string;
  label: string;
  points: number;
  severity: string;
}

export interface MotivationSignalDetail {
  id: number;
  signal_type: string;
  label?: string;
  severity: string;
  points: number;
  source: string;
  source_dataset?: string | null;
  evidence?: Record<string, unknown> | null;
  detected_at?: string | null;
  is_active: boolean;
}

/** Minimal contact summary embedded inside PropertyDetail.
 *  Comes from the relational contacts system (property_contacts join table).
 *  This is the authoritative source — the legacy owner_first_name / owner_last_name
 *  flat columns on the property record are from the original import and are not
 *  updated by HubSpot enrichment. */
export interface PropertyContactSummary {
  id: number
  first_name: string | null
  last_name: string | null
  role: ContactRole
  is_primary: boolean
  /** Full phone DTO including confidence — same shape as ContactPhone / LeadPhone. */
  phones: LeadPhone[]
  emails: Array<{ id: number; value: string; label: EmailLabel }>
}

/** Snapshot of owner/contact/mailing captured when contacts went stale or were replaced. */
export interface PastOwnerSnapshot {
  id: number
  captured_at: string | null
  reason: 'recent_sale' | 'contact_replaced' | (string & {})
  sale_date?: string | null
  owner_names: Array<{
    contact_id?: number | null
    first_name?: string | null
    last_name?: string | null
    role?: ContactRole | string | null
    is_primary?: boolean
  }>
  phones: Array<{
    value?: string | null
    label?: string | null
    confidence_score?: number | null
  }>
  emails: Array<{ value?: string | null; label?: string | null }>
  mailing_address?: string | null
  mailing_city?: string | null
  mailing_state?: string | null
  mailing_zip?: string | null
}

export interface PropertyDetail extends Property {
  motivation_score?: number | null;
  motivation_signal_summary?: MotivationSignalSummaryItem[];
  motivation_signals?: MotivationSignalDetail[];
  enrichment_records: EnrichmentRecord[]
  marketing_lists: PropertyMarketingListMembership[]
  analysis_session: PropertyAnalysisSession | null
  /** All contacts linked to this property, primary contact first.
   *  Prefer these over the legacy owner_first_name / owner_last_name fields. */
  contacts: PropertyContactSummary[]
}

/** @deprecated Use `PropertyDetail` instead */
export type LeadDetail = PropertyDetail

export interface PropertyAnalysisSession {
  id: number
  session_id: string
  current_step: string
  created_at: string | null
  updated_at: string | null
}

/** @deprecated Use `PropertyAnalysisSession` instead */
export type LeadAnalysisSession = PropertyAnalysisSession

export interface PropertyMarketingListMembership {
  marketing_list_id: number
  marketing_list_name: string | null
  outreach_status: string
  added_at: string | null
}

/** @deprecated Use `PropertyMarketingListMembership` instead */
export type LeadMarketingListMembership = PropertyMarketingListMembership

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
  data_enrichment_weight: number
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
  lead?: PropertySummary
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

export interface PropertyListResponse extends PaginatedResponse {
  leads: PropertySummary[]
}

/** @deprecated Use `PropertyListResponse` instead */
export type LeadListResponse = PropertyListResponse

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

export interface PropertyListFilters {
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
  source_type?: 'foreclosure' | 'long_owned' | 'absentee_owner' | 'tax_distress' | 'manual_distress'
  owner_user_id?: string
}

/** @deprecated Use `PropertyListFilters` instead */
export type LeadListFilters = PropertyListFilters

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
  priority_score: string | null
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
  /** True = AI-fetched, pending user review. False = confirmed, included in rollup. */
  is_suggested: boolean
  /** True = user dismissed, excluded from suggested list. */
  is_dismissed: boolean
  /** True = unit count is outside ±50% of subject property unit count. */
  out_of_range: boolean
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
  cf_per_unit_month_1: string | null
  cf_per_unit_month_24: string | null
  cf_needed_for_min: string | null
  purchase_price_for_min_cf: string | null
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
// Property Scoring Types (formerly "Lead Scoring Types")
// ---------------------------------------------------------------------------

export type ContactMethod = 'phone' | 'email' | 'text' | 'direct_mail'

/** Resolved outreach target (phone, email, or mailing address) for UI callouts. */
export interface OutreachContact {
  channel: ContactMethod
  label: string
  value: string
  display: string
  href?: string | null
  lines?: string[]
}

/** Unified recommended action vocabulary (scoring + workflow). */
export type UnifiedRecommendedAction =
  | 'enrich_data'
  | 'resolve_match'
  | 'analyze_property'
  | 'follow_up_now'
  | 'ready_for_outreach'
  | 'add_contact_info'
  | 'create_task'
  | 'nurture'
  | 'hold'
  | 'suppress'
  | 'do_not_contact'
  | 'review_now'
  | 'mail_ready'
  | 'call_ready'
  | 'valuation_needed'
  | 'needs_manual_review'

/** @deprecated Use `UnifiedRecommendedAction` */
export type ScoringRecommendedAction = UnifiedRecommendedAction

/** @deprecated Use `UnifiedRecommendedAction` instead */
export type RecommendedAction = UnifiedRecommendedAction

export type CRMRecommendedAction = UnifiedRecommendedAction

export interface ScoreSignal {
  dimension: string
  points: number
}

export interface PropertyScoreRecord {
  id: number
  property_id: number
  /** @deprecated Use `property_id` instead */
  lead_id?: number | null
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

/** @deprecated Use `PropertyScoreRecord` instead */
export type LeadScoreRecord = PropertyScoreRecord

export interface PropertyScoreResponse {
  /**
   * The most recent PropertyScoreRecord for the property, or `null` when the property
   * has never been scored.
   */
  latest: PropertyScoreRecord | null
  history: PropertyScoreRecord[]
}

/** @deprecated Use `PropertyScoreResponse` instead */
export type LeadScoreResponse = PropertyScoreResponse

export interface RecalculateRequest {
  lead_id?: number
  source_type?: string
  all?: boolean
}

export interface RecalculateResponse {
  success: boolean
  message: string
  score?: PropertyScoreRecord
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

// ---------------------------------------------------------------------------
// HubSpot CRM Migration Types
// ---------------------------------------------------------------------------

export enum OrgType {
  LLC = 'llc',
  TRUST = 'trust',
  CORPORATION = 'corporation',
  BROKERAGE = 'brokerage',
  LAW_FIRM = 'law_firm',
  PROPERTY_MANAGEMENT = 'property_management',
  NONPROFIT = 'nonprofit',
  UNKNOWN = 'unknown',
}

export enum OrgStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  UNKNOWN = 'unknown',
}

export enum InteractionType {
  NOTE = 'note',
  CALL = 'call',
  EMAIL = 'email',
  MEETING = 'meeting',
  OTHER = 'other',
}

export enum InteractionSource {
  MANUAL = 'manual',
  HUBSPOT_IMPORT = 'hubspot_import',
}

export enum TaskStatus {
  OPEN = 'open',
  COMPLETED = 'completed',
  CANCELLED = 'cancelled',
  OVERDUE = 'overdue',
}

export enum TaskPriority {
  HIGH = 'high',
  MEDIUM = 'medium',
  LOW = 'low',
}

export enum MatchConfidence {
  HIGH = 'HIGH',
  MEDIUM = 'MEDIUM',
  LOW = 'LOW',
  UNMATCHED = 'UNMATCHED',
}

export enum MatchStatus {
  PENDING = 'pending',
  CONFIRMED = 'confirmed',
  REJECTED = 'rejected',
}

export enum SignalType {
  PRIOR_INTERACTION_EXISTS = 'PRIOR_INTERACTION_EXISTS',
  PRIOR_RESPONSE_EXISTS = 'PRIOR_RESPONSE_EXISTS',
  PRIOR_WARM_CONVERSATION = 'PRIOR_WARM_CONVERSATION',
  ASKING_PRICE_GIVEN = 'ASKING_PRICE_GIVEN',
  APPOINTMENT_OCCURRED = 'APPOINTMENT_OCCURRED',
  OFFER_PREVIOUSLY_SENT = 'OFFER_PREVIOUSLY_SENT',
  SELLER_SAID_MAYBE_LATER = 'SELLER_SAID_MAYBE_LATER',
  SELLER_NOT_INTERESTED = 'SELLER_NOT_INTERESTED',
  WRONG_NUMBER = 'WRONG_NUMBER',
  DO_NOT_CONTACT = 'DO_NOT_CONTACT',
  FOLLOW_UP_OVERDUE = 'FOLLOW_UP_OVERDUE',
  PRIOR_LEAD_SOURCE_KNOWN = 'PRIOR_LEAD_SOURCE_KNOWN',
}

/** HubSpot-specific recommended action (distinct from the lead-scoring RecommendedAction union type) */
export enum HubSpotRecommendedAction {
  CONTACT_NOW = 'CONTACT_NOW',
  FOLLOW_UP_LATER = 'FOLLOW_UP_LATER',
  REVISIT_OFFER = 'REVISIT_OFFER',
  DO_NOT_CONTACT = 'DO_NOT_CONTACT',
}

export interface Organization {
  id: number
  name: string
  org_type: OrgType
  status: OrgStatus
  notes?: string | null
  source?: string | null
  hubspot_company_id?: string | null
  jurisdiction?: string | null
  file_number?: string | null
  registered_agent_name?: string | null
  registered_office_address?: string | null
  entity_lookup_status?: EntityLookupStatus | null
  entity_lookup_provider?: string | null
  entity_lookup_checked_at?: string | null
  entity_lookup_error?: string | null
  entity_lookup_person_found?: boolean
  created_at: string
  updated_at: string
}

/** Organization linked to a lead/property in command-center payload. */
export interface PropertyOrganizationSummary {
  id: number
  name: string
  org_type: OrgType | string | null
  status?: OrgStatus | string | null
  role: string
  link_id: number
  entity_lookup_status?: EntityLookupStatus | string | null
  entity_lookup_person_found?: boolean | null
  entity_lookup_checked_at?: string | null
  entity_lookup_error?: string | null
  jurisdiction?: string | null
  file_number?: string | null
  registered_office_address?: string | null
  registered_agent_name?: string | null
  /** Natural person found on Illinois SOS filing (manager/member). */
  resolved_person_name?: string | null
  resolved_person_role?: string | null
}

/** Other building owned by the same person (Command Center / portfolio). */
export interface RelatedPropertySummary {
  id: number
  property_street: string | null
  property_city?: string | null
  lead_status?: string | null
  lead_score?: number | null
}

export type EntityLookupStatus =
  | 'pending'
  | 'resolved'
  | 'no_match'
  | 'unsupported_jurisdiction'
  | 'error'

export interface EntityResolutionStatus {
  lead_id: number
  primary_is_entity: boolean
  entity_name: string | null
  is_institutional?: boolean
  is_definite_institutional?: boolean
  jurisdiction_supported: boolean
  supported_jurisdiction: string
  organization_id: number | null
  organization_name: string | null
  organization_org_type?: string | null
  entity_lookup_status: EntityLookupStatus | null
  entity_lookup_person_found: boolean
  entity_lookup_error: string | null
  entity_lookup_checked_at: string | null
  entity_lookup_provider: string | null
  registered_office_address?: string | null
  registered_agent_name?: string | null
  file_number?: string | null
  resolved_person_name?: string | null
  resolved_person_role?: string | null
  provider?: string | null
  provider_configured?: boolean
  dataset_imported_at?: string | null
  nonprofit_provider?: string | null
  nonprofit_provider_configured?: boolean
  nonprofit_dataset_imported_at?: string | null
  is_nonprofit?: boolean
  can_mark_nonprofit?: boolean
  can_research?: boolean
  limitations?: string[]
  can_resolve: boolean
}

export interface EntityResolutionResult {
  lead_id: number
  status: string
  entity_name?: string | null
  organization_id?: number | null
  person_contact_id?: number | null
  person_found?: boolean
  person_name?: string | null
  skip_trace_task_id?: number | null
  message?: string | null
  dry_run?: boolean
}

export interface OrganizationAuditLog {
  id: number
  organization_id: number
  field_name: string
  old_value?: string | null
  new_value?: string | null
  changed_by: string
  changed_at: string
}

export interface PropertyOrganizationLink {
  id: number
  property_id: number
  organization_id: number
  role: string
  created_at: string
}

export interface OwnerOrganizationLink {
  id: number
  owner_id: number
  organization_id: number
  role: string
  created_at: string
}

export interface Interaction {
  id: number
  interaction_type: InteractionType
  body: string
  occurred_at: string
  source: InteractionSource
  hubspot_engagement_id?: string | null
  raw_payload?: Record<string, unknown> | null
  is_orphaned: boolean
  created_at: string
  updated_at: string
}

export interface InteractionAssociation {
  id: number
  interaction_id: number
  target_type: string
  target_id: number
}

export interface TimelineEntry {
  entry_type: string
  subtype: string
  date: string
  body_or_title: string
  source: string
  hubspot_engagement_id?: string | null
}

export interface CRMTask {
  id: number
  title: string
  body?: string | null
  due_date?: string | null
  status: TaskStatus
  priority: TaskPriority
  source: InteractionSource
  hubspot_task_id?: string | null
  raw_payload?: Record<string, unknown> | null
  completion_timestamp?: string | null
  created_at: string
  updated_at: string
}

export interface TaskAssociation {
  id: number
  task_id: number
  target_type: string
  target_id: number
}

export interface HubSpotConfig {
  id?: number
  portal_id?: string | null
  account_name?: string | null
  configured?: boolean
  has_client_secret?: boolean
  write_back_enabled?: boolean
}

export interface QuickAddPayload {
  property_street: string
  note?: string | null
  priority?: 'high' | 'medium' | 'low' | null
  deal_source?: string | null
  date_identified?: string | null
  capture_latitude?: number | null
  capture_longitude?: number | null
  capture_location_label?: string | null
  property_city?: string | null
  property_state?: string | null
  property_zip?: string | null
}

export interface QuickAddResponse {
  lead_id: number
  created: boolean
  property_street: string
  lead_status: string
  deal_source: string
  date_identified: string | null
  hubspot_push_status: 'disabled' | 'queued' | 'queue_failed'
  hubspot_write_back_enabled: boolean
}

export interface QuickAddLookupMatch {
  lead_id: number
  property_street: string | null
  lead_status: string | null
  deal_source: string | null
  date_identified: string | null
}

export interface QuickAddLookupResponse {
  matches: QuickAddLookupMatch[]
}

/** HubSpot-aligned deal sources for quick-add (Driving For Dollars is the walk-by default). */
export const QUICK_ADD_DEAL_SOURCES = [
  'Driving For Dollars',
  'Cityscape',
  'Cityscape Unused Zoning Capacity',
  'Referral',
  'Direct Mail',
  'CoStar',
  'Listsource',
  'Other',
] as const

export interface HubSpotImportRun {
  id: number
  object_type: string
  status: string
  start_time: string
  end_time?: string | null
  total_fetched: number
  created_count: number
  updated_count: number
  skipped_count: number
  error_count: number
  error_message?: string | null
}

export interface HubSpotMatch {
  id: number
  hubspot_record_type: string
  hubspot_id: string
  internal_record_type?: string | null
  internal_record_id?: number | null
  confidence: MatchConfidence
  status: MatchStatus
  matching_criteria?: string | null
  display_name?: string | null
  internal_display_name?: string | null
  created_at: string
  updated_at: string
}

export interface HubSpotSignal {
  id: number
  lead_id: number
  signal_type: SignalType
  source_engagement_id?: string | null
  extracted_at: string
  raw_evidence?: string | null
}

// ---------------------------------------------------------------------------
// Contact Model Types
// ---------------------------------------------------------------------------

export type ContactRole = 'owner' | 'property_manager' | 'attorney' | 'family_member' | 'other' | 'former_owner'

export type PhoneLabel = 'mobile' | 'home' | 'work' | 'other'

export type EmailLabel = 'personal' | 'work' | 'other'

export interface ContactPhone {
  id: number
  contact_id: number
  value: string
  label: PhoneLabel
  notes?: string | null
  confidence_score?: number | null
  last_outcome?: string | null
  last_called_at?: string | null
  source?: string | null
}

export interface LeadPhone {
  id?: number
  value: string
  label?: PhoneLabel | string
  notes?: string | null
  confidence_score?: number | null
  last_outcome?: string | null
  last_called_at?: string | null
  source?: string | null
}

export interface ContactEmail {
  id: number
  contact_id: number
  value: string
  label: EmailLabel
}

export interface Contact {
  id: number
  first_name: string | null
  last_name: string | null
  role: ContactRole
  role_description: string | null
  notes: string | null
  phones: ContactPhone[]
  emails: ContactEmail[]
  created_at: string | null
  updated_at: string | null
}

export interface PropertyContact extends Contact {
  property_contact_role: ContactRole
  is_primary: boolean
}

export interface PropertyContactLinkRequest {
  contact_id: number
  role: ContactRole
  is_primary: boolean
}

export interface ContactCreatePayload {
  first_name?: string | null
  last_name?: string | null
  role?: ContactRole
  role_description?: string | null
  notes?: string | null
  phones?: Array<{ value: string; label: PhoneLabel }>
  emails?: Array<{ value: string; label: EmailLabel }>
}

export interface ContactUpdatePayload {
  first_name?: string | null
  last_name?: string | null
  role?: ContactRole
  role_description?: string | null
  notes?: string | null
  phones?: Array<{ value: string; label: PhoneLabel }>
  emails?: Array<{ value: string; label: EmailLabel }>
}

// ── Actionable Lead Command Center Types ──────────────────────────────────

export type LeadStatus =
  | 'skip_trace'
  | 'awaiting_skip_trace'
  | 'mailing_no_contact_made'
  | 'mailing_contacted_no_interest'
  | 'mailing_contacted_interested'
  | 'negotiating_remote'
  | 'in_person_appointment'
  | 'offer_delivered'
  | 'deprioritize'
  | 'deal_won'
  | 'deal_lost'
  | 'suppressed'
  | 'do_not_contact';

export type LeadTaskType =
  | 'call_owner_today'
  | 'research_missing_pin'
  | 'match_hubspot_deal'
  | 'run_property_analysis'
  | 'add_to_mail_batch'
  | 'skip_trace_owner'
  | 'custom';

export type LeadTaskStatus = 'open' | 'completed' | 'cancelled' | 'overdue';

export type TimelineEventType =
  | 'note_added'
  | 'email_logged'
  | 'call_logged'
  | 'task_created'
  | 'task_completed'
  | 'task_snoozed'
  | 'recommended_action_changed'
  | 'status_changed'
  | 'hubspot_note'
  | 'hubspot_call'
  | 'hubspot_task'
  | 'hubspot_deal_stage'
  | 'property_analysis_completed'
  | 'lead_imported';

export interface LeadTask {
  id: number | string;
  lead_id: number;
  task_type: LeadTaskType;
  title: string;
  status: LeadTaskStatus;
  due_date: string | null;
  created_at: string;
  completed_at: string | null;
  created_by: string;
  /** 'native' for tasks created in the platform, 'hubspot' for tasks imported from HubSpot */
  source?: 'native' | 'hubspot';
  /** HubSpot engagement/task id when source is hubspot */
  hubspot_task_id?: string | null;
}

export interface LeadTimelineEntry {
  id: number;
  lead_id: number;
  event_type: TimelineEventType;
  occurred_at: string;
  source: 'manual' | 'system' | 'hubspot' | 'hubspot_import';
  actor: string;
  summary: string;
  metadata: Record<string, unknown> | null;
  hubspot_activity_id: string | null;
  is_deleted: boolean;
  created_at: string;
}

export interface RecommendedActionMeta {
  value: CRMRecommendedAction | null;
  recommended_contact_method?: ContactMethod | null;
  outreach_contact?: OutreachContact | null;
  label: string | null;
  explanation: string | null;
  winning_rule?: string | null;
  winning_rule_label?: string | null;
  signals: Record<string, unknown>;
}

export interface DataQualityBreakdown {
  total: number;
  property: number;
  contact: number;
  best_phone_confidence: number | null;
  has_email: boolean;
  email_owner_or_primary?: boolean;
  missing: string[];
}

export interface WorkQueueMembership {
  key: string;
  label: string;
  path: string;
}

export interface QueueRow {
  id: number;
  owner_first_name: string | null;
  owner_last_name: string | null;
  /** Prefer over flat owner_* when present — derived from primary PropertyContact. */
  owner_display_name?: string | null;
  /** Best phone from primary-then-next contacts, else flat phone_1. */
  best_phone?: string | null;
  /** Best email from primary-then-next contacts, else flat email_1. */
  best_email?: string | null;
  property_street: string | null;
  property_city: string | null;
  property_state: string | null;
  property_zip?: string | null;
  lead_score: number;
  lead_status: LeadStatus;
  recommended_action: CRMRecommendedAction | null;
  recommended_contact_method?: ContactMethod | null;
  outreach_action_label?: string | null;
  outreach_contact?: OutreachContact | null;
  due_task_title?: string | null;
  due_task_due_date?: string | null;
  has_property_match: boolean;
  last_contact_date: string | null;
  last_hubspot_sync_at: string | null;
  hubspot_deal_stage: string | null;
  follow_up_overdue: boolean;
  review_required: boolean;
  review_reason: string | null;
  review_triggered_at: string | null;
  unanswered_call_count: number;
  is_warm: boolean;
  last_mailed_at?: string | null;
  last_sale_at?: string | null;
}

export interface QueuePage {
  rows: QueueRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface QueueNavigation {
  queue_key: string;
  lead_id: number;
  position: number | null;
  total: number;
  prev_id: number | null;
  next_id: number | null;
}

export interface QueueCounts {
  todays_action: number;
  previously_warm: number;
  follow_up_overdue: number;
  no_next_action: number;
  needs_review: number;
  do_not_contact: number;
  missing_property_match: number;
  ready_to_mail: number;
  mail_candidates: number;
  prospect_candidates: number;
}

export interface ProspectCandidateSignal {
  signal_type: string;
  severity: string;
  points: number;
  base_points?: number;
  recency_multiplier?: number;
  event_date?: string;
  evidence_key?: string;
  evidence?: Record<string, unknown>;
  label?: string;
}

export interface ProspectCandidate {
  id: number;
  pin: string | null;
  property_street: string | null;
  property_city: string | null;
  property_state: string | null;
  latitude?: number | null;
  longitude?: number | null;
  location_hint: string | null;
  primary_signal_type: string;
  motivation_score: number;
  motivation_pct: number;
  signals: ProspectCandidateSignal[] | null;
  source_feed: string;
  status: string;
  duplicate_lead_id: number | null;
  imported_lead_id: number | null;
  created_at: string | null;
  reviewed_at: string | null;
}

export interface ProspectAreaFilterConfig {
  enabled: boolean;
  label: string | null;
  geometry: {
    type: 'Polygon';
    coordinates: number[][][];
  } | null;
  updated_at: string | null;
}

export interface ProspectAreaFilterStats {
  filter_enabled: boolean;
  total_unfiltered: number;
  total_filtered: number;
  hidden_outside_area: number;
  hidden_no_coords: number;
}

export interface ProspectFeedStatus {
  last_sync_at: string | null;
  next_scheduled_label: string;
  chicago_api_configured?: boolean;
  feeds: Array<{
    feed_name: string;
    last_synced_at: string | null;
    rows_processed: number;
  }>;
}

export interface ProspectCandidatePage {
  rows: ProspectCandidate[];
  total: number;
  page: number;
  per_page: number;
  area_filter?: ProspectAreaFilterStats;
}

export interface ProspectApproveResult {
  lead_id: number;
  duplicate: boolean;
  import_job_id?: number;
}

export interface QuickBriefing {
  bullets: string[];
  generated_at: string;
  updated_at?: string;
  timeline_entries_used?: number;
  open_tasks_used?: number;
  mode?: 'create' | 'revise';
}

/** Owner-org entity research summary on command-center Next Step. */
export interface EntityResearchSummary {
  organization_id: number
  organization_name: string | null
  entity_lookup_status: EntityLookupStatus | string | null
  entity_lookup_person_found: boolean
  entity_lookup_checked_at: string | null
  entity_lookup_error: string | null
  file_number?: string | null
}

export interface CommandCenterPayload {
  id: number;
  owner_first_name: string | null;
  owner_last_name: string | null;
  owner_2_first_name?: string | null;
  owner_2_last_name?: string | null;
  /** Relational contacts — prefer over flat owner/phone/email fields when present. */
  contacts?: PropertyContactSummary[];
  /** True when sale is newer than date_skip_traced (contacts may be prior owner). */
  contacts_likely_prior_owner?: boolean;
  /** ISO sale date that made contacts stale, when applicable. */
  contacts_stale_since?: string | null;
  /** Point-in-time past owner snapshots (mailing + contacts). */
  past_owners?: PastOwnerSnapshot[];
  /** Linked companies / LLCs (HubSpot-style Organizations). */
  organizations?: PropertyOrganizationSummary[];
  /** Owner-org Illinois LLC / entity research status for Next Step visibility. */
  entity_research?: EntityResearchSummary | null;
  /** Other buildings owned by the same person (not same-address duplicates). */
  related_properties?: RelatedPropertySummary[];
  property_street: string | null;
  property_city: string | null;
  property_state: string | null;
  property_zip?: string | null;
  address_2?: string | null;
  property_type?: string | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  square_footage?: number | null;
  year_built?: number | null;
  county_assessor_pin?: string | null;
  is_cook_county_eligible?: boolean;
  ownership_type?: string | null;
  acquisition_date?: string | null;
  mailing_address?: string | null;
  mailing_city?: string | null;
  mailing_state?: string | null;
  mailing_zip?: string | null;
  phone_1?: string | null;
  phone_2?: string | null;
  phone_3?: string | null;
  phone_4?: string | null;
  phone_5?: string | null;
  phone_6?: string | null;
  phone_7?: string | null;
  email_1?: string | null;
  email_2?: string | null;
  email_3?: string | null;
  email_4?: string | null;
  email_5?: string | null;
  phones?: LeadPhone[];
  emails?: string[];
  notes?: string | null;
  lead_score: number;
  lead_status: LeadStatus;
  lead_category?: string;
  review_reason?: string | null;
  has_property_match: boolean;
  analysis_session_id: number | null;
  hubspot_deal_stage?: string | null;
  hubspot_deal_name?: string | null;
  deal_source?: string | null;
  deal_description?: string | null;
  source?: string | null;
  data_source?: string | null;
  last_hubspot_sync_at?: string | null;
  hubspot_has_confirmed_deal?: boolean;
  hubspot_sync_stale?: boolean;
  hubspot_deal_last_updated_at?: string | null;
  last_contact_date?: string | null;
  date_added_to_hubspot?: string | null;
  recommended_action: RecommendedActionMeta;
  open_tasks: LeadTask[];
  up_next_to_mail?: boolean | null;
  mail_queue_status?: 'queued' | 'sent_recently' | null;
  is_mailable?: boolean;
  mail_eligible?: boolean;
  mail_ineligible_reason?: 'recently_sold' | 'invalid_owner_address' | null;
  mail_eligible_date?: string | null;
  most_recent_sale_display?: string | null;
  most_recent_sale_price?: number | null;
  /** Newest-first Cook County parcel sales for this PIN (cache or live fallback). */
  sale_history?: Array<{
    sale_date?: string | null;
    sale_price?: number | null;
    sale_type?: string | null;
  }>;
  sale_date_meta?: {
    last_updated_at?: string | null;
    last_checked_at?: string | null;
    source?: string | null;
    status?: string | null;
    error_reason?: string | null;
  };
  timeline: {
    entries: LeadTimelineEntry[];
    total: number;
    page: number;
    per_page: number;
  };
  /** Latest persisted Gemini quick briefing (null until Generate). */
  quick_briefing?: QuickBriefing | null;
  data_completeness_score?: number | null;
  data_quality_breakdown?: DataQualityBreakdown | null;
  work_queues?: WorkQueueMembership[];
  condo_risk_status?: CondoRiskStatus | null;
  building_sale_possible?: BuildingSalePossible | null;
  condo_analysis_id?: number | null;
  assessor_class?: string | null;
  units?: number | null;
  units_allowed?: number | null;
}

export interface BuildingOwnershipAnalyzeResult {
  lead_id: number
  condo_analysis_id?: number | null
  condo_risk_status?: CondoRiskStatus | null
  building_sale_possible?: BuildingSalePossible | null
  recommended_action?: string | null
  analysis_details?: Record<string, unknown> | null
  classification?: {
    condo_risk_status?: CondoRiskStatus
    building_sale_possible?: BuildingSalePossible
    reason?: string
    confidence?: string
    triggered_rules?: string[]
  } | null
  skipped?: boolean
  skip_reason?: string | null
}

export interface LogCallFollowUpPayload {
  title: string;
  due_date: string;
  task_type?: string;
}

export interface LogCallPayload {
  outcome: 'answered' | 'voicemail' | 'no_answer' | 'busy' | 'wrong_number';
  duration_minutes?: number | null;
  notes?: string | null;
  contact_id?: number | null;
  contact_phone_id?: number | null;
  phone_number?: string | null;
  phone_label?: string | null;
  mail_campaign_id?: number | null;
  complete_task_id?: number | null;
  follow_up?: LogCallFollowUpPayload | null;
}

export interface LogNotePayload {
  body: string;
  contact_id?: number | null;
  contact_email_id?: number | null;
  email_address?: string | null;
  email_label?: string | null;
  subject?: string | null;
}

export interface BulkActionResult {
  successes: number;
  failures: number;
  /** Optional detailed breakdown shown instead of the generic failure message. */
  message?: string;
  mail_enqueue?: {
    attempt_id?: number;
    added: number;
    skipped: number;
    invalid: number;
    results: Array<{
      lead_id: number;
      status: string;
      error?: string;
      owner_name?: string | null;
      property_street?: string | null;
      sale_date?: string | null;
      rescheduled_to?: string | null;
      rescheduled_task_count?: number;
      skip_trace_scheduled?: boolean;
      skip_trace_task_id?: number | null;
      removed_queue_item_count?: number;
    }>;
  };
}

// ---------------------------------------------------------------------------
// HubSpot Webhook Sync Types
// ---------------------------------------------------------------------------

export type WebhookLogStatus =
  | 'pending'
  | 'processing'
  | 'processed'
  | 'failed'
  | 'deduplicated'
  | 'loop_suppressed'

export interface WebhookLog {
  id: number
  hubspot_object_type: string
  hubspot_object_id: string
  event_type: string
  status: WebhookLogStatus
  error_message: string | null
  received_at: string
  processed_at: string | null
}

export interface WebhookLogSummary {
  processed_count: number
  failed_count: number
  deduplicated_count: number
  last_synced_at: string | null
}

export interface WebhookLogListResponse {
  logs: WebhookLog[]
  total: number
  page: number
  per_page: number
  pages: number
}

// ---------------------------------------------------------------------------
// Authentication Types (multi-user-lead-exclusivity)
// ---------------------------------------------------------------------------

export interface AuthUser {
  user_id: string
  email: string
  display_name: string
  is_admin: boolean
}

export interface AuthContextValue {
  user: AuthUser | null       // null = unauthenticated
  token: string | null
  login: (email: string, password: string) => Promise<void>
  loginWithToken: (sessionToken: string, userId: string) => void
  logout: () => void
  isLoading: boolean          // true during initial token validation on load
}

// ---------------------------------------------------------------------------
// Admin Panel Types
// ---------------------------------------------------------------------------

export interface AdminUserSummary {
  user_id: string
  email: string
  display_name: string
  is_active: boolean
  is_admin: boolean
  created_at: string
  lead_count: number
  marketing_list_count: number
  import_job_count: number
}

export interface AdminLead {
  id: number
  owner_user_id: string
  owner_display_name: string
  property_street: string | null
  property_city: string | null
  property_state: string | null
  lead_status: string
  lead_score: number
  created_at: string
}

export interface AdminLeadParams {
  owner_user_id?: string
  page?: number
  page_size?: number
}

export interface AdminLeadListResponse {
  leads: AdminLead[]
  total_count: number
  page: number
  page_size: number
}

// ---------------------------------------------------------------------------
// Pipeline Stage Config & Kanban Types
// ---------------------------------------------------------------------------

export interface PipelineStage {
  id: number
  stage_name: string
  order: number
  weight: number
}

export interface DealKanbanCard {
  id: number
  property_address: string
  purchase_price: string
  unit_count: number
  status: string
  priority_score: string | null
  created_by_user_id: string
  property_city: string | null
  property_state: string | null
  close_date: string | null
  created_at: string | null
  updated_at: string | null
}

export type KanbanSortField = 'purchase_price' | 'priority_score' | 'lead_score'

export interface KanbanFilters {
  assigneeUserId?: string
  valueMin?: number
  valueMax?: number
  closingDateFrom?: string
  closingDateTo?: string
}

export interface KanbanState {
  stages: PipelineStage[]
  dealsByStage: Record<string, DealKanbanCard[]>
  filters: KanbanFilters
  sortField: KanbanSortField
  sortDirection: 'asc' | 'desc'
  isLoading: boolean
  error: string | null
}

// ---------------------------------------------------------------------------
// Lead Kanban Types (reads from leads table instead of deals table)
// ---------------------------------------------------------------------------

export interface LeadKanbanCard {
  id: number
  property_address: string
  owner_name: string
  lead_status: string | null
  recommended_action: string | null
  lead_score: number
  lead_category: string
  source_type: string
  last_contact_date: string | null
  analysis_complete: boolean
  is_warm: boolean
  has_phone: boolean
  has_email: boolean
  has_property_match: boolean
}

export interface LeadKanbanColumn {
  id: string
  label: string
  icon: string
  leads: LeadKanbanCard[]
  count: number
  sort_order: number
}

export interface LeadKanbanResponse {
  columns: LeadKanbanColumn[]
  total_counts: Record<string, number>
}

// ---------------------------------------------------------------------------
// Global Search Types
// ---------------------------------------------------------------------------

export interface SearchMatchContext {
  type: 'phone' | 'email' | 'name' | 'address' | 'lead_id'
  value: string
}

export interface SearchResultItem {
  id: number
  type: 'lead' | 'session'
  label: string
  nav_path: string
  lead_score?: number | null
  lead_status?: string | null
  /** Buildings in this person's portfolio including this lead (1 = only this one). */
  property_count?: number | null
  /** Same-person grouping key (user + last + first token). */
  person_key?: string | null
  owner_display_name?: string | null
  property_street?: string | null
  /** This building plus sibling portfolio rows for search grouping. */
  portfolio_properties?: RelatedPropertySummary[] | null
  relevance_score?: number | null
  created_at?: string | null
  status?: string | null
  match_context?: SearchMatchContext | null
}

export interface SearchResponse {
  q: string
  page: number
  per_page: number
  leads: SearchResultItem[]
  leads_total: number
  sessions: SearchResultItem[]
  sessions_total: number
}

export interface SearchParams {
  q: string
  page?: number
  per_page?: number
  signal?: AbortSignal
}

// -----------------------------------------------------------------------
// Data Sources Panel Types
// -----------------------------------------------------------------------

export type SocrataDatasetStatusValue = 'fresh' | 'stale' | 'empty' | 'never_synced'
export type RefreshType = 'periodic' | 'on_demand' | 'static' | 'automatic'

export interface SocrataDatasetStatus {
  name: string
  source_type: 'socrata'
  refresh_type: 'periodic'
  is_active: boolean
  status: SocrataDatasetStatusValue
  last_refreshed_at: string | null   // ISO-8601 UTC
  row_count: number
  days_since_sync: number | null     // always >= 0 when non-null
  last_error: string | null
}

export interface EnrichmentSourceStatus {
  name: string
  source_type: 'enrichment'
  refresh_type: 'on_demand' | 'automatic'
  is_active: boolean
  last_refreshed_at: string | null
  success_count: number
  failed_count: number
  pending_count: number
  no_results_count: number
  not_run_count: number
  total_leads_count: number
}

export interface ImportSourceStatus {
  name: string
  source_type: 'import'
  refresh_type: 'static'
  is_active: boolean
  last_refreshed_at: string | null
  rows_imported: number | null
  import_status: string | null
  completed_import_count?: number
  scope?: 'user' | 'org' | null
}

export interface PropertyMatchPreview {
  found: boolean
  entered_address: {
    property_street: string | null
    property_city: string | null
    property_state: string | null
    property_zip: string | null
  }
  recommended_address: {
    property_street: string | null
    property_city: string | null
    property_state: string | null
    property_zip: string | null
    property_type?: string | null
    county_assessor_pin?: string | null
  } | null
  pin: string | null
  pins?: string[]
  pin_count?: number | null
  connector: string | null
  parcel_fields?: Record<string, unknown> | null
  message?: string | null
  lead_id?: number
  address_complete?: boolean
  reason?: 'incomplete_address' | 'no_connector' | 'no_match' | null
}

export interface BuildingOwnershipDetail {
  lead_id?: number
  id: number
  normalized_address: string
  condo_risk_status: CondoRiskStatus
  building_sale_possible: BuildingSalePossible
  pin_count?: number
  owner_count?: number
  analysis_details?: Record<string, unknown> | null
  assessor_class?: string | null
  manually_reviewed?: boolean
  manual_override_status?: CondoRiskStatus | null
  analyzed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface NoNextActionStatusCounts {
  [leadStatus: string]: number
}

export interface HubSpotSourceStatus {
  name: string
  source_type: 'hubspot'
  refresh_type: 'on_demand'
  is_active: boolean
  connected: boolean
}

export interface GISConnectorStatus {
  name: string
  market: string
  counties: string[]
  source_type: 'gis'
  refresh_type: 'automatic'
  is_active: boolean
  matched_count: number
  unmatched_count: number
  total_count: number
  api_url: string
}

export interface DataSourceStatus {
  socrata_datasets: SocrataDatasetStatus[]
  enrichment_sources: EnrichmentSourceStatus[]
  import_source: ImportSourceStatus
  hubspot_source: HubSpotSourceStatus
  gis_connectors: GISConnectorStatus[]
}
