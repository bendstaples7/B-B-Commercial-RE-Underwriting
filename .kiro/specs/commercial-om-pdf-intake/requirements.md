# Requirements Document

## Introduction

The Commercial OM PDF Intake feature allows investors to upload a broker-provided Offering Memorandum (OM) PDF for a commercial or multifamily property and use it to kick off a deal analysis. Brokers produce polished OMs that contain pro forma financials, unit mix tables, income/expense schedules, and financing assumptions — but their projections are often optimistic. This feature:

1. Parses the uploaded PDF to extract all structured financial data (asking price, unit mix, current rents, pro forma rents, income/expenses, NOI, cap rate, GRM, and financing terms).
2. Independently researches achievable market rents for the property's unit types and submarket using the platform's existing Gemini AI comparable search capability.
3. Presents the investor with three side-by-side scenarios: the broker's current-state numbers, the broker's pro forma, and a platform-derived "realistic" scenario built from independently researched market rents.
4. Pre-populates a multifamily Deal record with the extracted data so the investor can proceed directly into the full underwriting pro forma workflow without re-entering numbers.

The feature integrates with the existing `multifamily-underwriting-proforma` Deal model and the `gemini-comparable-search` Gemini AI service. PDF parsing uses PyMuPDF or pdfplumber. The Gemini API (already integrated) is leveraged for intelligent field extraction from unstructured PDF text.

## Glossary

- **OM_PDF**: A broker-provided Offering Memorandum PDF file uploaded by the user for a commercial or multifamily property.
- **OM_Intake_Job**: The top-level record tracking the lifecycle of a single OM PDF upload, from file receipt through parsing, market research, and Deal creation.
- **PDF_Parser**: The backend service responsible for extracting raw text and structured tables from an uploaded OM_PDF using PyMuPDF or pdfplumber.
- **OM_Extractor**: The backend service that sends raw PDF text to the Gemini API and receives a structured JSON object containing all extracted OM fields.
- **Extracted_OM_Data**: The structured data object produced by the OM_Extractor, containing all fields parsed from the OM_PDF (see Requirement 2 for the full field list).
- **Broker_Current**: The set of financial metrics reflecting the property's current in-place performance as reported by the broker in the OM (current rents, current NOI, current cap rate, current GRM).
- **Broker_Pro_Forma**: The set of financial metrics reflecting the broker's projected stabilized performance (pro forma rents, pro forma NOI, pro forma cap rate, pro forma GRM).
- **Realistic_Scenario**: The platform-derived scenario built from independently researched market rents, replacing the broker's pro forma rent assumptions while reusing the broker's expense structure.
- **Market_Rent_Research**: The process of querying the Gemini AI service with the property's location, unit types, and unit sizes to obtain independently sourced comparable rent estimates.
- **Unit_Mix_Row**: A single row in the OM's unit mix table, representing one unit type with its count, size, current average rent, and pro forma rent.
- **Intake_Status**: The lifecycle state of an OM_Intake_Job: `PENDING`, `PARSING`, `EXTRACTING`, `RESEARCHING`, `REVIEW`, `CONFIRMED`, `FAILED`.
- **Confidence_Score**: A 0.0–1.0 value assigned by the OM_Extractor to each extracted field, indicating how reliably the field was identified in the PDF text.
- **Deal**: The multifamily underwriting Deal record defined in the `multifamily-underwriting-proforma` spec. An OM_Intake_Job that reaches `CONFIRMED` status creates or links to a Deal.
- **Intake_Review_UI**: The frontend page where the user reviews extracted OM data, sees the three-scenario comparison, and confirms or corrects fields before Deal creation.
- **GRM**: Gross Rent Multiplier — Purchase_Price divided by Annual_Gross_Rent.
- **NOI**: Net Operating Income — Effective_Gross_Income minus Operating_Expenses.
- **Cap_Rate**: NOI divided by Purchase_Price, expressed as a decimal.
- **DSCR**: Debt Service Coverage Ratio — NOI divided by annual Debt_Service.
- **Vacancy_Rate**: The fractional vacancy/collection loss assumption applied to Gross_Potential_Income to derive Effective_Gross_Income.
- **GOOGLE_AI_API_KEY**: The environment variable holding the Gemini API key, already used by the `gemini-comparable-search` feature.

## Requirements

### Requirement 1: OM PDF Upload

**User Story:** As an investor, I want to upload a broker OM PDF from the platform UI, so that the system can begin extracting deal data without me manually entering numbers.

#### Acceptance Criteria

1. WHEN a user submits a multipart POST request with a PDF file attachment to the OM intake endpoint, THE OM_Intake_Service SHALL create an OM_Intake_Job record with status `PENDING` and return the `intake_job_id` and a presigned upload URL within 3 seconds.
2. IF the uploaded file's MIME type is not `application/pdf`, THEN THE OM_Intake_Service SHALL reject the request with an HTTP 422 validation error whose body identifies the unsupported file type.
3. IF the uploaded file exceeds 50 MB, THEN THE OM_Intake_Service SHALL reject the request with an HTTP 422 validation error whose body identifies the file size limit.
4. IF an internal error prevents job record creation, THEN THE OM_Intake_Service SHALL return an HTTP 500 error and SHALL NOT persist a partial OM_Intake_Job record.
5. WHEN a file is accepted, THE OM_Intake_Service SHALL store the raw PDF bytes associated with the OM_Intake_Job until the job reaches a terminal status of `CONFIRMED` or `FAILED`.
6. WHEN an OM_Intake_Job is created, THE OM_Intake_Service SHALL record the uploading user's identity and a `created_at` timestamp on the job record.
7. WHEN a user requests the status of an OM_Intake_Job by `intake_job_id`, THE OM_Intake_Service SHALL return the current `Intake_Status` (one of `PENDING`, `PARSING`, `EXTRACTING`, `RESEARCHING`, `REVIEW`, `CONFIRMED`, `FAILED`), `created_at`, `updated_at`, and any `error_message` if the job is in `FAILED` status.
8. IF a user requests an OM_Intake_Job by `intake_job_id` and that job either does not exist or belongs to a different user, THEN THE OM_Intake_Service SHALL return an HTTP 404 response to avoid leaking job existence.

---

### Requirement 2: PDF Text Extraction

**User Story:** As a developer, I want the platform to extract raw text and table content from the uploaded PDF, so that the AI extraction step has clean input to work with.

#### Acceptance Criteria

1. WHEN an OM_Intake_Job transitions to `PARSING` status, THE PDF_Parser SHALL extract all text content from every page of the OM_PDF and store it as a single UTF-8 string associated with the job.
2. WHEN the OM_PDF contains tabular content (such as a unit mix table or income/expense schedule), THE PDF_Parser SHALL attempt to extract table rows as structured data (rows and columns) and store them alongside the raw text.
3. IF the PDF_Parser cannot open or decode the uploaded file, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status and store an error message identifying the file as unreadable or corrupt.
4. IF the extracted text from the OM_PDF contains fewer than 100 characters, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status with an error message indicating the PDF appears to contain no extractable text (e.g., a scanned image-only PDF).
5. WHEN PDF text extraction completes successfully, THE OM_Intake_Service SHALL transition the OM_Intake_Job to `EXTRACTING` status and enqueue the AI extraction step.
6. THE PDF_Parser SHALL complete text extraction within 30 seconds for a PDF of up to 50 pages; for PDFs between 51 and 300 pages, the limit is 30 seconds per 50-page block.
7. IF table extraction fails but raw text extraction succeeds, THEN THE OM_Intake_Service SHALL preserve the raw text, store a warning noting that table extraction failed, and continue to `EXTRACTING` status rather than transitioning to `FAILED`.

---

### Requirement 3: AI-Powered Field Extraction

**User Story:** As an investor, I want the platform to automatically identify and extract all key financial fields from the OM text, so that I don't have to manually transcribe numbers from the PDF.

#### Acceptance Criteria

1. WHEN an OM_Intake_Job is in `EXTRACTING` status, THE OM_Extractor SHALL send the extracted PDF text to the Gemini API with a structured prompt requesting a JSON object containing all Extracted_OM_Data fields.
2. WHEN the Gemini API returns a valid response, THE OM_Extractor SHALL parse and store the following fields as Extracted_OM_Data on the OM_Intake_Job:
   - **Property fields**: `property_address`, `property_city`, `property_state`, `property_zip`, `neighborhood`, `asking_price`, `price_per_unit`, `price_per_sqft`, `building_sqft`, `year_built`, `lot_size`, `zoning`, `unit_count`
   - **Broker_Current metrics**: `current_noi`, `current_cap_rate`, `current_grm`, `current_gross_potential_income`, `current_effective_gross_income`, `current_vacancy_rate`, `current_gross_expenses`
   - **Broker_Pro_Forma metrics**: `proforma_noi`, `proforma_cap_rate`, `proforma_grm`, `proforma_gross_potential_income`, `proforma_effective_gross_income`, `proforma_vacancy_rate`, `proforma_gross_expenses`
   - **Unit_Mix_Rows**: an array where each row contains `unit_type_label`, `unit_count`, `sqft`, `current_avg_rent`, `proforma_rent`
   - **Income line items**: `apartment_income_current`, `apartment_income_proforma`, `other_income_items` (array of `{label, annual_amount}`)
   - **Expense line items**: `expense_items` (array of `{label, current_annual_amount, proforma_annual_amount}`)
   - **Financing fields**: `down_payment_pct`, `loan_amount`, `interest_rate`, `amortization_years`, `debt_service_annual`, `current_dscr`, `proforma_dscr`, `current_cash_on_cash`, `proforma_cash_on_cash`
   - **Broker/listing fields**: `listing_broker_name`, `listing_broker_company`, `listing_broker_phone`, `listing_broker_email`
3. THE OM_Extractor SHALL assign a Confidence_Score between 0.0 and 1.0 to each extracted field, where 1.0 indicates the field was found verbatim in the PDF text and lower values indicate inference or ambiguity.
4. IF a field is not found in the PDF text, THE OM_Extractor SHALL set that field's value to `null` and its Confidence_Score to 0.0 rather than omitting the field from the response.
5. IF the Gemini API returns a network error, timeout, non-2xx HTTP response, or a response body that is not valid JSON, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status with an error message identifying the failure type.
6. IF the Gemini API returns valid JSON where the `unit_mix` key is absent, not an array, or contains array items missing required sub-fields (`unit_type_label`, `unit_count`, `sqft`, `current_avg_rent`, `proforma_rent`), OR where the `asking_price` field is absent, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status with an error message identifying the missing or malformed fields.
7. WHEN AI field extraction completes successfully, THE OM_Intake_Service SHALL transition the OM_Intake_Job to `RESEARCHING` status and enqueue the market rent research step.
8. THE OM_Extractor SHALL complete the Gemini API call and response parsing within 60 seconds.
9. IF `GOOGLE_AI_API_KEY` is not set or is empty, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status with a descriptive configuration error message.
10. IF the extracted PDF text passed to the Gemini API is empty or null, THEN THE OM_Intake_Service SHALL transition the OM_Intake_Job to `FAILED` status with an error message indicating no text was available for extraction, without making a Gemini API call.

---

### Requirement 4: Independent Market Rent Research

**User Story:** As an investor, I want the platform to independently research what rents are actually achievable in the market, so that I can evaluate the broker's pro forma against realistic rent assumptions.

#### Acceptance Criteria

1. WHEN an OM_Intake_Job is in `RESEARCHING` status, THE OM_Intake_Service SHALL invoke the Gemini AI comparable search capability once per distinct unit type present in the extracted Unit_Mix_Rows, passing the property's `property_city`, `property_state`, `neighborhood`, `unit_type_label`, and `sqft` as search parameters.
2. WHEN the market rent research call returns for a unit type, THE OM_Intake_Service SHALL store the researched `market_rent_estimate`, `market_rent_low`, and `market_rent_high` range values for that unit type on the OM_Intake_Job.
3. WHEN market rent research returns results for all unit types, THE OM_Intake_Service SHALL compute the `Realistic_Scenario` by substituting the `market_rent_estimate` for each unit type in place of the broker's `proforma_rent`, while retaining the broker's `proforma_gross_expenses` and `proforma_vacancy_rate` from the Extracted_OM_Data.
4. WHEN computing the Realistic_Scenario, THE OM_Intake_Service SHALL calculate `realistic_gross_potential_income` as the sum of (`market_rent_estimate` × `unit_count`) across all Unit_Mix_Rows, multiplied by 12.
5. WHEN computing the Realistic_Scenario, THE OM_Intake_Service SHALL calculate `realistic_effective_gross_income` as `realistic_gross_potential_income` × (1 − `proforma_vacancy_rate`) + sum of annual `other_income_items`.
6. WHEN computing the Realistic_Scenario, THE OM_Intake_Service SHALL calculate `realistic_noi` as `realistic_effective_gross_income` − `proforma_gross_expenses`.
7. WHEN computing the Realistic_Scenario and `asking_price` is greater than zero, THE OM_Intake_Service SHALL calculate `realistic_cap_rate` as `realistic_noi` ÷ `asking_price`, expressed as a decimal; IF `asking_price` is zero or null, THEN `realistic_cap_rate` SHALL be set to `null`.
8. WHEN computing the Realistic_Scenario and `realistic_gross_potential_income` is greater than zero, THE OM_Intake_Service SHALL calculate `realistic_grm` as `asking_price` ÷ `realistic_gross_potential_income`; IF `realistic_gross_potential_income` is zero or null, THEN `realistic_grm` SHALL be set to `null`.
9. IF market rent research fails for a unit type due to a network error, timeout of 30 seconds or more, or a response containing no parseable rent estimate, THE OM_Intake_Service SHALL store a `market_research_warning` identifying the affected unit type(s), set `market_rent_estimate` to `null` for those types, and transition to `REVIEW` status after all unit types have been attempted.
10. WHEN all market rent research and Realistic_Scenario computation completes, THE OM_Intake_Service SHALL transition the OM_Intake_Job to `REVIEW` status.
11. IF any `market_rent_estimate` used in Realistic_Scenario computation is `null`, THE OM_Intake_Service SHALL set `realistic_gross_potential_income`, `realistic_effective_gross_income`, `realistic_noi`, `realistic_cap_rate`, and `realistic_grm` to `null` and include a `partial_realistic_scenario_warning` on the OM_Intake_Job.

---

### Requirement 5: Three-Scenario Comparison

**User Story:** As an investor, I want to see the broker's current numbers, the broker's pro forma, and the platform's realistic scenario side by side, so that I can immediately understand the gap between broker claims and achievable performance.

#### Acceptance Criteria

1. WHEN a user requests the scenario comparison for an OM_Intake_Job in `REVIEW` or `CONFIRMED` status, THE OM_Intake_Service SHALL return a `ScenarioComparison` object containing three scenarios: `broker_current`, `broker_proforma`, and `realistic`.
2. THE `ScenarioComparison` SHALL include the following metrics for each scenario: `gross_potential_income_annual`, `effective_gross_income_annual`, `gross_expenses_annual`, `noi_annual`, `cap_rate`, `grm`, and `monthly_rent_total` (sum of all unit rents per month).
3. IF financing data is available (loan_amount > 0 AND interest_rate > 0), THEN THE `ScenarioComparison` SHALL also include `dscr` and `cash_on_cash` for each scenario; otherwise those fields SHALL be `null`.
4. WHEN the `realistic` scenario's `noi_annual` differs from the `broker_proforma` `noi_annual` by more than 10% (computed as `|realistic_noi - proforma_noi| / |proforma_noi|`), THE OM_Intake_Service SHALL include a `significant_variance_flag` set to `true` on the `ScenarioComparison`.
5. IF `broker_proforma` `noi_annual` is zero or null, THEN THE OM_Intake_Service SHALL set `significant_variance_flag` to `null` rather than dividing by zero.
6. WHEN the `realistic` scenario's `cap_rate` is lower than the `broker_proforma` `cap_rate`, THE OM_Intake_Service SHALL include a `realistic_cap_rate_below_proforma` flag set to `true` on the `ScenarioComparison`.
7. THE `ScenarioComparison` SHALL include a `unit_mix_comparison` array where each row contains the `unit_type_label`, `unit_count`, `sqft` (average per-unit square footage), `current_avg_rent` (from the `broker_current` scenario), `proforma_rent`, and `market_rent_estimate` (with `market_rent_low` and `market_rent_high`) for direct per-unit-type comparison.
8. IF the `asking_price` is zero or null, THEN THE OM_Intake_Service SHALL return `cap_rate` and `grm` as `null` for all scenarios rather than dividing by zero.
9. IF `gross_potential_income_annual` is zero or null for any scenario, THEN THE OM_Intake_Service SHALL return `grm` as `null` for that scenario rather than dividing by zero.

---

### Requirement 6: Intake Review UI

**User Story:** As an investor, I want a dedicated review page where I can inspect extracted data, correct any misread fields, and confirm the intake before a Deal is created, so that the resulting Deal starts with accurate data.

#### Acceptance Criteria

1. WHEN an OM_Intake_Job reaches `REVIEW` status, THE Frontend SHALL display the Intake_Review_UI showing the extracted property details, the three-scenario comparison table, and the unit mix comparison.
2. THE Intake_Review_UI SHALL display each extracted field alongside its Confidence_Score, marking fields with Confidence_Score below 0.7 with both a warning icon and an amber background so the user knows which fields to verify.
3. WHEN a user edits an extracted field value in the Intake_Review_UI, THE Frontend SHALL mark that field as `user_overridden` and recalculate the affected scenario metrics within 300 ms without a server round-trip.
4. WHEN a user edits a `current_avg_rent` or `proforma_rent` value for a unit type, THE Frontend SHALL recalculate `monthly_rent_total`, `gross_potential_income_annual`, `effective_gross_income_annual`, `noi_annual`, `cap_rate`, and `grm` for the affected scenario within 300 ms.
5. WHEN a user edits a `market_rent_estimate` value for a unit type, THE Frontend SHALL recalculate `realistic_gross_potential_income`, `realistic_effective_gross_income`, `realistic_noi`, `realistic_cap_rate`, and `realistic_grm` within 300 ms.
6. THE Intake_Review_UI SHALL display the OM_Intake_Job's `Intake_Status` at all times.
7. WHILE the OM_Intake_Job is in `PENDING`, `PARSING`, `EXTRACTING`, or `RESEARCHING` status, THE Frontend SHALL poll for status updates every 3 seconds.
8. WHILE the OM_Intake_Job is in `PARSING` status, THE Frontend SHALL display the message "Reading PDF…".
9. WHILE the OM_Intake_Job is in `EXTRACTING` status, THE Frontend SHALL display the message "Extracting deal data with AI…".
10. WHILE the OM_Intake_Job is in `RESEARCHING` status, THE Frontend SHALL display the message "Researching market rents…".
11. WHEN the OM_Intake_Job transitions to `REVIEW` status during polling, THE Frontend SHALL stop polling and render the full review content without requiring a page reload.
12. IF the OM_Intake_Job transitions to `FAILED` status, THE Frontend SHALL display the `error_message` and offer the user a "Try Again" button that creates a new OM_Intake_Job for the same file and navigates to the new job's review page.
13. WHEN a user clicks the "Confirm" button on the Intake_Review_UI, THE Frontend SHALL submit the confirmed field values (including any user overrides) to the OM intake confirmation endpoint and navigate to the created Deal's detail page upon success.

---

### Requirement 7: Deal Creation from Confirmed Intake

**User Story:** As an investor, I want to confirm the intake and have the platform automatically create a pre-populated multifamily Deal, so that I can proceed directly into full underwriting without re-entering data.

#### Acceptance Criteria

1. WHEN a user confirms an OM_Intake_Job in `REVIEW` status, THE OM_Intake_Service SHALL create a Deal record (as defined in the `multifamily-underwriting-proforma` spec) pre-populated with the confirmed Extracted_OM_Data fields and transition the OM_Intake_Job to `CONFIRMED` status.
2. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL map the following Extracted_OM_Data fields to Deal fields: `property_address`, `property_city`, `property_state`, `property_zip`, `unit_count`, `asking_price` → `purchase_price`, `year_built`, `building_sqft`.
3. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL create one Unit record per Unit_Mix_Row using `unit_type_label` as `unit_type`, `sqft` as `sqft`, `Beds` defaulting to 0, `Baths` defaulting to 0, and `Occupancy_Status` defaulting to `Occupied`; IF a Unit_Mix_Row has `unit_count` ≤ 0, THEN the OM_Intake_Service SHALL reject the confirmation with a validation error identifying the invalid row.
4. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL create Rent_Roll_Entry records for each unit using `current_avg_rent` as `current_rent`.
5. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL create Market_Rent_Assumption records for each unit type using `proforma_rent` as `post_reno_target_rent` and `market_rent_estimate` as `target_rent`; IF `market_rent_estimate` is absent or null, THEN `target_rent` SHALL be set to `null`.
6. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL populate the Deal's operating expense fields from the extracted `expense_items`, mapping recognized expense labels (Real Estate Taxes, Insurance, Gas, Electric, Water/Sewer, Trash, Maintenance, Management) to their corresponding Deal OpEx fields; unrecognized expense labels SHALL be stored on the Deal as `unmatched_expense_items` rather than silently dropped.
7. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL populate the Deal's `other_income_monthly` from the sum of `other_income_items` divided by 12.
8. WHEN creating the Deal from a confirmed intake, THE OM_Intake_Service SHALL store the extracted financing fields (`loan_amount`, `interest_rate`, `amortization_years`) on the Deal record as default lender assumptions for Scenario_B (Self_Funded_Reno); absent fields SHALL be stored as `null`.
9. WHEN the Deal is created successfully, THE OM_Intake_Service SHALL store the `deal_id` on the OM_Intake_Job and return it in the confirmation response.
10. WHEN the Deal is created successfully, THE Frontend SHALL navigate the user directly to the Deal detail page for the newly created Deal.
11. IF Deal creation fails due to a validation error, THEN THE OM_Intake_Service SHALL return the validation error to the user and the OM_Intake_Job SHALL remain in `REVIEW` status so the user can correct the field and retry confirmation.
12. THE OM_Intake_Service SHALL execute the entire Deal creation (Unit records, Rent_Roll_Entry records, Market_Rent_Assumption records, expense mapping, and OM_Intake_Job status update) as a single atomic database transaction that rolls back completely on any failure.

---

### Requirement 8: Intake Job Persistence and History

**User Story:** As an investor, I want to see a history of my past OM uploads, so that I can revisit extracted data and re-confirm intakes without re-uploading the PDF.

#### Acceptance Criteria

1. WHEN a user requests their OM intake history, THE OM_Intake_Service SHALL return a paginated list of OM_Intake_Jobs owned by the requesting user, ordered by `created_at` descending, with fields `intake_job_id`, `original_filename`, `property_address`, `asking_price`, `unit_count`, `Intake_Status`, `created_at`, and `deal_id` (if confirmed); the page size SHALL be between 1 and 100, defaulting to 25.
2. WHEN a user requests a previously completed OM_Intake_Job in `REVIEW` or `CONFIRMED` status, THE OM_Intake_Service SHALL return the full Extracted_OM_Data, ScenarioComparison, and any user overrides applied during the original review.
3. THE OM_Intake_Service SHALL retain OM_Intake_Job records and their associated Extracted_OM_Data for a minimum of 90 days after creation; after 90 days, records SHALL become inaccessible and requests for them SHALL return an error indicating the record has expired.
4. WHEN a user requests re-confirmation of an OM_Intake_Job already in `CONFIRMED` status, THE OM_Intake_Service SHALL reject the request with an error indicating the job is already confirmed and provide the existing `deal_id`.
5. IF a user requests a previously completed OM_Intake_Job that is in a status other than `REVIEW` or `CONFIRMED` (e.g., `FAILED`, `PARSING`), THEN THE OM_Intake_Service SHALL return the job's current status and `error_message` (if any) without returning Extracted_OM_Data or ScenarioComparison.

---

### Requirement 9: Error Handling and Resilience

**User Story:** As an investor, I want the system to handle PDF parsing failures and AI service errors gracefully, so that a bad PDF or a temporary API outage doesn't leave me with no recourse.

#### Acceptance Criteria

1. IF the Gemini API returns an HTTP 429 (rate limit) or 5xx error during field extraction or market rent research, THEN THE OM_Intake_Service SHALL retry the request up to 3 times with exponential backoff (2s, 4s, 8s) before transitioning the OM_Intake_Job to `FAILED` status.
2. WHEN the OM_Intake_Job transitions to `FAILED` status, THE OM_Intake_Service SHALL store the `Intake_Status` at the stage of failure and the `error_message` on the job record.
3. WHEN a user requests a retry of a `FAILED` OM_Intake_Job, THE OM_Intake_Service SHALL create a new OM_Intake_Job referencing the same stored PDF bytes and transition it to `PENDING` status; the original job SHALL remain in `FAILED` status.
4. IF the PDF text extraction step produces output but the AI extraction step fails, THEN THE OM_Intake_Service SHALL preserve the extracted raw text on the job record so that a retry does not need to re-parse the PDF.
5. WHEN any unhandled exception occurs during OM intake processing, THE OM_Intake_Service SHALL transition the job to `FAILED` status within 5 minutes of the exception occurring rather than leaving it in a non-terminal status indefinitely.

---

### Requirement 10: Data Validation and Consistency Checks

**User Story:** As an investor, I want the platform to flag inconsistencies in the extracted data, so that I can catch broker errors or extraction mistakes before they propagate into my Deal.

#### Acceptance Criteria

1. WHEN Extracted_OM_Data is stored, THE OM_Intake_Service SHALL validate that the sum of `unit_count` across all Unit_Mix_Rows equals the top-level `unit_count` field, and SHALL store a `unit_count_mismatch_warning` if they differ.
2. WHEN Extracted_OM_Data is stored, THE OM_Intake_Service SHALL validate that `current_noi` is approximately equal to `current_effective_gross_income` − `current_gross_expenses` (within 2% tolerance), and SHALL store a `noi_consistency_warning` if the values are inconsistent.
3. WHEN Extracted_OM_Data is stored, THE OM_Intake_Service SHALL validate that `current_cap_rate` is approximately equal to `current_noi` ÷ `asking_price` (within 0.5 percentage points), and SHALL store a `cap_rate_consistency_warning` if the values are inconsistent.
4. WHEN Extracted_OM_Data is stored, THE OM_Intake_Service SHALL validate that `current_grm` is approximately equal to `asking_price` ÷ `current_gross_potential_income` (within 2% tolerance), and SHALL store a `grm_consistency_warning` if the values are inconsistent.
5. WHEN any consistency warnings are present, THE Intake_Review_UI SHALL display them in a dedicated "Data Warnings" section showing the warning label, the field name, the computed value, the stated value, and the delta between them; warnings SHALL NOT block the user from confirming the intake.
6. IF `asking_price` is null or zero after extraction, THEN THE OM_Intake_Service SHALL store an `asking_price_missing_error` and SHALL NOT allow the user to confirm the intake until `asking_price` is provided.
7. IF `unit_count` is null or less than 1 after extraction, THEN THE OM_Intake_Service SHALL store a `unit_count_missing_error` and SHALL NOT allow the user to confirm the intake until `unit_count` is provided.
8. IF any required operand field for a consistency check (criteria 2–4) is null or zero, THEN THE OM_Intake_Service SHALL skip that specific check and store an `insufficient_data_warning` identifying the missing operand, rather than silently passing or erroneously failing the check.

---

### Requirement 11: Round-Trip Data Integrity

**User Story:** As a developer, I want the extracted and confirmed data to faithfully represent what was in the PDF, so that the resulting Deal is a reliable starting point for underwriting.

#### Acceptance Criteria

1. WHEN an OM_Intake_Job transitions to `CONFIRMED` status, THE OM_Intake_Service SHALL verify that the `deal_id` stored on the job references a Deal record whose `purchase_price` equals the confirmed `asking_price` value from the Extracted_OM_Data.
2. WHEN an OM_Intake_Job transitions to `CONFIRMED` status, THE OM_Intake_Service SHALL verify that the sum of `current_rent` across all Rent_Roll_Entry records on the created Deal equals the sum of (`current_avg_rent` × `unit_count`) across all Unit_Mix_Rows in the confirmed Extracted_OM_Data, within an absolute tolerance of $0.01.
3. WHEN an OM_Intake_Job transitions to `CONFIRMED` status, THE OM_Intake_Service SHALL verify that the number of Unit records created on the Deal equals the `unit_count` field in the confirmed Extracted_OM_Data.
4. WHEN a user overrides an extracted field value in the Intake_Review_UI and confirms the intake, THE OM_Intake_Service SHALL use the user-overridden value when creating the Deal record; IF the overridden value is null or invalid for the target field type, THEN THE OM_Intake_Service SHALL return a validation error without creating the Deal.
5. THE OM_Intake_Service SHALL store the original extracted value, the user-overridden value, and the timestamp of the override for each overridden field on the OM_Intake_Job.

---

### Requirement 12: Platform Integration

**User Story:** As an investor, I want the OM intake feature to be accessible from the platform's main navigation and to integrate with the existing multifamily Deal workflow, so that it feels like a natural part of the platform rather than a separate tool.

#### Acceptance Criteria

1. WHEN a user navigates the platform, THE Frontend SHALL expose an "Upload OM" button in the Multifamily section of the navigation that is visible without scrolling and labeled exactly "Upload OM".
2. WHEN a user is on the Deal list page, THE Frontend SHALL display an "Upload OM" button that navigates to the OM upload page.
3. WHEN an OM_Intake_Job is in `REVIEW` status and one or more Deals exist whose normalized address matches the extracted `property_address`, THE Frontend SHALL display links to those matching Deals (up to 5) so the user can compare the intake data against existing Deals.
4. WHEN a Deal is created from a confirmed OM intake, THE Deal_Service SHALL record in the Deal's audit trail that the Deal was created from an OM intake, including the `intake_job_id`, the user identity, and the timestamp.
5. WHERE the platform's existing Gemini API key configuration (`GOOGLE_AI_API_KEY`) is available, THE OM_Intake_Service SHALL reuse that key for both field extraction and market rent research rather than requiring a separate API key.
6. THE OM_Intake_Service SHALL use the existing `RealEstateAnalysisException` hierarchy for the following error categories: file validation errors (`InvalidFileError`), AI service errors (`ExternalServiceError`), job not found errors (`ResourceNotFoundError`), and confirmation conflicts (`ConflictError`), following the `@handle_errors` decorator pattern used by other controllers.
