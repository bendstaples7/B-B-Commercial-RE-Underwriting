# Implementation Plan: Gemini Comparable Search

## Overview

Replace the Socrata-based comparable sales search (Step 2) with a Gemini AI-powered search. This involves creating a new `GeminiComparableSearchService`, updating the Celery task, adding custom exceptions, updating the frontend `ComparableSale` type, adding a `SimilarityNotesCell` to `ComparableReviewTable`, creating a new `GeminiNarrativePanel` component, and updating the Step 2 loading message. The Socrata cache infrastructure is preserved untouched.

## Tasks

- [x] 1. Add custom Gemini exceptions to `exceptions.py`
  - Add `GeminiConfigurationError`, `GeminiAPIError`, `GeminiParseError`, and `GeminiResponseError` to `backend/app/exceptions.py`, all extending `RealEstateAnalysisException`
  - _Requirements: 1.5, 1.6, 1.7, 1.8_

- [x] 2. Implement `GeminiComparableSearchService`
  - [x] 2.1 Create `backend/app/services/gemini_comparable_search_service.py` with the service class skeleton
    - Define `RESIDENTIAL_PROMPT_TEMPLATE` and `COMMERCIAL_PROMPT_TEMPLATE` as module-level constants
    - Each template must include a system instruction requiring a single JSON object with exactly `"comparables"` and `"narrative"` top-level keys, a `{property_facts_json}` placeholder, and explicit field names/types for each comparable object
    - Implement `__init__` to read `GOOGLE_AI_API_KEY` from environment and raise `GeminiConfigurationError` if missing or empty
    - _Requirements: 1.7, 1.8_

  - [x] 2.2 Implement `_build_prompt`, `_call_gemini_api`, and `_parse_response` private methods
    - `_build_prompt`: select template based on `property_type` (`SINGLE_FAMILY`/`MULTI_FAMILY` → residential, `COMMERCIAL` → commercial), render with `json.dumps(property_facts, indent=2)`
    - `_call_gemini_api`: POST to Gemini API; raise `GeminiAPIError` on HTTP errors
    - `_parse_response`: parse JSON (raise `GeminiParseError` on invalid JSON), validate `"comparables"` and `"narrative"` keys present (raise `GeminiResponseError` if missing)
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 2.3 Implement the public `search` method
    - Orchestrate `_build_prompt` → `_call_gemini_api` → `_parse_response` and return `{"comparables": [...], "narrative": "..."}`
    - _Requirements: 1.1_

  - [x]* 2.4 Write property test for search result always has required keys (Property 1)
    - **Property 1: Search result always has required keys**
    - **Validates: Requirements 1.1, 1.4**
    - Use `@given(property_facts=st.dictionaries(st.text(), st.text()), property_type=st.sampled_from(PropertyType))` with a mocked Gemini API returning a well-formed response; assert result always contains `"comparables"` (list) and `"narrative"` (str)
    - File: `backend/tests/test_gemini_comparable_search_service.py`

  - [x]* 2.5 Write property test for prompt template selection (Property 2)
    - **Property 2: Prompt template selection is correct for all property types**
    - **Validates: Requirements 1.2, 1.3**
    - Use `@given(property_type=st.sampled_from(PropertyType))`; assert residential-prompt markers appear iff `property_type` is `SINGLE_FAMILY` or `MULTI_FAMILY`, and commercial-prompt markers appear iff `property_type` is `COMMERCIAL`
    - File: `backend/tests/test_gemini_comparable_search_service.py`

  - [x]* 2.6 Write property test for invalid JSON raises parse error (Property 3)
    - **Property 3: Invalid JSON always raises a parse error**
    - **Validates: Requirements 1.5**
    - Use `@given(raw=st.text().filter(lambda s: not _is_valid_json(s)))`; assert `_parse_response(raw)` raises `GeminiParseError`
    - File: `backend/tests/test_gemini_comparable_search_service.py`

  - [x]* 2.7 Write property test for missing required keys raises response error (Property 4)
    - **Property 4: Missing required keys always raise a response error**
    - **Validates: Requirements 1.6**
    - Use `@given(missing_key=st.sampled_from(["comparables", "narrative", "both"]))`; assert `_parse_response` raises `GeminiResponseError` identifying the missing field(s)
    - File: `backend/tests/test_gemini_comparable_search_service.py`

  - [x]* 2.8 Write example unit tests for `GeminiComparableSearchService`
    - Test `__init__` raises `GeminiConfigurationError` when `GOOGLE_AI_API_KEY` is unset or empty
    - Test `search()` calls Gemini with the correct prompt for each `PropertyType`
    - Test `search()` returns correct dict shape on a valid mocked response
    - File: `backend/tests/test_gemini_comparable_search_service.py`

- [x] 3. Implement `_map_comparable_to_model` helper and field mapping
  - [x] 3.1 Add `_map_comparable_to_model(comp_dict, session_id)` helper in `celery_worker.py`
    - Map all 16 fields from the Gemini JSON comparable object to `ComparableSale` columns per the field mapping table in the design
    - Implement enum resolution order: try `EnumClass(value)`, then `EnumClass[value.upper()]`, then fall back to defaults (`PropertyType.SINGLE_FAMILY`, `ConstructionType.FRAME`, `InteriorCondition.AVERAGE`)
    - Parse `sale_date` as `YYYY-MM-DD`; default to `date.today()` on any parse failure
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 3.2 Write property test for field mapping preserves all valid fields (Property 7)
    - **Property 7: Field mapping preserves all valid comparable fields**
    - **Validates: Requirements 3.1**
    - Use `@given(comp=st.fixed_dictionaries({...}))` with valid values for all 16 fields; assert every `ComparableSale` field matches the corresponding input value after type coercion
    - File: `backend/tests/test_comparable_field_mapping.py`

  - [x]* 3.3 Write property test for enum defaults on unrecognized values (Property 8)
    - **Property 8: Enum defaults are applied for all unrecognized values**
    - **Validates: Requirements 3.2, 3.3, 3.4**
    - Use `@given(bad_value=st.text().filter(lambda s: s not in valid_enum_values))`; assert defaults `PropertyType.SINGLE_FAMILY`, `ConstructionType.FRAME`, `InteriorCondition.AVERAGE` are applied
    - File: `backend/tests/test_comparable_field_mapping.py`

  - [x]* 3.4 Write property test for unparseable sale dates default to today (Property 9)
    - **Property 9: Unparseable sale dates default to today**
    - **Validates: Requirements 3.5**
    - Use `@given(bad_date=st.text().filter(lambda s: not _is_iso_date(s)))`; assert `sale_date` is `date.today()`
    - File: `backend/tests/test_comparable_field_mapping.py`

- [x] 4. Checkpoint — Ensure all backend service and mapping tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Update `run_comparable_search_task` in `celery_worker.py`
  - [x] 5.1 Replace `ComparableSalesFinder` call with `GeminiComparableSearchService.search()`
    - Instantiate `GeminiComparableSearchService`, call `search(property_facts, property_type)` using `_serialize_property_facts` to convert the ORM object
    - Iterate `result['comparables']`, call `_map_comparable_to_model` for each, and `db.session.add` each record
    - Store `result['narrative']` in `step_results['COMPARABLE_SEARCH']['narrative']` alongside existing `comparable_count` and `status` keys
    - Preserve all existing session state update logic (`current_step`, `completed_steps`, `updated_at`, `loading = False`)
    - On exception: set `session.loading = False`, store error in `step_results['COMPARABLE_SEARCH_ERROR']`, commit
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x]* 5.2 Write property test for comparable count matches response list length (Property 5)
    - **Property 5: Comparable count matches Gemini response list length**
    - **Validates: Requirements 2.2**
    - Use `@given(n=st.integers(min_value=0, max_value=20))`; mock `GeminiComparableSearchService.search` to return N comparables; assert exactly N `ComparableSale` records exist in the DB for that session after task completes
    - File: `backend/tests/test_gemini_comparable_search_task.py`

  - [x]* 5.3 Write property test for narrative round-trip preservation (Property 6)
    - **Property 6: Narrative round-trip preservation**
    - **Validates: Requirements 2.3**
    - Use `@given(narrative=st.text())`; mock `GeminiComparableSearchService.search`; assert `session.step_results['COMPARABLE_SEARCH']['narrative']` equals the exact narrative string returned
    - File: `backend/tests/test_gemini_comparable_search_task.py`

  - [x]* 5.4 Write example unit tests for the updated task
    - Test task creates exactly N `ComparableSale` records when Gemini returns N comparables
    - Test task stores narrative in `step_results['COMPARABLE_SEARCH']['narrative']`
    - Test task sets `session.loading = False` on success
    - Test task sets `session.loading = False` and stores error in `step_results['COMPARABLE_SEARCH_ERROR']` on `GeminiAPIError`
    - File: `backend/tests/test_gemini_comparable_search_task.py`

- [x] 6. Decouple `WorkflowController` from `ComparableSalesFinder`
  - Remove `self.comparable_finder = ComparableSalesFinder()` from `WorkflowController.__init__` and remove the `ComparableSalesFinder` import
  - Remove or stub out `_execute_comparable_search` (the Celery task now calls `GeminiComparableSearchService` directly)
  - Do NOT delete `ComparableSalesFinder` or its service file — it is still used by the multifamily underwriting proforma feature
  - _Requirements: 8.4_

- [x] 7. Add environment configuration and startup validation
  - [x] 7.1 Add `GOOGLE_AI_API_KEY=your_google_ai_api_key_here` to `backend/.env.example`
    - _Requirements: 4.1_

  - [x] 7.2 Add startup warning in `create_app` factory (`backend/app/__init__.py`)
    - Log a `WARNING`-level message if `GOOGLE_AI_API_KEY` is not set or is empty; do not raise — the app should still start
    - _Requirements: 4.2_

  - [x] 7.3 Add `GOOGLE_AI_API_KEY` to `_required_env_vars` in `celery_worker.py`
    - The worker must fail at startup with a descriptive error if the key is missing, consistent with the existing `DATABASE_URL`/`REDIS_URL` pattern
    - _Requirements: 4.3_

- [x] 8. Re-export `GeminiComparableSearchService` from `backend/app/services/__init__.py`
  - Add the new service to the services package `__init__.py` following the existing one-service-per-file convention
  - _Requirements: 1.1_

- [x] 9. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Update `ComparableSale` TypeScript type
  - Add `similarityNotes?: string | null` as an optional field to the `ComparableSale` interface in `frontend/src/types/index.ts`
  - Making it optional ensures backward compatibility with manually-added comparables and existing serialized session data
  - _Requirements: 5.5_

- [x] 11. Add `SimilarityNotesCell` and Similarity Notes column to `ComparableReviewTable`
  - [x] 11.1 Implement `SimilarityNotesCell` sub-component inside `ComparableReviewTable.tsx`
    - Render empty `<TableCell />` when `similarityNotes` is null, undefined, or empty
    - Render full text when `similarityNotes.length <= 100`
    - Render first 100 characters + `<Button size="small">…more</Button>` when length > 100; clicking toggles local `expanded` state to show full text
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 11.2 Add "Similarity Notes" column header and `SimilarityNotesCell` to the table
    - Insert as the last data column before the "Actions" column
    - Pass `similarityNotes` from each `ComparableSale` row; do not change the `onComparablesChange` callback signature
    - _Requirements: 5.1, 5.5_

  - [x]* 11.3 Write property test for similarity notes truncation threshold (Property 10)
    - **Property 10: Similarity notes truncation threshold**
    - **Validates: Requirements 5.2**
    - Use `fc.property(fc.string({ minLength: 101 }), ...)` with fast-check; assert exactly the first 100 characters are displayed with a "…more" affordance, and no characters beyond position 100 are visible before activation
    - File: `frontend/src/components/ComparableReviewTable.test.tsx`

  - [x]* 11.4 Write example unit tests for `ComparableReviewTable` similarity notes column
    - Test "Similarity Notes" column header is present before "Actions" column
    - Test clicking "…more" on a truncated cell shows the full text
    - Test null/empty `similarityNotes` renders an empty cell
    - File: `frontend/src/components/ComparableReviewTable.test.tsx`

- [x] 12. Create `GeminiNarrativePanel` component
  - [x] 12.1 Create `frontend/src/components/GeminiNarrativePanel.tsx`
    - Accept `{ narrative: string | null | undefined }` props
    - Return `null` when `narrative` is null, undefined, or empty string
    - Render an MUI `Accordion` with `defaultExpanded={true}`; `AccordionSummary` label "AI Analysis"
    - `AccordionDetails` contains a `Box` with `sx={{ maxHeight: 400, overflowY: 'auto', whiteSpace: 'pre-wrap' }}`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x]* 12.2 Write property test for narrative whitespace preservation (Property 11)
    - **Property 11: Narrative whitespace preservation**
    - **Validates: Requirements 6.7**
    - Use `fc.property(fc.string(), ...)` with fast-check; assert the rendered container has `white-space: pre-wrap` (or equivalent) applied for any non-empty narrative string
    - File: `frontend/src/components/GeminiNarrativePanel.test.tsx`

  - [x]* 12.3 Write example unit tests for `GeminiNarrativePanel`
    - Test panel renders when narrative is present
    - Test panel does not render when narrative is null, undefined, or empty string
    - Test panel is expanded by default
    - Test clicking "AI Analysis" header collapses and re-expands the panel
    - Test container has `maxHeight: 400px` and `overflowY: auto`
    - File: `frontend/src/components/GeminiNarrativePanel.test.tsx`

- [x] 13. Wire `GeminiNarrativePanel` into the Step 3 view in `App.tsx`
  - Render `<GeminiNarrativePanel narrative={session?.stepResults?.COMPARABLE_SEARCH?.narrative} />` immediately below `<ComparableReviewTable />` in the Step 3 view
  - Read narrative from `session.step_results?.COMPARABLE_SEARCH?.narrative` via the existing session state
  - _Requirements: 6.1, 6.2_

- [x] 14. Update Step 2 loading message in `App.tsx`
  - Change the loading message for `currentStep === WorkflowStep.COMPARABLE_SEARCH` from `"Searching for comparable sales… This may take up to 2 minutes."` to `"Searching for comparable sales with AI… This may take up to 2 minutes."`
  - _Requirements: 7.1_

- [x] 15. Update integration tests to patch `GeminiComparableSearchService`
  - In `backend/tests/test_comparable_search_fixes.py`, replace patches of `ComparableSalesFinder.find_comparables` with patches of `GeminiComparableSearchService.search`
  - Add a regression test that `POST /api/cache/socrata/sync` still returns the expected response (Requirement 8.1 guard)
  - _Requirements: 8.1, 8.4_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all backend (`cd backend && pytest`) and frontend (`cd frontend && npm test`) tests pass. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The `ComparableSalesFinder` class and Socrata cache infrastructure are NOT deleted — they remain for the multifamily underwriting proforma feature
- Property tests use Hypothesis (`@settings(max_examples=100)`) on the backend and fast-check (`numRuns: 100`) on the frontend
- Each property test should be tagged with a comment: `# Feature: gemini-comparable-search, Property N: <property_text>`
- No database migration is required — `similarity_notes` column already exists on `ComparableSale`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "10"] },
    { "id": 1, "tasks": ["2.1", "7.1", "7.2", "7.3"] },
    { "id": 2, "tasks": ["2.2", "3.1", "8"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["2.4", "2.5", "2.6", "2.7", "2.8", "3.2", "3.3", "3.4", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "6", "11.1"] },
    { "id": 6, "tasks": ["11.2", "12.1"] },
    { "id": 7, "tasks": ["11.3", "11.4", "12.2", "12.3", "13", "14", "15"] }
  ]
}
```
