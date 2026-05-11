# Requirements Document

## Introduction

This feature replaces the Cook County Socrata API-based comparable sales search (Step 2 of the 6-step analysis workflow) with a Gemini AI-powered comparable search. The `GeminiComparableSearchService` sends confirmed property facts to the Gemini API and receives a structured JSON response containing both a list of comparable sales and a full narrative analysis. The comparable sales are stored as `ComparableSale` database records (same schema as today), and the narrative is stored in `session.step_results['COMPARABLE_SEARCH']['narrative']` for display in a new UI panel. The existing Celery task infrastructure, workflow step ordering, and Cook County Socrata cache tables are all preserved.

## Glossary

- **Gemini_Service**: The `GeminiComparableSearchService` class responsible for calling the Gemini API and parsing its response.
- **Comparable_Search_Task**: The `run_comparable_search_task` Celery task that orchestrates Step 2 of the analysis workflow.
- **Analysis_Session**: The `AnalysisSession` SQLAlchemy model that tracks workflow state, including `step_results` (JSON) and `loading` (Boolean).
- **ComparableSale**: The existing SQLAlchemy model representing a single comparable property sale, with fields including `similarity_notes` (Text).
- **Narrative**: The full AI-generated analysis text returned by Gemini (Sections A–F for residential, full commercial analysis for commercial), stored in `session.step_results['COMPARABLE_SEARCH']['narrative']`.
- **Similarity_Notes**: Per-comparable narrative text returned by Gemini and stored in `ComparableSale.similarity_notes`.
- **Property_Type**: The `PropertyType` enum with values `SINGLE_FAMILY`, `MULTI_FAMILY`, and `COMMERCIAL`.
- **Residential_Prompt**: The Gemini prompt used for `SINGLE_FAMILY` and `MULTI_FAMILY` property types.
- **Commercial_Prompt**: The Gemini prompt used for `COMMERCIAL` property types.
- **ComparableReviewTable**: The existing React component that renders the comparable sales table in Step 3.
- **GeminiNarrativePanel**: The new React component that displays the full Gemini narrative below the comparable review table in Step 3.
- **Workflow_Controller**: The `WorkflowController` class that orchestrates the 6-step analysis workflow.
- **Socrata_Cache**: The Cook County Socrata local cache tables and sync endpoint (`/api/cache/socrata/sync`), preserved for the multifamily underwriting proforma feature.
- **GOOGLE_AI_API_KEY**: The environment variable holding the Gemini API key, required at application and worker startup.

## Requirements

### Requirement 1: Gemini API Service

**User Story:** As a developer, I want a dedicated service that calls the Gemini API with property facts, so that the comparable search logic is encapsulated and independently testable.

#### Acceptance Criteria

1. THE `Gemini_Service` SHALL expose a `search(property_facts: dict, property_type: PropertyType) -> dict` method that calls the Gemini API and returns a dict with keys `"comparables"` (list) and `"narrative"` (string).
2. WHEN `property_type` is `SINGLE_FAMILY` or `MULTI_FAMILY`, THE `Gemini_Service` SHALL use the Residential_Prompt template.
3. WHEN `property_type` is `COMMERCIAL`, THE `Gemini_Service` SHALL use the Commercial_Prompt template.
4. WHEN the Gemini API returns a valid JSON response, THE `Gemini_Service` SHALL parse the `"comparables"` array and `"narrative"` string from the response body.
5. IF the Gemini API response body is not valid JSON, THEN THE `Gemini_Service` SHALL raise a descriptive exception identifying the parse failure.
6. IF the Gemini API response JSON is missing the `"comparables"` key or the `"narrative"` key, THEN THE `Gemini_Service` SHALL raise a descriptive exception identifying the missing field.
7. THE `Gemini_Service` SHALL read the Gemini API key from the `GOOGLE_AI_API_KEY` environment variable.
8. IF `GOOGLE_AI_API_KEY` is not set or is empty, THEN THE `Gemini_Service` SHALL raise a descriptive exception at instantiation time.

---

### Requirement 2: Comparable Search Task Update

**User Story:** As a developer, I want the Celery comparable search task to use the Gemini service instead of the Socrata-based finder, so that Step 2 of the analysis workflow produces AI-generated comparables.

#### Acceptance Criteria

1. WHEN `Comparable_Search_Task` executes for a session, THE `Comparable_Search_Task` SHALL call `Gemini_Service.search()` with the session's confirmed property facts and property type, replacing the previous `ComparableSalesFinder.find_comparables()` call.
2. WHEN `Gemini_Service.search()` returns successfully, THE `Comparable_Search_Task` SHALL create one `ComparableSale` database record per entry in the `"comparables"` array, mapping all JSON fields to the corresponding model columns including `similarity_notes`.
3. WHEN `Gemini_Service.search()` returns successfully, THE `Comparable_Search_Task` SHALL store the `"narrative"` string in `session.step_results['COMPARABLE_SEARCH']['narrative']`.
4. WHEN `Comparable_Search_Task` completes successfully, THE `Comparable_Search_Task` SHALL set `session.loading` to `False`.
5. IF `Gemini_Service.search()` raises an exception, THEN THE `Comparable_Search_Task` SHALL set `session.loading` to `False` and store the error message in `session.step_results['COMPARABLE_SEARCH_ERROR']`. Error messages MAY also be stored in `session.step_results['COMPARABLE_SEARCH_ERROR']` for non-exception diagnostic purposes without indicating a Gemini service failure.
6. THE `Comparable_Search_Task` SHALL preserve all existing session state update logic (setting `session.current_step`, `session.completed_steps`, and `session.updated_at`) unchanged.

---

### Requirement 3: Comparable Sale Field Mapping

**User Story:** As a developer, I want every field in the Gemini JSON comparable object to map correctly to the `ComparableSale` model, so that downstream scoring and valuation steps receive complete data.

#### Acceptance Criteria

1. THE `Comparable_Search_Task` SHALL map the following fields from each Gemini comparable JSON object to the corresponding `ComparableSale` column: `address`, `sale_date` (parsed as `YYYY-MM-DD` to a Python `date`), `sale_price`, `property_type` (resolved to `PropertyType` enum), `units`, `bedrooms`, `bathrooms`, `square_footage`, `lot_size`, `year_built`, `construction_type` (resolved to `ConstructionType` enum), `interior_condition` (resolved to `InteriorCondition` enum), `distance_miles`, `latitude`, `longitude`, and `similarity_notes`.
2. WHEN a `property_type` value in the Gemini response does not match a known `PropertyType` enum value — including responses with zero units or vacant land indicators — THE `Comparable_Search_Task` SHALL default to `PropertyType.SINGLE_FAMILY`.
3. WHEN a `construction_type` value in the Gemini response does not match a known `ConstructionType` enum value, THE `Comparable_Search_Task` SHALL default to `ConstructionType.FRAME`.
4. WHEN an `interior_condition` value in the Gemini response does not match a known `InteriorCondition` enum value, THE `Comparable_Search_Task` SHALL default to `InteriorCondition.AVERAGE`.
5. WHEN a `sale_date` string in the Gemini response cannot be parsed as a valid ISO date, THE `Comparable_Search_Task` SHALL default to the current date.

---

### Requirement 4: Environment Configuration

**User Story:** As a developer, I want the `GOOGLE_AI_API_KEY` to be documented and validated at startup, so that misconfiguration is caught immediately rather than at runtime during a user's analysis.

#### Acceptance Criteria

1. THE `Application` SHALL include `GOOGLE_AI_API_KEY` as a documented variable in `backend/.env.example` with a placeholder value.
2. WHEN the Flask application starts via `create_app`, THE `Application` SHALL log a startup warning if `GOOGLE_AI_API_KEY` is not set or is empty.
3. WHEN the Celery worker starts, THE `Comparable_Search_Task` worker process SHALL fail at startup with a descriptive error message if `GOOGLE_AI_API_KEY` is not set or is empty.

---

### Requirement 5: Similarity Notes Column in ComparableReviewTable

**User Story:** As a real estate analyst, I want to see Gemini's per-comparable notes in the review table, so that I can understand why each comparable was selected before approving the set.

#### Acceptance Criteria

1. THE `ComparableReviewTable` SHALL render a "Similarity Notes" column as the last data column before the Actions column.
2. WHEN a comparable's `similarity_notes` value exceeds 100 characters, THE `ComparableReviewTable` SHALL display the first 100 characters followed by a "…more" affordance.
3. WHEN a user activates the "…more" affordance on a truncated `similarity_notes` cell, THE `ComparableReviewTable` SHALL display the full `similarity_notes` text.
4. WHEN a comparable's `similarity_notes` value is null or empty, THE `ComparableReviewTable` SHALL display an empty cell in the Similarity Notes column.
5. THE `ComparableReviewTable` SHALL pass `similarity_notes` through the existing `ComparableSale` TypeScript type without requiring changes to the `onComparablesChange` callback signature.

---

### Requirement 6: GeminiNarrativePanel Component

**User Story:** As a real estate analyst, I want to read Gemini's full narrative analysis alongside the comparable table, so that I have the AI's complete reasoning available when deciding which comparables to approve.

#### Acceptance Criteria

1. THE `GeminiNarrativePanel` SHALL render below the `ComparableReviewTable` in the Step 3 view when a narrative is available.
2. THE `GeminiNarrativePanel` SHALL read the narrative text from `session.step_results.COMPARABLE_SEARCH.narrative`.
3. WHEN `session.step_results.COMPARABLE_SEARCH.narrative` is null, undefined, or an empty string, THE `GeminiNarrativePanel` SHALL not render.
4. THE `GeminiNarrativePanel` SHALL render the narrative in a scrollable container with a maximum height of 400px.
5. THE `GeminiNarrativePanel` SHALL include a collapsible header labeled "AI Analysis" that allows the user to show or hide the narrative panel.
6. THE `GeminiNarrativePanel` SHALL default to the expanded (visible) state on every initial render, regardless of any previous user interaction in the same or prior sessions.
7. THE `GeminiNarrativePanel` SHALL preserve whitespace and line breaks present in the narrative text.

---

### Requirement 7: Step 2 Loading State Message

**User Story:** As a real estate analyst, I want the loading indicator during Step 2 to communicate that AI is searching for comparables, so that I understand why the step takes longer than a typical database query.

#### Acceptance Criteria

1. WHILE `session.loading` is `true` and `session.currentStep` is `2`, THE `Application` SHALL display the message "Searching for comparable sales with AI…" in place of a generic loading spinner or message.

---

### Requirement 8: Socrata Cache Preservation

**User Story:** As a developer, I want the Cook County Socrata cache infrastructure to remain intact after this change, so that the multifamily underwriting proforma feature continues to function without modification.

#### Acceptance Criteria

1. THE `Application` SHALL preserve the `POST /api/cache/socrata/sync` endpoint and its existing behavior after the Gemini comparable search is introduced.
2. THE `Application` SHALL preserve all Socrata cache database tables (`parcel_universe`, `parcel_sales`, `improvement_characteristics`) and their schemas.
3. THE `Application` SHALL preserve the `socrata_cache_refresh_task` Celery beat schedule and task implementation.
4. THE `Workflow_Controller` SHALL remove the `ComparableSalesFinder` dependency from the comparable search execution path while leaving all other workflow steps unchanged.
