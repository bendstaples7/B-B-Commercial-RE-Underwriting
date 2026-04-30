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
  owner_first_name: string
  owner_last_name: string
  mailing_city: string | null
  mailing_state: string | null
  mailing_zip: string | null
  lead_score: number
  data_source: string | null
  created_at: string | null
  updated_at: string | null
  source: string | null
  notes: string | null
  needs_skip_trace: boolean | null
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
