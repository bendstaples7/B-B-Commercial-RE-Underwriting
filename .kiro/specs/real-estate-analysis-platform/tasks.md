# Implementation Plan: Real Estate Analysis Platform

## Overview

This implementation plan breaks down the real estate analysis platform into discrete coding tasks. The platform consists of a Python Flask backend with PostgreSQL database, a React TypeScript frontend, and integrations with external property data APIs. The implementation follows the 6-step workflow: property facts extraction, comparable sales search, user review, weighted scoring, valuation models, and report generation with optional scenario analysis.

## Tasks

- [x] 1. Set up project structure and development environment
  - Create backend directory structure (Flask app, models, services, controllers, tests)
  - Create frontend directory structure (React app, components, services, types)
  - Set up PostgreSQL database with initial schema
  - Configure Redis for caching and session management
  - Set up Python virtual environment with dependencies (Flask, SQLAlchemy, Celery, pytest, hypothesis)
  - Set up Node.js project with dependencies (React, TypeScript, Material-UI, React Query, Recharts)
  - Create .env files for configuration (API keys, database URLs)
  - _Requirements: 14.1, 14.2, 14.3, 15.1, 15.2, 15.3_

- [x] 2. Implement core data models and database schema
  - [x] 2.1 Create SQLAlchemy models for PropertyFacts, ComparableSale, AnalysisSession
    - Define PropertyFacts model with all 17+ fields and enums (PropertyType, ConstructionType, InteriorCondition)
    - Define ComparableSale model with sale data and similarity metrics
    - Define AnalysisSession model with workflow state tracking
    - Define RankedComparable, ValuationResult, and Scenario models
    - Add database indexes for performance (address lookups, session queries)
    - _Requirements: 1.1, 2.3, 11.4, 14.4_

  - [ ]* 2.2 Write property test for data model validation
    - **Property 1: Property Data Retrieval Completeness**
    - **Validates: Requirements 1.1**

  - [ ]* 2.3 Write unit tests for data models
    - Test model creation with valid data
    - Test field validation and constraints
    - Test enum value handling
    - _Requirements: 1.1, 2.3_

- [x] 3. Implement Property Data Service with fallback logic
  - [x] 3.1 Create PropertyDataService class with API integration adapters
    - Implement MLS API adapter for property and sales data
    - Implement tax assessor API adapter for property characteristics
    - Implement Chicago city data adapter for square footage fallback
    - Implement municipal data adapter for building permits and zoning
    - Add geocoding functionality using Google Maps API
    - Implement fallback sequence logic (primary → Chicago → tax assessor → municipal → manual)
    - Add Redis caching layer (24-hour cache for property facts, permanent for geocoding)
    - _Requirements: 1.1, 1.2, 13.1, 15.1, 15.2, 15.3_

  - [ ]* 3.2 Write property test for data source fallback sequence
    - **Property 2: Data Source Fallback Sequence**
    - **Validates: Requirements 1.2, 13.1**

  - [ ]* 3.3 Write property test for failed field manual entry
    - **Property 4: Failed Field Manual Entry**
    - **Validates: Requirements 1.5**

  - [ ]* 3.4 Write unit tests for PropertyDataService
    - Test successful API calls with mocked responses
    - Test API failure handling and fallback logic
    - Test caching behavior
    - Test geocoding with various address formats
    - _Requirements: 1.1, 1.2, 1.5, 13.1, 13.2_

- [x] 4. Implement Comparable Sales Finder with radius expansion
  - [x] 4.1 Create ComparableSalesFinder class
    - Implement find_comparables() with radius expansion algorithm (0.25 → 0.5 → 0.75 → 1.0 miles)
    - Implement property type filtering (residential vs commercial)
    - Implement sale date filtering (last 12 months)
    - Implement distance calculation using geocoded coordinates
    - Add validation for minimum 10 comparables requirement
    - _Requirements: 2.1, 2.2, 2.3, 12.3_

  - [ ]* 4.2 Write property test for comparable sales minimum count
    - **Property 5: Comparable Sales Minimum Count**
    - **Validates: Requirements 2.1**

  - [ ]* 4.3 Write property test for search radius expansion sequence
    - **Property 6: Search Radius Expansion Sequence**
    - **Validates: Requirements 2.2**

  - [ ]* 4.4 Write property test for comparable data completeness
    - **Property 7: Comparable Data Completeness**
    - **Validates: Requirements 2.3**

  - [ ]* 4.5 Write property test for property type comparable filtering
    - **Property 40: Property Type Comparable Filtering**
    - **Validates: Requirements 12.3**

  - [ ]* 4.6 Write unit tests for ComparableSalesFinder
    - Test radius expansion with various property locations
    - Test edge case: fewer than 10 comparables at max radius
    - Test property type filtering
    - Test sale date filtering
    - _Requirements: 2.1, 2.2, 2.5, 12.3_

- [x] 5. Implement Weighted Scoring Engine
  - [x] 5.1 Create WeightedScoringEngine class
    - Implement calculate_score() with 7 weighted criteria
    - Implement recency scoring (16% weight): 100 - (days_old / 365 × 100)
    - Implement proximity scoring (15% weight): 100 - (distance_miles / max_distance × 100)
    - Implement units scoring (15% weight): 100 - (|subject_units - comp_units| / max_units × 100)
    - Implement beds/baths scoring (15% weight): combined difference normalized
    - Implement square footage scoring (15% weight): percentage difference
    - Implement construction type scoring (12% weight): categorical match (100/50/0)
    - Implement interior condition scoring (12% weight): categorical match with gradations
    - Implement rank_comparables() to sort by total score descending
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 5.2 Write property test for weighted scoring formula correctness
    - **Property 11: Weighted Scoring Formula Correctness**
    - **Validates: Requirements 4.1-4.7**

  - [ ]* 5.3 Write property test for comparable ranking order
    - **Property 12: Comparable Ranking Order**
    - **Validates: Requirements 4.8**

  - [ ]* 5.4 Write unit tests for WeightedScoringEngine
    - Test each scoring component independently
    - Test total score calculation
    - Test ranking with tied scores
    - Test edge cases (identical properties, maximum differences)
    - _Requirements: 4.1-4.8_

- [x] 6. Checkpoint - Ensure core data services work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Valuation Engine with adjustment calculations
  - [x] 7.1 Create ValuationEngine class
    - Implement calculate_valuations() using top 5 ranked comparables
    - Implement calculate_price_per_sqft()
    - Implement calculate_price_per_unit()
    - Implement calculate_price_per_bedroom()
    - Implement calculate_adjusted_value() with adjustment factors
    - Define adjustment factors dictionary (units: $15k, bedrooms: $5k, bathrooms: $3k, sqft: $50, construction: $10k, interior conditions, basement: $8k, parking: $5k)
    - Implement compute_arv_range() calculating 25th, 50th, 75th percentiles
    - Generate narrative summaries for each comparable valuation
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [ ]* 7.2 Write property test for top comparables selection
    - **Property 13: Top Comparables Selection**
    - **Validates: Requirements 5.1**

  - [ ]* 7.3 Write property test for valuation methods completeness
    - **Property 14: Valuation Methods Completeness**
    - **Validates: Requirements 5.2**

  - [ ]* 7.4 Write property test for adjustment categories completeness
    - **Property 15: Adjustment Categories Completeness**
    - **Validates: Requirements 5.3**

  - [ ]* 7.5 Write property test for ARV range calculation
    - **Property 17: ARV Range Calculation**
    - **Validates: Requirements 5.6**

  - [ ]* 7.6 Write unit tests for ValuationEngine
    - Test each valuation method calculation
    - Test adjustment factor application
    - Test ARV percentile calculations
    - Test narrative generation
    - Test edge cases (no adjustments needed, extreme differences)
    - _Requirements: 5.1-5.6_

- [x] 8. Implement Scenario Analysis Engine
  - [x] 8.1 Create ScenarioAnalysisEngine class with wholesale analysis
    - Implement analyze_wholesale() calculating MAO, contract price, assignment fees
    - MAO formula: Conservative ARV × 0.70 - Estimated Repairs
    - Contract price formula: MAO × 0.95
    - Assignment fee range: Contract Price × 0.05 to 0.10
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 8.2 Write property tests for wholesale calculations
    - **Property 21: Wholesale MAO Calculation**
    - **Property 22: Wholesale Contract Price Calculation**
    - **Property 23: Wholesale Assignment Fee Calculation**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 8.3 Implement fix and flip analysis
    - Implement analyze_fix_and_flip() with complete cost breakdown
    - Calculate holding costs: (Acquisition + Renovation) × 0.02 × months
    - Calculate financing costs: (Acquisition + Renovation) × 0.75 × 0.11 × (months / 12)
    - Calculate closing costs: Likely ARV × 0.08
    - Calculate total cost and net profit
    - Calculate ROI: Net Profit / (Acquisition + Renovation) × 0.25
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 8.4 Write property tests for fix and flip calculations
    - **Property 24: Fix and Flip Interest Rate**
    - **Property 25: Fix and Flip LTC Ratio**
    - **Property 26: Fix and Flip Total Cost Calculation**
    - **Property 27: Fix and Flip Profit Calculation**
    - **Validates: Requirements 8.1-8.4**

  - [x] 8.5 Implement buy and hold analysis
    - Implement analyze_buy_and_hold() with dual capital structures
    - Create capital structure 1: 5% down, 6.5% interest, 360 months (owner-occupied)
    - Create capital structure 2: 25% down, 7.5% interest, 360 months (investor)
    - Fetch market rent data from comparable rentals
    - Generate price points table (low, medium, high purchase prices)
    - Calculate monthly payment using PMT formula
    - Calculate monthly cash flow: Rent - Payment - Expenses
    - Calculate cash-on-cash return: (Cash Flow × 12) / Down Payment
    - Calculate cap rate: (Rent × 12 - Expenses × 12) / Purchase Price
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 8.6 Write property tests for buy and hold calculations
    - **Property 28: Buy and Hold Capital Structures**
    - **Property 29: Buy and Hold Market Rent Retrieval**
    - **Property 30: Buy and Hold Price Points**
    - **Property 31: Buy and Hold Metrics Completeness**
    - **Validates: Requirements 9.1-9.4**

  - [x] 8.7 Implement scenario comparison
    - Implement compare_scenarios() generating summary table
    - Calculate ROI for each scenario and price point
    - Highlight highest ROI strategy per price point
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 8.8 Write property tests for scenario comparison
    - **Property 32: Scenario Comparison Completeness**
    - **Property 33: Scenario ROI Calculation**
    - **Property 34: Highest ROI Highlighting**
    - **Validates: Requirements 10.1-10.4**

  - [ ]* 8.9 Write unit tests for ScenarioAnalysisEngine
    - Test wholesale scenario with various ARV values
    - Test fix and flip with different renovation budgets
    - Test buy and hold with different price points
    - Test scenario comparison logic
    - _Requirements: 7.1-10.4_

- [x] 9. Implement Report Generator with export functionality
  - [x] 9.1 Create ReportGenerator class
    - Implement generate_report() orchestrating all sections
    - Implement format_section_a() for subject property facts table
    - Implement format_section_b() for comparable sales table
    - Implement format_section_c() for weighted ranking table
    - Implement format_section_d() for valuation models with narratives
    - Implement format_section_e() for ARV range display
    - Implement format_section_f() for key drivers bullet points
    - Add optional scenario analysis sections
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 10.5_

  - [x] 9.2 Implement Excel export functionality
    - Implement export_to_excel() using openpyxl library
    - Create formatted Excel workbook with multiple sheets
    - Apply styling (headers, borders, number formats)
    - _Requirements: 6.7_

  - [x] 9.3 Implement Google Sheets export functionality
    - Implement export_to_google_sheets() using Google Sheets API
    - Handle OAuth authentication flow
    - Create new spreadsheet and populate with report data
    - Return shareable URL
    - _Requirements: 6.8_

  - [ ]* 9.4 Write property tests for report generation
    - **Property 18: Report Structure Completeness**
    - **Property 19: Excel Export Validity**
    - **Property 20: Google Sheets Export Validity**
    - **Validates: Requirements 6.1-6.8**

  - [ ]* 9.5 Write unit tests for ReportGenerator
    - Test each section formatting independently
    - Test Excel file generation and structure
    - Test Google Sheets API integration with mocked credentials
    - Test report with and without scenario analysis
    - _Requirements: 6.1-6.8_

- [x] 10. Checkpoint - Ensure all backend services are complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement Workflow Controller for orchestration
  - [x] 11.1 Create WorkflowController class
    - Implement start_analysis() initializing new session
    - Implement get_session_state() retrieving current workflow state
    - Implement advance_to_step() with validation gates
    - Implement update_step_data() handling user modifications
    - Implement go_back_to_step() for backward navigation
    - Add session state persistence to PostgreSQL
    - Implement recalculation cascade when earlier steps are modified
    - _Requirements: 1.4, 3.4, 11.1, 11.2, 11.3, 11.4, 11.5, 14.3, 14.4_

  - [ ]* 11.2 Write property tests for workflow controller
    - **Property 3: Workflow Gate Enforcement**
    - **Property 36: Data Validation on Modification**
    - **Property 37: Downstream Recalculation Cascade**
    - **Property 38: State Preservation During Navigation**
    - **Property 47: Session State Persistence**
    - **Property 48: Session Recovery After Browser Close**
    - **Validates: Requirements 1.4, 3.4, 11.1-11.5, 14.3, 14.4**

  - [ ]* 11.3 Write unit tests for WorkflowController
    - Test session initialization
    - Test step advancement with and without approval
    - Test backward navigation
    - Test data modification and recalculation
    - Test session persistence and recovery
    - _Requirements: 1.4, 3.4, 11.1-11.5, 14.3, 14.4_

- [x] 12. Implement Flask REST API endpoints
  - [x] 12.1 Create API routes for workflow operations
    - POST /api/analysis/start - Start new analysis with address
    - GET /api/analysis/{session_id} - Get session state
    - POST /api/analysis/{session_id}/step/{step_number} - Advance to step
    - PUT /api/analysis/{session_id}/step/{step_number} - Update step data
    - POST /api/analysis/{session_id}/back/{step_number} - Go back to step
    - GET /api/analysis/{session_id}/report - Generate report
    - GET /api/analysis/{session_id}/export/excel - Export to Excel
    - POST /api/analysis/{session_id}/export/sheets - Export to Google Sheets
    - Add request validation using marshmallow schemas
    - Add error handling middleware
    - Add rate limiting using Flask-Limiter
    - _Requirements: 1.1-15.5_

  - [ ]* 12.2 Write property test for multi-user data isolation
    - **Property 49: Multi-User Data Isolation**
    - **Validates: Requirements 14.5**

  - [ ]* 12.3 Write integration tests for API endpoints
    - Test complete workflow from start to report generation
    - Test error responses for invalid inputs
    - Test authentication and authorization
    - Test rate limiting behavior
    - Test concurrent user sessions
    - _Requirements: All requirements_

- [x] 13. Implement error handling and logging
  - [x] 13.1 Create error handling infrastructure
    - Define custom exception classes for each error category
    - Implement error response formatter with consistent JSON structure
    - Add Flask error handlers for all exception types
    - Implement API failover logic with logging
    - Implement rate limit handling with request queuing
    - Add comprehensive logging (API calls, errors, user actions)
    - _Requirements: 1.5, 13.1-13.5, 15.4, 15.5_

  - [ ]* 13.2 Write property tests for error handling
    - **Property 43: Manual Entry Fallback**
    - **Property 44: Manual Entry Field Marking**
    - **Property 45: Critical Data Missing Notification**
    - **Property 46: Optional Data Graceful Degradation**
    - **Property 50: API Failover and Logging**
    - **Property 51: Rate Limit Handling**
    - **Validates: Requirements 1.5, 13.1-13.5, 15.4, 15.5**

  - [ ]* 13.3 Write unit tests for error handling
    - Test each error category handling
    - Test error response format
    - Test logging output
    - Test failover sequences
    - _Requirements: 1.5, 13.1-13.5, 15.4, 15.5_

- [x] 14. Implement React frontend - Core components
  - [x] 14.1 Create TypeScript types and interfaces
    - Define PropertyFacts, ComparableSale, AnalysisSession types
    - Define WorkflowStep enum and state types
    - Define API request/response types
    - _Requirements: 14.1, 14.2_

  - [x] 14.2 Create API service layer
    - Implement AnalysisService class with all API calls
    - Configure React Query for state management and caching
    - Add error handling and retry logic
    - _Requirements: 14.1, 14.2, 14.3_

  - [x] 14.3 Create WorkflowStepper component
    - Display 6-step progress indicator
    - Highlight current step
    - Allow navigation to completed steps
    - _Requirements: 11.4, 14.2_

  - [x] 14.4 Create Step 1: PropertyFactsForm component
    - Input field for property address
    - Display retrieved property facts in editable table
    - Interior condition classification dropdown
    - User confirmation button
    - Handle missing data with manual entry fields
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 11.1, 11.2, 13.2_

  - [ ]* 14.5 Write unit tests for PropertyFactsForm
    - Test form rendering
    - Test address input and submission
    - Test property facts display
    - Test manual entry for missing fields
    - Test confirmation flow
    - _Requirements: 1.1-1.5_

- [x] 15. Implement React frontend - Comparables and Review
  - [x] 15.1 Create Step 2: ComparableSalesDisplay component
    - Display subject property as first row
    - Display comparable sales in table format (14 columns)
    - Show search radius and comparable count
    - Display notification if fewer than 10 comparables found
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 15.2 Create Step 3: ComparableReviewTable component
    - Display all comparables in editable table
    - Add remove button for each comparable
    - Add "Add Comparable" button with manual entry form
    - Validate minimum 10 comparables before approval
    - User approval button
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 15.3 Write unit tests for comparable components
    - Test ComparableSalesDisplay rendering
    - Test ComparableReviewTable interactions
    - Test comparable removal and addition
    - Test validation logic
    - _Requirements: 2.1-3.5_

- [x] 16. Implement React frontend - Scoring and Valuation
  - [x] 16.1 Create Step 4: WeightedScoringTable component
    - Display ranked comparables table
    - Show score breakdown by criteria (7 columns)
    - Show total score and rank
    - Highlight top 5 comparables
    - _Requirements: 4.1-4.8_

  - [x] 16.2 Create Step 5: ValuationModelsDisplay component
    - Display valuation table for top 5 comparables
    - Show 4 valuation methods per comparable
    - Display narrative summaries
    - Display ARV range (conservative, likely, aggressive)
    - Display key drivers section
    - _Requirements: 5.1-5.6_

  - [ ]* 16.3 Write unit tests for scoring and valuation components
    - Test WeightedScoringTable rendering
    - Test ValuationModelsDisplay rendering
    - Test data formatting and display
    - _Requirements: 4.1-5.6_

- [x] 17. Implement React frontend - Report and Scenarios
  - [x] 17.1 Create Step 6: ReportDisplay component
    - Display all 6 report sections (A-F)
    - Add "Export to Excel" button
    - Add "Export to Google Sheets" button
    - Handle export downloads and links
    - _Requirements: 6.1-6.8_

  - [x] 17.2 Create ScenarioAnalysisPanel component
    - Add scenario selection checkboxes (wholesale, fix & flip, buy & hold)
    - Create WholesaleScenarioForm with inputs and results display
    - Create FixFlipScenarioForm with renovation budget input and results
    - Create BuyHoldScenarioForm with rent input and dual capital structure results
    - Display scenario comparison table when multiple scenarios selected
    - Highlight highest ROI strategies
    - _Requirements: 7.1-10.5_

  - [ ]* 17.3 Write unit tests for report and scenario components
    - Test ReportDisplay rendering
    - Test export button functionality
    - Test scenario forms and calculations display
    - Test scenario comparison table
    - _Requirements: 6.1-10.5_

- [x] 18. Implement responsive design and accessibility
  - [x] 18.1 Apply Material-UI responsive breakpoints
    - Configure theme with breakpoints for desktop, tablet, mobile
    - Apply responsive layouts to all components
    - Test on multiple screen sizes
    - _Requirements: 14.2_

  - [x] 18.2 Add accessibility features
    - Add ARIA labels to all interactive elements
    - Ensure keyboard navigation works throughout
    - Add focus indicators
    - Test with screen reader
    - _Requirements: 14.1, 14.2_

  - [ ]* 18.3 Write accessibility tests
    - Test keyboard navigation
    - Test ARIA labels presence
    - Test color contrast ratios
    - _Requirements: 14.1, 14.2_

- [x] 19. Implement property type support (residential vs commercial)
  - [x] 19.1 Add property type branching logic
    - Update ValuationEngine to select residential vs commercial methods
    - Implement commercial income capitalization approach
    - Update adjustment factors based on property type
    - Update ReportGenerator to use property-type-specific terminology
    - _Requirements: 12.1, 12.2, 12.4, 12.5_

  - [ ]* 19.2 Write property tests for property type handling
    - **Property 39: Property Type Method Selection**
    - **Property 41: Property Type Adjustment Factors**
    - **Property 42: Property Type Report Terminology**
    - **Validates: Requirements 12.1, 12.2, 12.4, 12.5**

  - [ ]* 19.3 Write unit tests for property type support
    - Test residential valuation methods
    - Test commercial valuation methods
    - Test property-specific adjustment factors
    - Test report terminology differences
    - _Requirements: 12.1-12.5_

- [x] 20. Final integration and end-to-end testing
  - [x] 20.1 Set up end-to-end test environment
    - Configure test database with seed data
    - Set up mock external APIs
    - Configure frontend test environment
    - _Requirements: All requirements_

  - [x]* 20.2 Write end-to-end integration tests
    - Test complete workflow: address input → report generation
    - Test workflow with user modifications at each step
    - Test backward navigation and recalculation
    - Test scenario analysis workflows
    - Test export functionality
    - Test error scenarios (API failures, invalid data)
    - Test session persistence and recovery
    - _Requirements: All requirements_

- [-] 21. Final checkpoint - Complete system validation
  - Ensure all tests pass (unit, property, integration, e2e)
  - Verify all 51 correctness properties are tested
  - Verify all 15 requirements are covered
  - Ask the user if questions arise or if ready for deployment.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate universal correctness properties with 100+ iterations
- Unit tests validate specific examples, edge cases, and error conditions
- The implementation follows a bottom-up approach: data layer → services → API → frontend
- Checkpoints ensure incremental validation at major milestones
- All 51 correctness properties from the design document are mapped to property-based tests
- The dual testing approach (unit + property tests) ensures comprehensive coverage
