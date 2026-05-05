# Requirements Document

## Introduction

The Commercial Condo Filter feature identifies which commercial target properties are likely whole-building acquisition opportunities versus condoized or fragmented ownership structures. This prevents users from wasting mailers on properties they cannot realistically purchase as a single building. The system groups commercial properties by building-level normalized address, analyzes ownership and PIN patterns, detects condo indicators, and applies deterministic classification rules to produce actionable risk statuses.

## Glossary

- **Condo_Filter_Service**: The backend service responsible for grouping properties, detecting condo indicators, applying classification rules, and persisting analysis results.
- **Address_Normalizer**: The helper component that strips unit/suite/apartment identifiers from a property address to produce a building-level normalized address.
- **Unit_Detector**: The helper component that identifies unit, apartment, or suite markers in a property address string.
- **Condo_Language_Detector**: The helper component that identifies condo-related terminology in property_type or assessor_class fields.
- **Classification_Engine**: The helper component that applies deterministic rules to an address group's metrics to produce condo_risk_status and building_sale_possible values.
- **Address_Group_Analysis**: The database table storing per-building analysis results including metrics, classification, and manual override data.
- **Condo_Review_UI**: The frontend page that displays analysis results, provides filtering, detail inspection, manual override controls, and CSV export.
- **Normalized_Address**: A building-level address with unit/suite/apartment identifiers removed, used as the grouping key.
- **PIN**: The county assessor parcel identification number (county_assessor_pin field on a Lead record).
- **Condo_Risk_Status**: An enumerated classification value: likely_not_condo, likely_condo, partial_condo_possible, needs_review, or unknown.
- **Building_Sale_Possible**: An enumerated assessment value: yes, no, maybe, or unknown.
- **Unit_Marker**: A substring pattern in an address indicating a unit designation (e.g., "unit", "apt", "apartment", "suite", "ste", "#", or alphanumeric unit suffixes like "1a", "2b", "3r").
- **Condo_Language**: Terminology in property_type or assessor_class fields indicating condominium ownership (e.g., "condo", "condominium", "commercial condo", "condo unit", "unit").
- **Address_Group**: A collection of Lead records that share the same Normalized_Address.
- **Manual_Override**: A user action that replaces the automated classification for an Address_Group with a manually chosen status and reason.

## Requirements

### Requirement 1: Address Normalization

**User Story:** As a real estate investor, I want properties grouped by building-level address, so that I can see all records associated with a single physical building regardless of unit designations.

#### Acceptance Criteria

1. WHEN the Condo_Filter_Service receives a property address, THE Address_Normalizer SHALL strip unit markers (unit, apt, apartment, suite, ste, #) and their associated values from the address to produce a Normalized_Address.
2. WHEN the Condo_Filter_Service receives an address containing alphanumeric unit suffixes (e.g., "1a", "2b", "3n", "1s", "2f", "3r"), THE Address_Normalizer SHALL strip the unit suffix to produce a Normalized_Address.
3. THE Address_Normalizer SHALL convert the address to a consistent case and whitespace format during normalization.
4. WHEN the Condo_Filter_Service receives an address with no unit markers, THE Address_Normalizer SHALL return the address unchanged except for case and whitespace normalization.
5. FOR ALL valid address strings, normalizing then normalizing again SHALL produce an equivalent Normalized_Address (idempotence property).

### Requirement 2: Property Grouping

**User Story:** As a real estate investor, I want commercial properties grouped by their building-level address, so that I can analyze ownership patterns at the building level.

#### Acceptance Criteria

1. WHEN the Condo_Filter_Service runs analysis, THE Condo_Filter_Service SHALL query all Lead records where lead_category is "commercial" or property_type contains "mixed".
2. WHEN the Condo_Filter_Service has queried commercial and mixed-use properties, THE Condo_Filter_Service SHALL group the results by Normalized_Address.
3. THE Condo_Filter_Service SHALL compute the following metrics for each Address_Group: property_count (number of Lead records), pin_count (number of unique non-null county_assessor_pin values), owner_count (number of unique non-null owner name combinations), missing_pin_count (number of Lead records with null county_assessor_pin), and missing_owner_count (number of Lead records with null owner names).

### Requirement 3: Unit Marker Detection

**User Story:** As a real estate investor, I want the system to detect unit indicators in addresses, so that condoized properties are flagged automatically.

#### Acceptance Criteria

1. WHEN the Unit_Detector receives an address string, THE Unit_Detector SHALL return true if the address contains any of the following patterns (case-insensitive): "unit", "apt", "apartment", "suite", "ste", or "#" followed by a value.
2. WHEN the Unit_Detector receives an address string ending with an alphanumeric unit suffix pattern (e.g., "1a", "2b", "3n", "1s", "2f", "3r"), THE Unit_Detector SHALL return true.
3. WHEN the Unit_Detector receives an address string containing no unit marker patterns, THE Unit_Detector SHALL return false.
4. THE Condo_Filter_Service SHALL set has_unit_number to true on the Address_Group_Analysis record if any Lead in the Address_Group has a detected unit marker.

### Requirement 4: Condo Language Detection

**User Story:** As a real estate investor, I want the system to detect condo-related terminology in property type and assessor class fields, so that properties explicitly classified as condos are identified.

#### Acceptance Criteria

1. WHEN the Condo_Language_Detector receives property_type and assessor_class values, THE Condo_Language_Detector SHALL return true if either field contains any of the following terms (case-insensitive): "condo", "condominium", "commercial condo", "condo unit", or "unit".
2. WHEN the Condo_Language_Detector receives property_type and assessor_class values containing none of the condo language terms, THE Condo_Language_Detector SHALL return false.
3. THE Condo_Filter_Service SHALL set has_condo_language to true on the Address_Group_Analysis record if any Lead in the Address_Group has detected condo language in property_type or assessor_class.

### Requirement 5: Deterministic Classification

**User Story:** As a real estate investor, I want each building classified using clear deterministic rules, so that I can trust and inspect the reasoning behind each classification.

#### Acceptance Criteria

1. WHEN an Address_Group has has_unit_number equal to true, THE Classification_Engine SHALL assign condo_risk_status = "likely_condo" and building_sale_possible = "no".
2. WHEN an Address_Group has has_condo_language equal to true, THE Classification_Engine SHALL assign condo_risk_status = "likely_condo" and building_sale_possible = "no".
3. WHEN an Address_Group has pin_count >= 4 and owner_count >= 2, THE Classification_Engine SHALL assign condo_risk_status = "likely_condo" and building_sale_possible = "no".
4. WHEN an Address_Group has pin_count = 1, owner_count = 1, has_unit_number = false, and has_condo_language = false, THE Classification_Engine SHALL assign condo_risk_status = "likely_not_condo" and building_sale_possible = "yes".
5. WHEN an Address_Group has pin_count >= 2, owner_count = 1, and has_unit_number = false, THE Classification_Engine SHALL assign condo_risk_status = "partial_condo_possible" and building_sale_possible = "maybe".
6. WHEN an Address_Group has pin_count >= 2, owner_count > 1, has_unit_number = false, has_condo_language = false, and does not meet the criteria for likely_condo, THE Classification_Engine SHALL assign condo_risk_status = "needs_review" and building_sale_possible = "unknown".
7. WHEN an Address_Group has missing_pin_count > 0 or missing_owner_count > 0, THE Classification_Engine SHALL assign condo_risk_status = "needs_review" and building_sale_possible = "unknown".
8. WHEN an Address_Group does not match any other classification rule, THE Classification_Engine SHALL assign condo_risk_status = "needs_review" and building_sale_possible = "unknown" as the default fallback.
9. THE Classification_Engine SHALL evaluate rules in priority order (rules 1-3 before rule 4, rule 4 before rules 5-6, rules 5-6 before rules 7-8) and apply the first matching rule.
10. THE Classification_Engine SHALL return the triggered rule identifiers, a human-readable reason string, and a confidence indicator alongside the classification result.
11. FOR ALL Address_Groups with identical metrics, THE Classification_Engine SHALL produce identical classification results (determinism property).

### Requirement 6: Analysis Persistence

**User Story:** As a real estate investor, I want analysis results saved to the database, so that I can review them later without re-running the analysis.

#### Acceptance Criteria

1. WHEN the Condo_Filter_Service completes classification for an Address_Group, THE Condo_Filter_Service SHALL upsert a record into the Address_Group_Analysis table with all computed metrics, classification results, and an analysis_details JSON field containing triggered rules, reason, and confidence.
2. WHEN the Condo_Filter_Service completes classification for an Address_Group, THE Condo_Filter_Service SHALL update the condo_risk_status, building_sale_possible, and condo_analysis_id fields on all Lead records in that Address_Group.
3. THE Condo_Filter_Service SHALL set the analyzed_at timestamp on the Address_Group_Analysis record to the current UTC time upon completion.
4. WHEN an Address_Group_Analysis record already exists for a Normalized_Address, THE Condo_Filter_Service SHALL update the existing record rather than creating a duplicate.
5. THE Condo_Filter_Service SHALL preserve any existing manual_override_status and manual_override_reason when re-running automated analysis on a previously overridden Address_Group.

### Requirement 7: Database Schema

**User Story:** As a developer, I want a well-defined database schema, so that analysis data is stored consistently and can be queried efficiently.

#### Acceptance Criteria

1. THE Address_Group_Analysis table SHALL contain the following columns: id (integer primary key), normalized_address (string, unique, indexed), source_type (string), property_count (integer), pin_count (integer), owner_count (integer), has_unit_number (boolean), has_condo_language (boolean), missing_pin_count (integer), missing_owner_count (integer), condo_risk_status (string), building_sale_possible (string), analysis_details (JSON), manually_reviewed (boolean, default false), manual_override_status (string, nullable), manual_override_reason (text, nullable), analyzed_at (datetime), created_at (datetime), and updated_at (datetime).
2. THE Lead table SHALL be extended with three new columns: condo_risk_status (string, nullable), building_sale_possible (string, nullable), and condo_analysis_id (integer foreign key referencing Address_Group_Analysis.id, nullable).
3. THE Address_Group_Analysis table SHALL have an index on the normalized_address column for efficient lookups.
4. THE Address_Group_Analysis table SHALL have an index on the condo_risk_status column for efficient filtering.

### Requirement 8: Analysis API Endpoint

**User Story:** As a user, I want an API endpoint to trigger the condo analysis, so that I can run the analysis on demand and receive summary results.

#### Acceptance Criteria

1. WHEN the user sends a POST request to the analysis endpoint, THE Condo_Filter_Service SHALL query commercial and mixed-use properties, group by Normalized_Address, compute metrics, apply classification rules, upsert Address_Group_Analysis records, and update linked Lead records.
2. WHEN the analysis completes, THE analysis endpoint SHALL return a JSON response containing summary counts grouped by condo_risk_status and building_sale_possible values, total address groups analyzed, and total properties processed.
3. IF the analysis encounters a database error during processing, THEN THE analysis endpoint SHALL return an appropriate error response with a descriptive message and not leave partial results in an inconsistent state.
4. WHEN the user sends a GET request to the analysis results endpoint with filter parameters (condo_risk_status, building_sale_possible, manually_reviewed), THE analysis endpoint SHALL return paginated Address_Group_Analysis records matching the filters.
5. WHEN the user sends a GET request for a specific Address_Group_Analysis record, THE analysis endpoint SHALL return the full record including all linked Lead records with their original addresses, PINs, owners, property types, and assessor classes.

### Requirement 9: Manual Override

**User Story:** As a real estate investor, I want to manually override the automated classification for specific buildings, so that I can correct misclassifications based on my local knowledge.

#### Acceptance Criteria

1. WHEN the user submits a manual override for an Address_Group_Analysis record, THE Condo_Filter_Service SHALL update the manual_override_status, manual_override_reason, and set manually_reviewed to true on the Address_Group_Analysis record.
2. WHEN the user submits a manual override, THE Condo_Filter_Service SHALL update the condo_risk_status and building_sale_possible fields on all linked Lead records to match the override values.
3. WHEN the user submits a manual override, THE Condo_Filter_Service SHALL preserve the original automated analysis_details JSON field unchanged.
4. WHEN the Condo_Filter_Service re-runs automated analysis on a manually overridden Address_Group, THE Condo_Filter_Service SHALL update the automated analysis_details but SHALL NOT overwrite the manual_override_status or manual_override_reason fields.

### Requirement 10: Review UI - Results Table

**User Story:** As a real estate investor, I want a review page showing all analyzed buildings in a filterable table, so that I can quickly identify which properties need attention.

#### Acceptance Criteria

1. THE Condo_Review_UI SHALL display a results table with the following columns: normalized_address, condo_risk_status, building_sale_possible, confidence, property_count, pin_count, owner_count, has_unit_number, has_condo_language, missing_pin_count, missing_owner_count, reason, analyzed_at, and manually_reviewed.
2. THE Condo_Review_UI SHALL provide filter controls for condo_risk_status, building_sale_possible, and manually_reviewed fields.
3. THE Condo_Review_UI SHALL provide a "Run Analysis" button that triggers the analysis API endpoint and refreshes the results table upon completion.
4. WHEN the user applies filters, THE Condo_Review_UI SHALL update the results table to show only matching Address_Group_Analysis records.
5. THE Condo_Review_UI SHALL support pagination for the results table.

### Requirement 11: Review UI - Detail View

**User Story:** As a real estate investor, I want to drill into a specific building to see all associated properties and analysis details, so that I can make informed override decisions.

#### Acceptance Criteria

1. WHEN the user selects an Address_Group from the results table, THE Condo_Review_UI SHALL display a detail view showing all Lead records in the Address_Group with their original addresses, PINs, owners, property types, and assessor classes.
2. THE Condo_Review_UI detail view SHALL display the full analysis_details JSON including triggered rules, reason, and confidence.
3. THE Condo_Review_UI detail view SHALL provide manual override controls allowing the user to set condo_risk_status, building_sale_possible, and manual_override_reason.
4. WHEN the user submits a manual override from the detail view, THE Condo_Review_UI SHALL call the override API endpoint and refresh the detail view to reflect the updated status.

### Requirement 12: CSV Export

**User Story:** As a real estate investor, I want to export analysis results to CSV, so that I can use the data in external tools and mailing workflows.

#### Acceptance Criteria

1. WHEN the user clicks the CSV export button, THE Condo_Review_UI SHALL generate a CSV file containing the following columns: normalized_address, representative_property_address, pin_count, owner_count, condo_risk_status, building_sale_possible, owner_names, mailing_addresses, property_ids, pins, reason, and confidence.
2. THE CSV export SHALL respect any active filters applied in the results table.
3. WHEN the CSV export contains Address_Groups with multiple Lead records, THE CSV export SHALL concatenate multiple owner names, mailing addresses, property IDs, and PINs into delimited values within their respective columns.
4. THE Condo_Review_UI SHALL trigger a browser file download when the CSV export completes.

### Requirement 13: Data Safety

**User Story:** As a real estate investor, I want assurance that the condo filter analysis does not delete or suppress any property data, so that I retain full access to all imported records.

#### Acceptance Criteria

1. THE Condo_Filter_Service SHALL NOT delete any Lead records during analysis.
2. THE Condo_Filter_Service SHALL NOT modify any existing Lead fields other than condo_risk_status, building_sale_possible, and condo_analysis_id during analysis.
3. THE Condo_Filter_Service SHALL NOT suppress or hide Lead records from other system views based on condo classification results.

### Requirement 14: Address Normalization Round-Trip

**User Story:** As a developer, I want confidence that address normalization is consistent and reversible for inspection, so that grouping logic is reliable.

#### Acceptance Criteria

1. FOR ALL valid address strings, THE Address_Normalizer SHALL produce a Normalized_Address that, when normalized again, produces the same result (idempotence round-trip property).
2. FOR ALL Address_Groups, THE Condo_Filter_Service SHALL store the original un-normalized addresses on the linked Lead records, preserving the ability to inspect the source data.
