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
