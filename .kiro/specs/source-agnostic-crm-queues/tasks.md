# Implementation Plan: Source-Agnostic CRM Queues

## Overview

Four targeted changes make all 7 work queues source-agnostic. No schema
changes are required — all columns already exist. Tasks are ordered so
each layer (backend logic → pipeline → tests → frontend) can be verified
independently.

---

## Tasks

- [x] 1. Refactor QueueService — Previously Warm and No Next Action
  - [x] 1.1 Remove the `hubspot_signals` join from `_count_previously_warm`; replace with `Lead.is_warm.is_(True)` filter and drop the `ninety_days_ago` parameter
  - [x] 1.2 Remove the `hubspot_signals` join from `get_previously_warm`; replace with `Lead.is_warm.is_(True)` filter
  - [x] 1.3 Update `get_counts()` to call `self._count_previously_warm()` with no date argument
  - [x] 1.4 Expand the `_count_no_next_action` `recommended_action` allow-list to include `'ready_for_outreach'` and `'add_contact_info'` alongside the existing `None` and `'create_task'`
  - [x] 1.5 Apply the same allow-list expansion to `get_no_next_action` so count and paginated methods remain in sync
  - [x] 1.6 Remove the `HubSpotSignal` import from `queue_service.py` (no longer needed after steps 1.1–1.2)

- [x] 2. Update LeadIngestionService — `has_property_match` and `review_required`
  - [x] 2.1 In `_enrich_with_gis`, add `lead.has_property_match = False` in the `if parcel is None` branch (before the `return outcome` call)
  - [x] 2.2 Add the `_set_review_required_flag(self, lead, is_creation: bool) -> None` helper method to `LeadIngestionService` per the design spec: sets `review_required=True` / `review_reason='Missing phone, email, and county PIN'` on creation when all three fields are null/empty; clears the flag on update when all three are populated
  - [x] 2.3 Call `self._set_review_required_flag(lead, is_creation)` immediately after `self._set_skip_trace_flag(lead, is_creation)` in `ingest_foreclosure`
  - [x] 2.4 Call `self._set_review_required_flag(lead, is_creation)` immediately after `self._set_skip_trace_flag(lead, is_creation)` in `ingest_tax_distress`
  - [x] 2.5 Call `self._set_review_required_flag(lead, is_creation)` immediately after `self._set_skip_trace_flag(lead, is_creation)` in `ingest_long_owned`
  - [x] 2.6 Call `self._set_review_required_flag(lead, is_creation)` immediately after `self._set_skip_trace_flag(lead, is_creation)` in `ingest_absentee_owner`
  - [x] 2.7 Call `self._set_review_required_flag(lead, is_creation)` immediately after `self._set_skip_trace_flag(lead, is_creation)` in `process_csv` (if that method exists and follows the same pattern)

- [x] 3. Update HubSpot signal pipeline — set `is_warm` flag
  - [x] 3.1 Define `WARM_SIGNAL_TYPES = frozenset({'PRIOR_WARM_CONVERSATION', 'APPOINTMENT_OCCURRED'})` as a module-level constant in `hubspot_tasks.py`
  - [x] 3.2 In `run_extract_hubspot_signals`, after `db.session.commit()` (signals persisted), add a guarded block: check whether any signal in the current batch has `signal_type in WARM_SIGNAL_TYPES`; if so, load the Lead, and if `lead.is_warm` is not already `True`, set `lead.is_warm = True` and commit
  - [x] 3.3 Wrap the `is_warm` write in its own `try/except` that logs a warning on failure and continues — a warmth-flag failure must not abort signal processing for remaining interactions

- [x] 4. Fix frontend sidebar — split Properties label and chevron
  - [x] 4.1 In `App.tsx`, within the `NAV_SECTIONS.map` render loop, add a conditional branch for `section.path === '/properties'`
  - [x] 4.2 For the Properties branch, render a `Box` row with two separate click targets: a `ListItemButton` (with `component={Link}`, `to={section.path}`) for the label/icon that navigates to `/properties`; and an `IconButton` for the chevron that calls `toggleSection(section.path)` with `e.stopPropagation()`
  - [x] 4.3 For all other sections (the `else` branch), keep the existing single `ListItemButton` that calls `toggleSection(section.path)` — the Analysis section behavior is unchanged
  - [x] 4.4 Add `aria-label` attributes to both click targets: `aria-label={`Navigate to ${section.label}`}` on the ListItemButton and `aria-label={expandedSections[section.path] ? 'Collapse section' : 'Expand section'}` on the IconButton

- [x] 5. Write property-based tests for QueueService
  - [x] 5.1 Write Property 1 test (`test_property_1_no_next_action_filter_predicate`) in `backend/tests/test_queue_properties.py`: for any lead in the database, it appears in No Next Action iff `lead_status in ('new','active')` AND `recommended_action in (None, 'create_task', 'ready_for_outreach', 'add_contact_info')` AND no open task — use Hypothesis `@given` with `@settings(max_examples=100)`. **Validates: Requirements 1.1, 1.3, 1.4**
  - [x] 5.2 Write Property 3 test (`test_property_3_previously_warm_equals_is_warm`) in `backend/tests/test_queue_properties.py`: for any population of leads, Previously Warm contains exactly those with `is_warm=True` — no more, no fewer. **Validates: Requirements 4.1, 4.2**
  - [x] 5.3 Write Property 9 test (`test_property_9_priority_queues_exclude_no_next_action`) in `backend/tests/test_queue_properties.py`: the intersection of (Today's Action ∪ Follow-Up Overdue) and No Next Action is empty for any lead state. **Validates: Requirements 11.1, 11.2, 11.3**
  - [x] 5.4 Write Property 10 test (`test_property_10_owner_scoping_uniform`) in `backend/tests/test_queue_properties.py`: for any `owner_user_id` and any lead population, all 7 queues (counts and paginated) contain only leads with matching `owner_user_id`. **Validates: Requirements 12.3, 12.4**

- [x] 6. Write property-based tests for LeadIngestionService
  - [x] 6.1 Write Property 5 test (`test_property_5_review_required_creation_rule`) in `backend/tests/test_lead_ingestion_service.py`: for any newly-ingested lead, `review_required=True` iff all three of `phone_1`, `email_1`, `county_assessor_pin` are null/empty — use Hypothesis to generate all combinations. **Validates: Requirements 5.2, 5.3**
  - [x] 6.2 Write Property 6 test (`test_property_6_review_required_update_rule`) in `backend/tests/test_lead_ingestion_service.py`: for a lead already having `review_required=True`, after an update where all three fields are populated the flag clears; if any remain null/empty the flag stays. **Validates: Requirement 5.4**
  - [x] 6.3 Write Property 7 test (`test_property_7_gis_no_match_sets_false`) in `backend/tests/test_lead_ingestion_service.py`: when the GIS connector is configured and returns `None`, `has_property_match` is `False`; a prior `True` from a successful match is never overridden to `False`. **Validates: Requirements 6.2, 6.3, 6.4**

- [x] 7. Write property-based tests for HubSpot signal pipeline
  - [x] 7.1 Write Property 4 test (`test_property_4_warm_signal_sets_is_warm`) in `backend/tests/test_queue_properties.py`: for any lead processed by the signal pipeline, `is_warm=True` after processing iff any signal in the batch is `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED`; a lead that already had `is_warm=True` is never set to `False` — use Hypothesis to generate signal type combinations. All `db.session` calls are mocked; test runs synchronously without Celery. **Validates: Requirements 4.3, 9.1, 9.2, 9.3**

- [x] 8. Write property-based test for badge count / paginated total parity
  - [x] 8.1 Write Property 2 test (`test_property_2_badge_counts_equal_paginated_totals`) in `backend/tests/test_queue_properties.py`: for any state of the leads table, `get_counts()` returns a count for each queue that equals the `total` returned by the corresponding `get_*` method. Seed arbitrary lead populations with Hypothesis and assert count == total for all 7 queues. **Validates: Requirements 1.5, 2.3, 3.4, 4.5, 5.5, 6.5, 12.1**

- [x] 9. Update integration tests — add DuPage lead fixtures
  - [x] 9.1 Extend `backend/tests/test_queue_integration.py` with a `TestDuPageLeadQueueVisibility` class: seed both a HubSpot-sourced lead (no `source_type`) and a DuPage-sourced lead (`source_type='foreclosure'`) with identical qualifying field values, and assert both appear in the same queue. Cover No Next Action, Previously Warm (via `is_warm=True`), Needs Review, and Missing Property Match.
  - [x] 9.2 Add an integration test asserting that a DuPage lead with `is_warm=True` appears in the Previously Warm queue (replacing the old HubSpot signal seeding test for the same queue) to confirm the `is_warm`-only filter works end-to-end against the SQLite test DB.

- [x] 10. Write frontend sidebar tests
  - [x] 10.1 Create `frontend/src/App.test.tsx` with React Testing Library tests: clicking the Properties label text calls `mockNavigate` with `'/properties'` and does NOT call `toggleSection`; clicking the Properties chevron calls `toggleSection('/properties')` and does NOT call `mockNavigate`. **Validates: Requirement 10.1**
  - [x] 10.2 Add a test asserting that clicking the Analysis section header calls only `toggleSection` and does NOT call `navigate` — confirming other sections are unaffected. **Validates: Requirement 10.3**

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1", "2", "3", "4"],
      "description": "Core implementation — backend logic changes and frontend fix, all independent of each other"
    },
    {
      "wave": 2,
      "tasks": ["5", "6", "7", "8", "10"],
      "description": "Property-based and frontend tests — each test group validates the wave 1 change it corresponds to"
    },
    {
      "wave": 3,
      "tasks": ["9"],
      "description": "Integration tests — extend existing suite after QueueService (task 1) and signal pipeline (task 3) are in place"
    }
  ]
}
```

## Notes

- No database migrations are needed — `is_warm`, `review_required`, `review_reason`, and `has_property_match` columns already exist on the `leads` table.
- Task 1 (QueueService) and Task 3 (HubSpot pipeline) must be completed before existing `test_queue_integration.py` Previously Warm tests will pass with the new `is_warm`-only filter. The integration test class added in Task 9.1 should replace the existing `_make_warm_signal` approach for the Previously Warm queue test.
- Property tests in Tasks 5–8 are added to existing files (`test_queue_properties.py`, `test_lead_ingestion_service.py`) — do not create new test files for these.
- The frontend test file `App.test.tsx` is new (Task 10) — co-located at `frontend/src/App.test.tsx` per project conventions.
- Run backend tests with `cd backend && pytest tests/test_queue_properties.py tests/test_queue_integration.py tests/test_lead_ingestion_service.py -v`.
- Run frontend tests with `cd frontend && npm test`.
