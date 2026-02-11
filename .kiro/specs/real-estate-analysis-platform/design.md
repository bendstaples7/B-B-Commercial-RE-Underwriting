# Design Document

## Overview

The real estate analysis platform is a web-based application that automates property valuation through a 6-step workflow. The system integrates with multiple property data sources, performs comparable sales analysis with weighted scoring, generates valuation models, and produces comprehensive reports with optional scenario analysis.

The architecture follows a client-server model with a React-based frontend, Python Flask backend, PostgreSQL database for session persistence, and integration adapters for external property data APIs.

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Web Browser                          │
│                     (React Frontend)                        │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS/REST API
┌────────────────────────┴────────────────────────────────────┐
│                    Flask Backend API                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Workflow   │  │  Valuation   │  │   Scenario   │     │
│  │  Controller  │  │    Engine    │  │   Analysis   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│              Data Integration Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │     MLS      │  │  Tax Assessor│  │  Municipal   │     │
│  │   Adapter    │  │   Adapter    │  │    Data      │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                  PostgreSQL Database                        │
│         (Session State, User Data, Cache)                   │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

**Frontend:**
- React 18+ with TypeScript for type safety
- Material-UI for responsive component library
- React Query for API state management
- Recharts for data visualization

**Backend:**
- Python 3.10+ with Flask web framework
- SQLAlchemy ORM for database operations
- Celery for asynchronous task processing
- Redis for caching and task queue

**Database:**
- PostgreSQL 14+ for persistent storage
- Redis for session cache and rate limiting

**External Integrations:**
- MLS API (varies by region)
- County tax assessor APIs
- Google Maps API for geocoding and distance calculations
- Census Bureau API for demographic data

## Components and Interfaces

### 1. Workflow Controller

**Responsibility:** Orchestrates the 6-step analysis workflow, manages state transitions, and coordinates between components.

**Interface:**
```python
class WorkflowController:
    def start_analysis(self, address: str, user_id: str) -> AnalysisSession
    def get_session_state(self, session_id: str) -> SessionState
    def advance_to_step(self, session_id: str, step: WorkflowStep) -> StepResult
    def update_step_data(self, session_id: str, step: WorkflowStep, data: dict) -> bool
    def go_back_to_step(self, session_id: str, step: WorkflowStep) -> StepResult
```

**Key Methods:**
- `start_analysis()`: Initializes new analysis session with property address
- `advance_to_step()`: Validates current step completion and moves to next step
- `update_step_data()`: Handles user modifications and triggers recalculation
- `go_back_to_step()`: Allows navigation to previous steps while preserving data

### 2. Property Data Service

**Responsibility:** Retrieves property information from multiple data sources with fallback logic.

**Interface:**
```python
class PropertyDataService:
    def fetch_property_facts(self, address: str) -> PropertyFacts
    def fetch_with_fallback(self, address: str, field: str) -> Optional[Any]
    def geocode_address(self, address: str) -> Coordinates
    def validate_property_data(self, facts: PropertyFacts) -> ValidationResult
```

**Data Source Priority:**
1. MLS API (primary for sales data)
2. County tax assessor (property characteristics)
3. Chicago city data portal (square footage fallback)
4. Municipal building records
5. User manual entry (last resort)

**Caching Strategy:**
- Cache property facts for 24 hours
- Cache geocoding results indefinitely
- Invalidate cache on user manual updates

### 3. Comparable Sales Finder

**Responsibility:** Searches for comparable sales using radius expansion and filters.

**Interface:**
```python
class ComparableSalesFinder:
    def find_comparables(
        self, 
        subject: PropertyFacts, 
        min_count: int = 10,
        max_age_months: int = 12
    ) -> List[ComparableSale]
    
    def expand_search_radius(
        self, 
        center: Coordinates, 
        current_radius: float
    ) -> float
    
    def filter_by_property_type(
        self, 
        sales: List[Sale], 
        property_type: PropertyType
    ) -> List[Sale]
```

**Search Algorithm:**
```
1. Start with 0.25 mile radius
2. Query sales within radius, filter by:
   - Sale date within 12 months
   - Property type matches subject
   - Valid sale (not foreclosure/family transfer)
3. If count < 10:
   - Expand radius: 0.25 → 0.5 → 0.75 → 1.0 miles
   - Repeat query
4. Return first 10+ results or all if < 10 at max radius
```

### 4. Weighted Scoring Engine

**Responsibility:** Calculates similarity scores for comparable properties using weighted criteria.

**Interface:**
```python
class WeightedScoringEngine:
    def calculate_score(
        self, 
        subject: PropertyFacts, 
        comparable: ComparableSale
    ) -> ScoringResult
    
    def rank_comparables(
        self, 
        subject: PropertyFacts, 
        comparables: List[ComparableSale]
    ) -> List[RankedComparable]
```

**Scoring Formula:**
```
Total Score = (Recency × 0.16) + (Proximity × 0.15) + (Units × 0.15) + 
              (Beds/Baths × 0.15) + (Sq Ft × 0.15) + (Construction × 0.12) + 
              (Interior × 0.12)

Where each component score is normalized to 0-100 scale:
- Recency: 100 - (days_old / 365 × 100)
- Proximity: 100 - (distance_miles / max_distance × 100)
- Units: 100 - (|subject_units - comp_units| / max_units × 100)
- Beds/Baths: 100 - (|subject_beds - comp_beds| + |subject_baths - comp_baths|) / max_diff × 100
- Sq Ft: 100 - (|subject_sqft - comp_sqft| / subject_sqft × 100)
- Construction: categorical match (100 if same, 50 if similar, 0 if different)
- Interior: categorical match (100 if same, 75/50/25 based on condition gap)
```

### 5. Valuation Engine

**Responsibility:** Generates valuation models using top comparables with adjustments.

**Interface:**
```python
class ValuationEngine:
    def calculate_valuations(
        self, 
        subject: PropertyFacts, 
        top_comps: List[RankedComparable]
    ) -> ValuationResult
    
    def calculate_price_per_sqft(self, comp: ComparableSale) -> float
    def calculate_price_per_unit(self, comp: ComparableSale) -> float
    def calculate_price_per_bedroom(self, comp: ComparableSale) -> float
    def calculate_adjusted_value(
        self, 
        subject: PropertyFacts, 
        comp: ComparableSale
    ) -> AdjustedValuation
    
    def compute_arv_range(self, valuations: List[float]) -> ARVRange
```

**Adjustment Factors:**
```python
ADJUSTMENT_FACTORS = {
    'unit_difference': 15000,  # per unit
    'bedroom_difference': 5000,  # per bedroom
    'bathroom_difference': 3000,  # per bathroom
    'sqft_difference': 50,  # per square foot
    'construction_upgrade': 10000,  # brick vs frame
    'interior_condition': {
        'needs_gut_to_poor': -20000,
        'poor_to_average': -10000,
        'average_to_new': 15000,
        'new_to_high_end': 25000
    },
    'basement': 8000,
    'parking': 5000  # per space
}
```

**ARV Calculation:**
```
1. For each top 5 comparable:
   - Base value = comparable sale price
   - Apply adjustments for each difference
   - Calculate 4 valuation methods ($/sqft, $/unit, $/bed, adjusted)
   
2. Collect all valuation estimates (5 comps × 4 methods = 20 values)

3. Calculate ARV range:
   - Conservative: 25th percentile
   - Likely: 50th percentile (median)
   - Aggressive: 75th percentile
```

### 6. Scenario Analysis Engine

**Responsibility:** Performs financial modeling for wholesale, fix & flip, and buy & hold strategies.

**Interface:**
```python
class ScenarioAnalysisEngine:
    def analyze_wholesale(
        self, 
        arv: ARVRange, 
        subject: PropertyFacts
    ) -> WholesaleScenario
    
    def analyze_fix_and_flip(
        self, 
        arv: ARVRange, 
        subject: PropertyFacts,
        renovation_budget: float
    ) -> FixFlipScenario
    
    def analyze_buy_and_hold(
        self, 
        arv: ARVRange, 
        subject: PropertyFacts,
        market_rent: float
    ) -> BuyHoldScenario
    
    def compare_scenarios(
        self, 
        scenarios: List[Scenario],
        price_points: List[float]
    ) -> ScenarioComparison
```

**Wholesale Model:**
```
MAO = Conservative ARV × 0.70 - Estimated Repairs
Contract Price = MAO × 0.95
Assignment Fee = Contract Price × 0.05 to 0.10
```

**Fix & Flip Model:**
```
Acquisition Cost = Purchase Price
Renovation Cost = User Input
Holding Costs = (Acquisition + Renovation) × 0.02 × months_to_flip
Financing Costs = (Acquisition + Renovation) × 0.75 × 0.11 × (months_to_flip / 12)
Closing Costs = Likely ARV × 0.08
Total Cost = Acquisition + Renovation + Holding + Financing + Closing
Net Profit = Likely ARV - Total Cost
ROI = Net Profit / (Acquisition + Renovation) × 0.25
```

**Buy & Hold Model:**
```
Capital Structure 1 (Owner-Occupied):
  Down Payment = Purchase Price × 0.05
  Loan Amount = Purchase Price × 0.95
  Interest Rate = 6.5%
  Monthly Payment = PMT(rate/12, 360, -loan_amount)

Capital Structure 2 (Investor):
  Down Payment = Purchase Price × 0.25
  Loan Amount = Purchase Price × 0.75
  Interest Rate = 7.5%
  Monthly Payment = PMT(rate/12, 360, -loan_amount)

For each structure:
  Monthly Rent = Market Rent (from comparable rentals)
  Monthly Expenses = Property Tax / 12 + Insurance + Maintenance + Vacancy Reserve
  Monthly Cash Flow = Rent - Payment - Expenses
  Cash on Cash Return = (Cash Flow × 12) / Down Payment
  Cap Rate = (Rent × 12 - Expenses × 12) / Purchase Price
```

### 7. Report Generator

**Responsibility:** Formats analysis results into structured reports with export capabilities.

**Interface:**
```python
class ReportGenerator:
    def generate_report(self, session: AnalysisSession) -> Report
    def export_to_excel(self, report: Report) -> bytes
    def export_to_google_sheets(self, report: Report, user_credentials: dict) -> str
    def format_section_a(self, subject: PropertyFacts) -> ReportSection
    def format_section_b(self, comparables: List[ComparableSale]) -> ReportSection
    def format_section_c(self, ranked: List[RankedComparable]) -> ReportSection
    def format_section_d(self, valuations: ValuationResult) -> ReportSection
    def format_section_e(self, arv: ARVRange) -> ReportSection
    def format_section_f(self, key_drivers: List[str]) -> ReportSection
```

**Report Structure:**
- Section A: Property facts table (15+ fields)
- Section B: Comparable sales table (10+ rows, 14 columns)
- Section C: Weighted ranking table (scores by criteria)
- Section D: Valuation models (narrative + metrics table)
- Section E: ARV range (conservative/likely/aggressive)
- Section F: Key drivers (bullet points)
- Optional: Scenario analysis tables

## Data Models

### PropertyFacts
```python
@dataclass
class PropertyFacts:
    address: str
    property_type: PropertyType  # SINGLE_FAMILY, MULTI_FAMILY, COMMERCIAL
    units: int
    bedrooms: int
    bathrooms: float
    square_footage: int
    lot_size: int  # square feet
    year_built: int
    construction_type: ConstructionType  # FRAME, BRICK, MASONRY
    basement: bool
    parking_spaces: int
    last_sale_price: Optional[float]
    last_sale_date: Optional[date]
    assessed_value: float
    annual_taxes: float
    zoning: str
    interior_condition: InteriorCondition  # NEEDS_GUT, POOR, AVERAGE, NEW_RENO, HIGH_END
    coordinates: Coordinates
    data_source: str  # tracks which API provided data
    user_modified_fields: List[str]
```

### ComparableSale
```python
@dataclass
class ComparableSale:
    id: str
    address: str
    sale_date: date
    sale_price: float
    property_type: PropertyType
    units: int
    bedrooms: int
    bathrooms: float
    square_footage: int
    lot_size: int
    year_built: int
    construction_type: ConstructionType
    interior_condition: InteriorCondition
    distance_miles: float
    coordinates: Coordinates
    similarity_notes: str
```

### RankedComparable
```python
@dataclass
class RankedComparable:
    comparable: ComparableSale
    total_score: float
    score_breakdown: ScoringBreakdown
    rank: int
```

### ScoringBreakdown
```python
@dataclass
class ScoringBreakdown:
    recency_score: float
    proximity_score: float
    units_score: float
    beds_baths_score: float
    sqft_score: float
    construction_score: float
    interior_score: float
```

### ValuationResult
```python
@dataclass
class ValuationResult:
    comparable_valuations: List[ComparableValuation]
    arv_range: ARVRange
    key_drivers: List[str]
```

### ComparableValuation
```python
@dataclass
class ComparableValuation:
    comparable: ComparableSale
    price_per_sqft: float
    price_per_unit: float
    price_per_bedroom: float
    adjusted_value: float
    adjustments: List[Adjustment]
    narrative: str
```

### Adjustment
```python
@dataclass
class Adjustment:
    category: str  # 'units', 'bedrooms', 'sqft', 'construction', 'interior'
    difference: Any  # numeric or categorical
    adjustment_amount: float
    explanation: str
```

### ARVRange
```python
@dataclass
class ARVRange:
    conservative: float  # 25th percentile
    likely: float  # median
    aggressive: float  # 75th percentile
    all_valuations: List[float]
```

### AnalysisSession
```python
@dataclass
class AnalysisSession:
    session_id: str
    user_id: str
    created_at: datetime
    current_step: WorkflowStep
    subject_property: Optional[PropertyFacts]
    comparables: List[ComparableSale]
    ranked_comparables: List[RankedComparable]
    valuation_result: Optional[ValuationResult]
    scenarios: List[Scenario]
    report: Optional[Report]
```

### Scenario (Base Class)
```python
@dataclass
class Scenario:
    scenario_type: ScenarioType  # WHOLESALE, FIX_FLIP, BUY_HOLD
    purchase_price: float
    summary: dict
```

### WholesaleScenario
```python
@dataclass
class WholesaleScenario(Scenario):
    mao: float
    contract_price: float
    assignment_fee_low: float
    assignment_fee_high: float
    estimated_repairs: float
```

### FixFlipScenario
```python
@dataclass
class FixFlipScenario(Scenario):
    acquisition_cost: float
    renovation_cost: float
    holding_costs: float
    financing_costs: float
    closing_costs: float
    total_cost: float
    exit_value: float
    net_profit: float
    roi: float
    months_to_flip: int
```

### BuyHoldScenario
```python
@dataclass
class BuyHoldScenario(Scenario):
    capital_structures: List[CapitalStructure]
    market_rent: float
    price_points: List[PricePoint]
```

### CapitalStructure
```python
@dataclass
class CapitalStructure:
    name: str  # "5% Down Owner-Occupied" or "25% Down Investor"
    down_payment_percent: float
    interest_rate: float
    loan_term_months: int
```

### PricePoint
```python
@dataclass
class PricePoint:
    purchase_price: float
    down_payment: float
    loan_amount: float
    monthly_payment: float
    monthly_rent: float
    monthly_expenses: float
    monthly_cash_flow: float
    cash_on_cash_return: float
    cap_rate: float
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property 1: Property Data Retrieval Completeness
*For any* valid property address, when property facts are retrieved, the returned PropertyFacts object should contain all required fields (property_type, units, bedrooms, bathrooms, square_footage, lot_size, year_built, construction_type, basement, parking_spaces, assessed_value, annual_taxes, zoning) with valid data types.
**Validates: Requirements 1.1**

### Property 2: Data Source Fallback Sequence
*For any* property address where primary data source fails for a specific field, the system should attempt retrieval from fallback sources in the correct priority order (Chicago city data → tax assessor → municipal databases) before requesting manual entry.
**Validates: Requirements 1.2, 13.1**

### Property 3: Workflow Gate Enforcement
*For any* workflow step requiring user confirmation, attempting to advance to the next step without explicit approval should fail and keep the session at the current step.
**Validates: Requirements 1.4, 3.4**

### Property 4: Failed Field Manual Entry
*For any* property field where data retrieval fails from all sources, the system should mark the field as unavailable and accept user manual entry without blocking workflow progression.
**Validates: Requirements 1.5**

### Property 5: Comparable Sales Minimum Count
*For any* subject property, the comparable sales search should return at least 10 comparable properties sold within the last 12 months, or all available comparables if fewer than 10 exist within maximum search radius.
**Validates: Requirements 2.1**

### Property 6: Search Radius Expansion Sequence
*For any* subject property location where fewer than 10 comparables exist at current radius, the system should expand the search radius in the exact sequence: 0.25mi → 0.5mi → 0.75mi → 1.0mi, stopping when 10+ comparables are found or maximum radius is reached.
**Validates: Requirements 2.2**

### Property 7: Comparable Data Completeness
*For any* list of comparable sales returned by the search, each comparable should have all required fields populated (address, sale_date, sale_price, property_type, units, bedrooms, bathrooms, square_footage, lot_size, year_built, construction_type, interior_condition, distance_miles).
**Validates: Requirements 2.3**

### Property 8: Subject Property Display Position
*For any* comparable sales display, the subject property should appear at index 0 (first row) and all comparable properties should appear in subsequent rows.
**Validates: Requirements 2.4**

### Property 9: Comparable List Modification
*For any* comparable in the displayed list, the user should be able to remove it, and after removal, the system should validate that at least 10 comparables remain before allowing workflow advancement.
**Validates: Requirements 3.2, 3.5**

### Property 10: Comparable Addition
*For any* user-provided comparable data, the system should add it to the comparable list and include it in subsequent analysis steps.
**Validates: Requirements 3.3**

### Property 11: Weighted Scoring Formula Correctness
*For any* subject property and comparable sale, the calculated total score should equal the sum of: (recency_score × 0.16) + (proximity_score × 0.15) + (units_score × 0.15) + (beds_baths_score × 0.15) + (sqft_score × 0.15) + (construction_score × 0.12) + (interior_score × 0.12), and all component weights should sum to exactly 1.0.
**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**

### Property 12: Comparable Ranking Order
*For any* list of scored comparables, the ranked output should be sorted in descending order by total_score, with the highest-scoring comparable at rank 1.
**Validates: Requirements 4.8**

### Property 13: Top Comparables Selection
*For any* valuation model generation, the system should use exactly the top 5 ranked comparables (ranks 1-5) as input.
**Validates: Requirements 5.1**

### Property 14: Valuation Methods Completeness
*For any* comparable in the top 5, the system should calculate all four valuation methods: price_per_sqft, price_per_unit, price_per_bedroom, and adjusted_value.
**Validates: Requirements 5.2**

### Property 15: Adjustment Categories Completeness
*For any* comparable with differences from the subject property, the adjusted valuation should include adjustments for all applicable categories: units, bedrooms, bathrooms, square_footage, construction_type, interior_condition, and major value items (basement, parking).
**Validates: Requirements 5.3**

### Property 16: Valuation Narrative Generation
*For any* comparable in the valuation model, a non-empty narrative string should be generated explaining the adjustments applied.
**Validates: Requirements 5.4**

### Property 17: ARV Range Calculation
*For any* set of valuation estimates from the top 5 comparables, the conservative ARV should equal the 25th percentile, the likely ARV should equal the median (50th percentile), and the aggressive ARV should equal the 75th percentile of all valuation values.
**Validates: Requirements 5.6**

### Property 18: Report Structure Completeness
*For any* generated report, it should contain all six required sections: Section A (Subject Property Facts), Section B (Comparable Sales), Section C (Weighted Ranking), Section D (Valuation Models), Section E (Final ARV Range), and Section F (Key Drivers).
**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**

### Property 19: Excel Export Validity
*For any* completed report, the Excel export function should generate valid Excel file bytes that can be successfully opened by Excel or compatible spreadsheet applications.
**Validates: Requirements 6.7**

### Property 20: Google Sheets Export Validity
*For any* completed report with valid user credentials, the Google Sheets export function should create a new Google Sheet and return a valid shareable URL.
**Validates: Requirements 6.8**

### Property 21: Wholesale MAO Calculation
*For any* conservative ARV value and estimated repair cost, the calculated MAO should equal (conservative_ARV × 0.70) - estimated_repairs.
**Validates: Requirements 7.1**

### Property 22: Wholesale Contract Price Calculation
*For any* calculated MAO, the contract price should equal MAO × 0.95.
**Validates: Requirements 7.2**

### Property 23: Wholesale Assignment Fee Calculation
*For any* contract price, the assignment fee range should be calculated as (contract_price × 0.05) for low estimate and (contract_price × 0.10) for high estimate.
**Validates: Requirements 7.3**

### Property 24: Fix and Flip Interest Rate
*For any* fix and flip scenario, the financing model should use exactly 11% annual interest rate for interest-only loan calculations.
**Validates: Requirements 8.1**

### Property 25: Fix and Flip LTC Ratio
*For any* fix and flip scenario, the loan amount should equal exactly 75% of the total project cost (acquisition + renovation).
**Validates: Requirements 8.2**

### Property 26: Fix and Flip Total Cost Calculation
*For any* fix and flip scenario, the total project cost should equal the sum of acquisition_cost + renovation_cost + holding_costs + financing_costs + closing_costs.
**Validates: Requirements 8.3**

### Property 27: Fix and Flip Profit Calculation
*For any* fix and flip scenario, the net profit should equal likely_ARV - total_project_cost.
**Validates: Requirements 8.4**

### Property 28: Buy and Hold Capital Structures
*For any* buy and hold scenario, the system should generate exactly 2 capital structures: one with 5% down payment (owner-occupied) and one with 25% down payment (investor).
**Validates: Requirements 9.1**

### Property 29: Buy and Hold Market Rent Retrieval
*For any* buy and hold scenario, the system should retrieve and include market rent data from comparable rental properties.
**Validates: Requirements 9.2**

### Property 30: Buy and Hold Price Points
*For any* buy and hold scenario, the system should generate multiple price points (minimum 3: low, medium, high) with cash flow analysis for each.
**Validates: Requirements 9.3**

### Property 31: Buy and Hold Metrics Completeness
*For any* price point and capital structure combination in buy and hold analysis, the system should calculate monthly_cash_flow, cash_on_cash_return, and cap_rate.
**Validates: Requirements 9.4**

### Property 32: Scenario Comparison Completeness
*For any* set of analyzed scenarios, the comparison table should include all selected scenario types (wholesale, fix_flip, buy_hold) with results for low, medium, and high price points.
**Validates: Requirements 10.1, 10.2**

### Property 33: Scenario ROI Calculation
*For any* scenario and price point combination, the system should calculate and display the return on investment (ROI) value.
**Validates: Requirements 10.3**

### Property 34: Highest ROI Highlighting
*For any* price point in the scenario comparison, exactly one strategy should be highlighted as having the highest ROI at that price point.
**Validates: Requirements 10.4**

### Property 35: Data Field Editability
*For any* workflow step, all displayed data fields should be editable by the user with appropriate validation.
**Validates: Requirements 11.1**

### Property 36: Data Validation on Modification
*For any* user data modification, the system should validate the input against data type constraints (e.g., numeric fields accept only numbers) and range constraints (e.g., year_built between 1800 and current year), rejecting invalid inputs with descriptive error messages.
**Validates: Requirements 11.2**

### Property 37: Downstream Recalculation Cascade
*For any* user modification to data in an earlier workflow step, all dependent calculations in subsequent steps should be automatically recalculated to reflect the change.
**Validates: Requirements 11.3, 11.5**

### Property 38: State Preservation During Navigation
*For any* user navigation backward to a previous step, all user modifications should be preserved, and re-executing forward should maintain those changes unless explicitly modified again.
**Validates: Requirements 11.4**

### Property 39: Property Type Method Selection
*For any* property identified as residential, the system should apply residential valuation methods, and for any property identified as commercial, the system should apply commercial valuation methods including income capitalization approach.
**Validates: Requirements 12.1, 12.2**

### Property 40: Property Type Comparable Filtering
*For any* comparable sales search, all returned comparables should have the same property_type as the subject property (residential with residential, commercial with commercial).
**Validates: Requirements 12.3**

### Property 41: Property Type Adjustment Factors
*For any* valuation adjustment calculation, the adjustment factors used should be appropriate for the property type (residential factors for residential properties, commercial factors for commercial properties).
**Validates: Requirements 12.4**

### Property 42: Property Type Report Terminology
*For any* generated report, the metrics and terminology should match the property type (e.g., commercial reports include cap rate and NOI, residential reports include price per bedroom).
**Validates: Requirements 12.5**

### Property 43: Manual Entry Fallback
*For any* property field where all automated data sources fail, the system should prompt for manual entry and accept user-provided values.
**Validates: Requirements 13.2**

### Property 44: Manual Entry Field Marking
*For any* field populated by manual user entry, the report should clearly mark or tag that field as "user-provided" or "manually entered".
**Validates: Requirements 13.3**

### Property 45: Critical Data Missing Notification
*For any* analysis session where critical required fields are missing and cannot be provided, the system should notify the user with a list of which analysis components cannot be completed.
**Validates: Requirements 13.4**

### Property 46: Optional Data Graceful Degradation
*For any* analysis session where optional fields are missing, the system should proceed with analysis using available data and include a note in the report about limitations due to missing optional data.
**Validates: Requirements 13.5**

### Property 47: Session State Persistence
*For any* user session, navigating between pages or workflow steps should maintain all session state data without loss.
**Validates: Requirements 14.3**

### Property 48: Session Recovery After Browser Close
*For any* user session, closing the browser and returning within a reasonable time period (e.g., 24 hours) should restore the session state and allow the user to resume from where they left off.
**Validates: Requirements 14.4**

### Property 49: Multi-User Data Isolation
*For any* two concurrent user sessions, data from one user's session should never appear in or affect another user's session.
**Validates: Requirements 14.5**

### Property 50: API Failover and Logging
*For any* external data source API that becomes unavailable, the system should attempt alternative sources and log the failure with timestamp, API name, and error details for administrator review.
**Validates: Requirements 15.4**

### Property 51: Rate Limit Handling
*For any* external data source that returns a rate limit error, the system should queue the request for retry and notify the user of processing delays.
**Validates: Requirements 15.5**

## Error Handling

### Error Categories

**1. Data Retrieval Errors**
- API unavailable or timeout
- Invalid API response format
- Missing required fields in API response
- Rate limit exceeded

**Handling Strategy:**
- Attempt fallback data sources in priority order
- Cache successful responses to reduce API calls
- Log all failures for monitoring
- Prompt user for manual entry as last resort
- Display clear error messages indicating which data is unavailable

**2. Validation Errors**
- Invalid address format
- Out-of-range numeric values
- Insufficient comparables found
- Missing critical required fields

**Handling Strategy:**
- Validate inputs before processing
- Provide specific error messages with correction guidance
- Allow user to correct and retry
- For insufficient comparables, notify user and proceed with available data

**3. Calculation Errors**
- Division by zero in valuation formulas
- Missing data for required calculations
- Invalid adjustment factors

**Handling Strategy:**
- Check for zero denominators before division
- Use default values or skip calculations when data is missing
- Log calculation errors with context
- Display partial results with notes about missing calculations

**4. Session Errors**
- Session expired or not found
- Concurrent modification conflicts
- Database connection failures

**Handling Strategy:**
- Implement session timeout with warning before expiration
- Use optimistic locking for concurrent modifications
- Retry database operations with exponential backoff
- Provide session recovery mechanism

**5. Export Errors**
- Excel generation failure
- Google Sheets API authentication failure
- File size limits exceeded

**Handling Strategy:**
- Validate report data before export
- Provide clear authentication instructions for Google Sheets
- Implement chunking for large reports
- Offer alternative export formats if one fails

### Error Response Format

All API errors should follow consistent JSON structure:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {
      "field": "specific_field_name",
      "reason": "Detailed explanation"
    },
    "suggested_action": "What the user should do next"
  }
}
```

## Testing Strategy

### Dual Testing Approach

The testing strategy employs both unit testing and property-based testing as complementary approaches:

**Unit Tests** focus on:
- Specific examples demonstrating correct behavior
- Edge cases (empty data, boundary values, maximum search radius)
- Error conditions (API failures, invalid inputs, missing data)
- Integration points between components
- UI component rendering and user interactions

**Property-Based Tests** focus on:
- Universal properties that hold for all inputs
- Comprehensive input coverage through randomization
- Invariants that must be maintained across operations
- Mathematical correctness of formulas and calculations

Both testing approaches are necessary for comprehensive coverage. Unit tests catch concrete bugs in specific scenarios, while property tests verify general correctness across the input space.

### Property-Based Testing Configuration

**Library Selection:** Use Hypothesis for Python backend testing

**Test Configuration:**
- Minimum 100 iterations per property test (due to randomization)
- Each property test must reference its design document property
- Tag format: **Feature: real-estate-analysis-platform, Property {number}: {property_text}**
- Each correctness property must be implemented by a SINGLE property-based test

**Example Property Test Structure:**
```python
from hypothesis import given, strategies as st
import pytest

@given(
    address=st.text(min_size=10, max_size=100),
    property_type=st.sampled_from(['SINGLE_FAMILY', 'MULTI_FAMILY', 'COMMERCIAL'])
)
@pytest.mark.property_test
def test_property_data_retrieval_completeness(address, property_type):
    """
    Feature: real-estate-analysis-platform
    Property 1: Property Data Retrieval Completeness
    
    For any valid property address, when property facts are retrieved,
    the returned PropertyFacts object should contain all required fields
    with valid data types.
    """
    # Test implementation
    service = PropertyDataService()
    facts = service.fetch_property_facts(address)
    
    # Verify all required fields present
    assert facts.property_type is not None
    assert facts.units > 0
    assert facts.bedrooms >= 0
    assert facts.bathrooms >= 0
    assert facts.square_footage > 0
    # ... verify all required fields
```

### Unit Testing Strategy

**Component-Level Tests:**
- Test each service class independently with mocked dependencies
- Verify correct API calls and response handling
- Test error handling and fallback logic
- Validate data transformations

**Integration Tests:**
- Test workflow controller orchestration
- Verify data flow between components
- Test database persistence and retrieval
- Validate session state management

**API Endpoint Tests:**
- Test all REST endpoints with valid and invalid inputs
- Verify authentication and authorization
- Test rate limiting and error responses
- Validate response formats

**Frontend Tests:**
- Test React component rendering
- Verify user interaction handling
- Test form validation
- Validate state management

### Test Data Strategy

**Mock Data:**
- Create realistic property data fixtures
- Generate comparable sales datasets with known characteristics
- Mock external API responses for consistent testing

**Test Database:**
- Use separate test database with seed data
- Reset database state between test runs
- Include edge cases in seed data (sparse areas, unusual properties)

### Continuous Integration

- Run all tests on every commit
- Require passing tests before merge
- Generate code coverage reports (target: 80%+ coverage)
- Run property tests with extended iterations nightly (1000+ iterations)
