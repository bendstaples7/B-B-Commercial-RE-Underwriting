# Requirements Document

## Introduction

This document specifies the requirements for a web-based real estate valuation and analysis platform that automates property analysis through a comprehensive 6-step workflow. The system extracts property facts, identifies comparable sales, performs weighted scoring, generates valuation models, and produces formatted reports with optional scenario analysis for wholesale, fix & flip, and buy & hold strategies.

## Glossary

- **System**: The real estate analysis web application
- **User**: A real estate investor, analyst, or professional using the platform
- **Subject_Property**: The property being analyzed and valued
- **Comparable_Sale**: A recently sold property similar to the Subject_Property
- **ARV**: After Repair Value - estimated market value after improvements
- **MAO**: Maximum Allowable Offer - highest price for wholesale deals
- **LTC**: Loan to Cost - percentage of total project cost financed
- **Property_Data_Source**: External APIs or databases providing property information
- **Valuation_Model**: Mathematical model calculating property value using comparable sales
- **Scenario_Analysis**: Financial modeling comparing different investment strategies

## Requirements

### Requirement 1: Subject Property Facts Extraction

**User Story:** As a user, I want to input a property address and receive comprehensive property details, so that I can verify the subject property information before analysis.

#### Acceptance Criteria

1. WHEN a user provides a property address, THE System SHALL retrieve property type, unit count, bedrooms, bathrooms, square footage, lot size, year built, construction type, basement status, parking details, last sale price, last sale date, assessed value, property taxes, and zoning information
2. WHEN square footage data is unavailable from primary sources, THE System SHALL attempt retrieval from Chicago city data, then tax assessor records, then other municipal databases in sequence
3. WHEN property data is retrieved, THE System SHALL present an interior condition classification interface with options: needs a gut, poor, average, new renovation, high end
4. WHEN all property facts are displayed, THE System SHALL require user confirmation before proceeding to the next step
5. IF property data retrieval fails for any field, THEN THE System SHALL mark the field as unavailable and allow user manual entry

### Requirement 2: Comparable Sales Search

**User Story:** As a user, I want the system to automatically find recent comparable sales, so that I can base my valuation on relevant market data.

#### Acceptance Criteria

1. WHEN searching for comparable sales, THE System SHALL find a minimum of 10 comparable properties sold within the last 12 months
2. WHEN insufficient comparables are found at 0.25 mile radius, THE System SHALL expand the search radius to 0.5 miles, then 0.75 miles, then 1.0 mile until 10 or more comparables are found
3. WHEN comparables are found, THE System SHALL retrieve address, sale date, sale price, property type, unit count, bedrooms, bathrooms, square footage, lot size, year built, construction type, interior condition, and distance from subject property for each comparable
4. WHEN displaying comparable sales, THE System SHALL present the Subject_Property as the first row followed by comparable properties in subsequent rows
5. WHEN the maximum search radius of 1.0 mile is reached and fewer than 10 comparables exist, THE System SHALL present all available comparables and notify the user of the limited dataset

### Requirement 3: User Review and Approval

**User Story:** As a user, I want to review and approve comparable sales before valuation, so that I can ensure data quality and relevance.

#### Acceptance Criteria

1. WHEN comparable sales are displayed, THE System SHALL present them in a table format with all retrieved property details
2. WHEN the user reviews comparables, THE System SHALL provide the ability to remove individual comparables from the analysis
3. WHEN the user reviews comparables, THE System SHALL provide the ability to manually add additional comparables with custom data entry
4. WHEN the user completes review, THE System SHALL require explicit approval before proceeding to weighted scoring
5. WHEN the user modifies comparable data, THE System SHALL validate that at least 10 comparables remain before allowing approval

### Requirement 4: Weighted Scoring and Ranking

**User Story:** As a user, I want comparables ranked by similarity to my subject property, so that I can prioritize the most relevant sales data.

#### Acceptance Criteria

1. WHEN calculating comparable scores, THE System SHALL apply a 16% weight to recency (sale date proximity to current date)
2. WHEN calculating comparable scores, THE System SHALL apply a 15% weight to proximity (distance from subject property)
3. WHEN calculating comparable scores, THE System SHALL apply a 15% weight to unit count match
4. WHEN calculating comparable scores, THE System SHALL apply a 15% weight to bedroom and bathroom count match
5. WHEN calculating comparable scores, THE System SHALL apply a 15% weight to square footage similarity
6. WHEN calculating comparable scores, THE System SHALL apply a 12% weight to exterior construction type similarity
7. WHEN calculating comparable scores, THE System SHALL apply a 12% weight to interior renovation quality similarity
8. WHEN scoring is complete, THE System SHALL produce a ranked table of comparables ordered by total weighted score from highest to lowest

### Requirement 5: Valuation Models Using Top Comparables

**User Story:** As a user, I want detailed valuation models based on the best comparables, so that I can determine a reliable property value range.

#### Acceptance Criteria

1. WHEN generating valuation models, THE System SHALL use only the top 5 ranked comparables
2. WHEN calculating valuations, THE System SHALL compute price per square foot, price per unit, price per bedroom, and adjusted valuation for each of the top 5 comparables
3. WHEN calculating adjusted valuations, THE System SHALL apply adjustments for differences in unit count, bedrooms, bathrooms, square footage, exterior construction type, interior condition, and major value items
4. WHEN presenting valuation models, THE System SHALL generate a narrative summary for each comparable property explaining the adjustments
5. WHEN presenting valuation models, THE System SHALL display a valuation table showing all calculated metrics for each comparable
6. WHEN computing final ARV range, THE System SHALL calculate conservative ARV as the bottom quartile value, likely ARV as the median value, and aggressive ARV as the top quartile value across all valuation methods

### Requirement 6: Standardized Report Output

**User Story:** As a user, I want a comprehensive formatted report, so that I can review all analysis components in a structured document.

#### Acceptance Criteria

1. WHEN generating the report, THE System SHALL include Section A containing Subject Property Facts in table format
2. WHEN generating the report, THE System SHALL include Section B containing all Comparable Sales in table format
3. WHEN generating the report, THE System SHALL include Section C containing Weighted Ranking scores in table format
4. WHEN generating the report, THE System SHALL include Section D containing Valuation Models with narrative summaries and valuation table
5. WHEN generating the report, THE System SHALL include Section E containing Final ARV Range with conservative, likely, and aggressive values
6. WHEN generating the report, THE System SHALL include Section F containing Key Drivers explaining the primary factors influencing valuation
7. WHEN the report is complete, THE System SHALL provide export functionality to Excel format
8. WHEN the report is complete, THE System SHALL provide export functionality to Google Sheets format

### Requirement 7: Scenario Analysis - Wholesale Strategy

**User Story:** As a user, I want to analyze wholesale investment scenarios, so that I can determine maximum allowable offer and potential assignment fees.

#### Acceptance Criteria

1. WHEN the user selects wholesale scenario analysis, THE System SHALL calculate Maximum Allowable Offer (MAO) based on conservative ARV
2. WHEN calculating wholesale scenarios, THE System SHALL compute contract price recommendations
3. WHEN calculating wholesale scenarios, THE System SHALL estimate assignment fee potential
4. WHEN wholesale analysis is complete, THE System SHALL present results in a summary table showing MAO, contract price, and assignment fee

### Requirement 8: Scenario Analysis - Fix and Flip Strategy

**User Story:** As a user, I want to analyze fix and flip investment scenarios, so that I can evaluate renovation project profitability.

#### Acceptance Criteria

1. WHEN the user selects fix and flip scenario analysis, THE System SHALL model financing with 11% interest-only loan terms
2. WHEN calculating fix and flip scenarios, THE System SHALL apply 75% Loan to Cost (LTC) ratio
3. WHEN calculating fix and flip scenarios, THE System SHALL compute total project cost including acquisition, renovation, holding costs, and financing costs
4. WHEN calculating fix and flip scenarios, THE System SHALL calculate profit based on likely ARV minus total project cost
5. WHEN fix and flip analysis is complete, THE System SHALL present results showing acquisition price, renovation budget, total cost, exit value, and net profit

### Requirement 9: Scenario Analysis - Buy and Hold Strategy

**User Story:** As a user, I want to analyze buy and hold investment scenarios with different capital structures, so that I can evaluate long-term rental income potential.

#### Acceptance Criteria

1. WHEN the user selects buy and hold scenario analysis, THE System SHALL model two capital structures: 5% down payment owner-occupied and 25% down payment investor financing
2. WHEN calculating buy and hold scenarios, THE System SHALL retrieve market rent data for comparable properties
3. WHEN calculating buy and hold scenarios, THE System SHALL generate price versus cash flow tables showing multiple purchase price points
4. WHEN calculating buy and hold scenarios, THE System SHALL compute monthly cash flow, cash-on-cash return, and cap rate for each price point and capital structure
5. WHEN buy and hold analysis is complete, THE System SHALL present results comparing both capital structures across low, medium, and high purchase price scenarios

### Requirement 10: Scenario Comparison and Summary

**User Story:** As a user, I want to compare all investment scenarios side by side, so that I can determine the optimal investment strategy.

#### Acceptance Criteria

1. WHEN all selected scenarios are analyzed, THE System SHALL generate a scenario summary table comparing wholesale, fix and flip, and buy and hold strategies
2. WHEN generating scenario comparison, THE System SHALL display results for low, medium, and high offer price points
3. WHEN generating scenario comparison, THE System SHALL calculate return on investment (ROI) for each strategy and price point
4. WHEN generating scenario comparison, THE System SHALL highlight the highest ROI strategy for each price point
5. WHEN scenario analysis is complete, THE System SHALL include the scenario summary in the exportable report

### Requirement 11: Interactive Workflow and User Modifications

**User Story:** As a user, I want to make updates and changes during the analysis process, so that I can refine data and assumptions in real-time.

#### Acceptance Criteria

1. WHEN the user is at any workflow step, THE System SHALL provide the ability to edit displayed data fields
2. WHEN the user modifies data, THE System SHALL validate the changes against data type and range constraints
3. WHEN the user modifies data in an earlier step, THE System SHALL recalculate all dependent downstream results
4. WHEN the user requests to return to a previous step, THE System SHALL preserve all user modifications and allow re-execution from that step
5. WHEN data modifications affect valuation results, THE System SHALL update the ARV range and scenario analyses automatically

### Requirement 12: Property Type Support

**User Story:** As a user, I want to analyze both commercial and residential properties, so that I can use the platform for diverse real estate investments.

#### Acceptance Criteria

1. WHEN a property is identified as residential, THE System SHALL apply residential-specific valuation methods and comparable search criteria
2. WHEN a property is identified as commercial, THE System SHALL apply commercial-specific valuation methods including income capitalization approach
3. WHEN searching for comparables, THE System SHALL filter by property type to ensure residential properties are compared to residential and commercial to commercial
4. WHEN calculating valuation adjustments, THE System SHALL use property-type-appropriate adjustment factors
5. WHEN generating reports, THE System SHALL include property-type-specific metrics and terminology

### Requirement 13: Missing Data Handling

**User Story:** As a user, I want the system to handle missing data gracefully, so that I can complete analysis even with incomplete information.

#### Acceptance Criteria

1. WHEN property data is unavailable from primary sources, THE System SHALL attempt retrieval from fallback data sources in priority order
2. WHEN data cannot be retrieved from any source, THE System SHALL prompt the user for manual entry
3. WHEN the user provides manual data entry, THE System SHALL mark the field as user-provided in the report
4. WHEN critical data fields are missing and cannot be provided, THE System SHALL notify the user which analysis components cannot be completed
5. WHEN optional data fields are missing, THE System SHALL proceed with analysis using available data and note limitations in the report

### Requirement 14: Web-Based Interface Accessibility

**User Story:** As a user, I want to access the platform through a web browser, so that I can perform analysis from any device without software installation.

#### Acceptance Criteria

1. THE System SHALL be accessible through modern web browsers including Chrome, Firefox, Safari, and Edge
2. WHEN a user accesses the platform, THE System SHALL present a responsive interface that adapts to desktop, tablet, and mobile screen sizes
3. WHEN a user navigates the workflow, THE System SHALL maintain session state across page interactions
4. WHEN a user closes the browser during analysis, THE System SHALL preserve work in progress and allow resumption upon return
5. WHEN multiple users access the platform simultaneously, THE System SHALL maintain data isolation between user sessions

### Requirement 15: Data Source Integration

**User Story:** As a system administrator, I want the platform to integrate with property data sources, so that users receive accurate and current property information.

#### Acceptance Criteria

1. THE System SHALL integrate with MLS (Multiple Listing Service) APIs for property and sales data
2. THE System SHALL integrate with county tax assessor databases for property characteristics and assessed values
3. THE System SHALL integrate with municipal data sources for building permits and zoning information
4. WHEN a data source API is unavailable, THE System SHALL attempt alternative sources and log the failure for administrator review
5. WHEN data source rate limits are reached, THE System SHALL queue requests and notify the user of processing delays
