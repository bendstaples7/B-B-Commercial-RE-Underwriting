# Implementation Plan: Actionable Lead Command Center

## Overview

This implementation plan covers the full Actionable Lead Command Center feature: database migrations, backend models, Action Engine service, backend services, Celery tasks, Flask Blueprint controllers, Marshmallow schemas, frontend components, API service extensions, routing updates, property-based tests (Hypothesis), and integration tests. Tasks are organized into 10 phases following the phased delivery plan in the requirements.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3.1", "4.1", "4.2", "4.3"],
      "description": "Data model foundation — migrations, models, exceptions, schemas"
    },
    {
      "wave": 2,
      "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "6.1", "6.2", "6.3", "7.1", "7.2"],
      "description": "Action Engine service, Celery tasks, and RA endpoint"
    },
    {
      "wave": 3,
      "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.9", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10"],
      "description": "Queue service and queue controller endpoints"
    },
    {
      "wave": 4,
      "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "11.1", "11.2", "11.3", "11.4", "11.5", "12.1", "12.2", "12.3", "12.4", "13.1", "13.2", "13.3", "13.4", "13.5", "13.6", "13.7", "13.8", "13.9", "13.10", "13.11", "13.12", "13.13", "13.14", "14.1", "14.2", "14.3", "14.4", "14.5", "15.1", "15.2", "15.3", "15.4"],
      "description": "Command center services and controllers"
    },
    {
      "wave": 5,
      "tasks": ["16.1", "17.1", "17.2", "17.3", "17.4", "17.5"],
      "description": "Frontend TypeScript types and API service extensions"
    },
    {
      "wave": 6,
      "tasks": ["18.1", "18.2", "19.1", "19.2", "20.1", "20.2", "21.1", "21.2", "22.1", "22.2", "23.1", "23.2"],
      "description": "Frontend Command Center components"
    },
    {
      "wave": 7,
      "tasks": ["24.1", "24.2", "25.1", "25.2", "26.1", "26.2", "26.3", "26.4", "26.5", "26.6", "26.7"],
      "description": "Frontend Queue components"
    },
    {
      "wave": 8,
      "tasks": ["27.1", "27.2"],
      "description": "Frontend routing updates"
    },
    {
      "wave": 9,
      "tasks": ["28.1", "28.2", "28.3", "28.4", "28.5", "28.6", "29.1", "29.2", "29.3", "29.4", "29.5", "29.6", "30.1", "30.2", "30.3", "30.4", "31.1", "31.2", "31.3", "32.1", "32.2", "32.3", "32.4"],
      "description": "Property-based tests (Hypothesis)"
    },
    {
      "wave": 10,
      "tasks": ["33.1", "33.2", "33.3", "33.4", "33.5", "33.6", "34.1", "34.2", "34.3", "34.4", "34.5", "35.1", "35.2", "35.3", "35.4", "35.5", "35.6"],
      "description": "Unit and integration tests"
    }
  ]
}
```

## Tasks

## Phase 1: Data Model Foundation

### 1. Database Migrations

- [x] 1.1 Create Alembic migration to add new columns to the `leads` table: `lead_status` (enum), `recommended_action` (enum), `has_phone`, `has_email`, `has_property_match`, `analysis_complete`, `follow_up_overdue`, `is_warm`, `data_completeness_score`, `last_contact_date`, `unanswered_call_count`, `hubspot_deal_stage`, `last_hubspot_sync_at`, `follow_up_date`, `review_required`, `review_reason`, `review_triggered_at`
  - Add composite indexes: `(lead_status, recommended_action)`, `(lead_status, has_property_match)`, `(follow_up_overdue, lead_status)`
  - Set `server_default='new'` for `lead_status` so existing rows are not null
- [x] 1.2 Create Alembic migration to create the `lead_tasks` table with all columns and indexes defined in the design (`ix_lead_tasks_lead_status`, `ix_lead_tasks_status_due_date`)
- [x] 1.3 Create Alembic migration to create the `lead_timeline_entries` table with all columns and indexes defined in the design (`ix_timeline_lead_occurred`, unique index on `hubspot_activity_id`)

### 2. Backend Models

- [x] 2.1 Create `backend/app/models/lead_task.py` — `LeadTask` SQLAlchemy model with all columns, indexes, and the `lead` relationship as specified in the design
- [x] 2.2 Create `backend/app/models/lead_timeline_entry.py` — `LeadTimelineEntry` SQLAlchemy model with all columns, indexes, and the `lead` relationship as specified in the design
- [x] 2.3 Extend `backend/app/models/lead.py` (the `Property`/`Lead` model) with all new signal columns, `lead_status`, `recommended_action`, and the `lead_tasks` / `timeline_entries` backrefs; re-export both new models from `backend/app/models/__init__.py`

### 3. Exception Classes

- [x] 3.1 Add new exception classes to `backend/app/exceptions.py`: `LeadTaskValidationError`, `InvalidLeadStatusTransitionError`, `InvalidTaskStatusTransitionError`, `DoNotContactViolationError`, `ActionEngineRecomputationError` — all extending `RealEstateAnalysisException` with the payload shapes defined in the design

### 4. Marshmallow Schemas (Data Model Layer)

- [x] 4.1 Add `LeadTaskSchema`, `LeadTaskCreateSchema`, `LeadTaskUpdateSchema`, `LeadTaskCompleteSchema`, and `LeadTaskSnoozeSchema` to `backend/app/schemas.py`
- [x] 4.2 Add `LeadTimelineEntrySchema` and `LeadTimelinePageSchema` to `backend/app/schemas.py`
- [x] 4.3 Add `LeadStatusUpdateSchema`, `LogNoteSchema`, `LogCallSchema`, `ParkLeadSchema`, `DoNotContactSchema`, and `ReactivateLeadSchema` to `backend/app/schemas.py`


## Phase 2: Action Engine

### 5. Action Engine Service

- [x] 5.1 Create `backend/app/services/action_engine_service.py` with the `TASK_TYPE_TO_RECOMMENDED_ACTION` static config dict and `RECOMMENDED_ACTION_METADATA` static config dict as defined in the design
- [x] 5.2 Implement `compute_recommended_action(lead) -> str | None` — pure function evaluating the 11-priority rule chain exactly as specified in the design (including the Priority 4 split: no address → `enrich_data`, has address but no match → `resolve_match`)
- [x] 5.3 Implement `recompute_and_persist(lead_id: int) -> Lead` — fetches lead, runs engine, persists `recommended_action`, appends a `recommended_action_changed` timeline entry only when the value changes
- [x] 5.4 Implement `bulk_recompute(lead_ids: list[int] | None = None)` — batch recomputation in chunks of 500, used by the Celery task; processes all leads when `lead_ids` is None
- [x] 5.5 Re-export `ActionEngineService` from `backend/app/services/__init__.py`

### 6. Celery Tasks

- [x] 6.1 Create `backend/app/tasks/action_engine_tasks.py` with `recompute_recommended_action(lead_id: int)` Celery task that calls `ActionEngineService.recompute_and_persist`
- [x] 6.2 Add `bulk_recompute_all_leads()` Celery task that calls `ActionEngineService.bulk_recompute()` — target: 10,000 leads in 60 seconds
- [x] 6.3 Register the new Celery tasks in `backend/celery_worker.py` (or wherever tasks are auto-discovered)

### 7. Action Engine Endpoint

- [x] 7.1 Add `GET /api/leads/:id/recommended-action` route to `backend/app/controllers/command_center_controller.py` (create the file if it does not exist) — returns current `recommended_action` and the signal field names/values that matched the winning rule
- [x] 7.2 Add `RecommendedActionResponseSchema` to `backend/app/schemas.py` for the above endpoint


## Phase 3: Queue Backend

### 8. Queue Service

- [x] 8.1 Create `backend/app/services/queue_service.py` — `QueueService` class with `get_counts() -> dict[str, int]` returning badge counts for all 7 queues
- [x] 8.2 Implement `get_todays_action(page, per_page, sort_by, sort_order)` — filters: `lead_status` in (`active`, `follow_up`) AND (`recommended_action = 'follow_up_now'` OR any open task has `due_date ≤ today`)
- [x] 8.3 Implement `get_previously_warm(page, per_page, sort_by, sort_order)` — filters: HubSpot activity exists, `lead_status` in (`active`, `new`), no Platform_Contact_Event in past 90 days; sorted by most recent HubSpot engagement date descending
- [x] 8.4 Implement `get_follow_up_overdue(page, per_page, sort_by, sort_order)` — filters: open task with `due_date` in the past OR (`recommended_action = 'follow_up_now'` AND `last_contact_date > 7 days ago`); sorted by earliest overdue date ascending
- [x] 8.5 Implement `get_no_next_action(page, per_page, sort_by, sort_order)` — filters: `lead_status` in (`active`, `new`), `recommended_action` in (null, `create_task`), no open tasks; sorted by status (`new` first) then lead score descending
- [x] 8.6 Implement `get_needs_review(page, per_page, sort_by, sort_order)` — filters: `review_required = true`; sorted by `review_triggered_at` descending
- [x] 8.7 Implement `get_do_not_contact(page, per_page, sort_by, sort_order)` — filters: `lead_status = 'do_not_contact'`
- [x] 8.8 Implement `get_missing_property_match(page, per_page, sort_by, sort_order)` — filters: `has_property_match = false` AND no `research_missing_pin` task exists; sorted by lead score descending
- [x] 8.9 Re-export `QueueService` from `backend/app/services/__init__.py`

### 9. Queue Controller

- [x] 9.1 Create `backend/app/controllers/queue_controller.py` — `queue_bp` Blueprint with prefix `/api/queues`
- [x] 9.2 Implement `GET /api/queues/counts` — calls `QueueService.get_counts()`, returns all 7 badge counts
- [x] 9.3 Implement `GET /api/queues/todays-action` — paginated, accepts `page`, `per_page`, `sort_by`, `sort_order`
- [x] 9.4 Implement `GET /api/queues/previously-warm`
- [x] 9.5 Implement `GET /api/queues/follow-up-overdue`
- [x] 9.6 Implement `GET /api/queues/no-next-action`
- [x] 9.7 Implement `GET /api/queues/needs-review`
- [x] 9.8 Implement `GET /api/queues/do-not-contact`
- [x] 9.9 Implement `GET /api/queues/missing-property-match`
- [x] 9.10 Add `QueueRowSchema` and `QueuePageSchema` to `backend/app/schemas.py` for queue list responses; register `queue_bp` in `backend/app/__init__.py`


## Phase 4: Command Center Backend

### 10. Lead Task Service

- [x] 10.1 Create `backend/app/services/lead_task_service.py` — `LeadTaskService` class
- [x] 10.2 Implement `create(lead_id, data) -> LeadTask` — validates title (1–255 chars), sets `status='open'`, appends `task_created` timeline entry, triggers RA recomputation; auto-transitions `lead_status` from `new` → `active`
- [x] 10.3 Implement `complete(task_id, lead_id) -> LeadTask` — validates task is `open` (raises `InvalidTaskStatusTransitionError` if already completed), sets `status='completed'`, records `completed_at`, appends `task_completed` timeline entry, triggers RA recomputation
- [x] 10.4 Implement `snooze(task_id, lead_id, new_due_date) -> LeadTask` — validates `new_due_date` is strictly after today (raises `LeadTaskValidationError` otherwise), updates `due_date`, appends `task_snoozed` timeline entry
- [x] 10.5 Implement `list_open(lead_id) -> list[LeadTask]` — returns open tasks ordered by `due_date` asc, nulls last
- [x] 10.6 Re-export `LeadTaskService` from `backend/app/services/__init__.py`

### 11. Lead Timeline Service

- [x] 11.1 Create `backend/app/services/lead_timeline_service.py` — `LeadTimelineService` class
- [x] 11.2 Implement `append(lead_id, event_type, actor, summary, metadata=None, occurred_at=None, source='manual', hubspot_activity_id=None) -> LeadTimelineEntry`
- [x] 11.3 Implement `get_page(lead_id, page, per_page=25) -> (list[LeadTimelineEntry], int)` — reverse-chronological order, excludes soft-deleted entries from display but retains them in DB
- [x] 11.4 Implement `soft_delete(entry_id, actor)` — replaces `summary` with `'[deleted]'`, preserves all other fields; raises error if entry is HubSpot-sourced
- [x] 11.5 Re-export `LeadTimelineService` from `backend/app/services/__init__.py`

### 12. Call Log Service

- [x] 12.1 Create `backend/app/services/call_log_service.py` — `CallLogService` class
- [x] 12.2 Implement `log_call(lead_id, outcome, duration_minutes, notes, actor) -> LeadTimelineEntry` — validates outcome is one of (`answered`, `voicemail`, `no_answer`, `busy`, `wrong_number`), validates duration 1–999 if provided; raises `DoNotContactViolationError` if lead is DNC; updates signals based on outcome (`answered` → update `last_contact_date`; `voicemail`/`no_answer` → increment `unanswered_call_count`; `wrong_number` → set `has_phone=false`); appends `call_logged` timeline entry; triggers RA recomputation; auto-transitions `lead_status` from `new` → `active`
- [x] 12.3 Implement `log_note(lead_id, body, actor) -> LeadTimelineEntry` — validates body 1–5,000 chars; raises `DoNotContactViolationError` if lead is DNC; appends `note_added` timeline entry; triggers RA recomputation; auto-transitions `lead_status` from `new` → `active`
- [x] 12.4 Re-export `CallLogService` from `backend/app/services/__init__.py`

### 13. Command Center Controller

- [x] 13.1 Create `backend/app/controllers/command_center_controller.py` — `command_center_bp` Blueprint with prefix `/api/leads`
- [x] 13.2 Implement `GET /api/leads/:id/command-center` — returns full command center payload: lead header fields, recommended action with metadata, open tasks, first page of timeline, property match status
- [x] 13.3 Implement `PATCH /api/leads/:id/status` — validates new status, persists change, appends `status_changed` timeline entry, triggers RA recomputation; handles DNC and suppressed special cases (set RA to null, close open tasks for DNC)
- [x] 13.4 Implement `POST /api/leads/:id/tasks` — delegates to `LeadTaskService.create`
- [x] 13.5 Implement `PATCH /api/leads/:id/tasks/:task_id` — delegates to `LeadTaskService.snooze` or update
- [x] 13.6 Implement `POST /api/leads/:id/tasks/:task_id/complete` — delegates to `LeadTaskService.complete`
- [x] 13.7 Implement `GET /api/leads/:id/timeline` — delegates to `LeadTimelineService.get_page`; clears `review_required` flag when called (marks review triggers acknowledged)
- [x] 13.8 Implement `POST /api/leads/:id/notes` — delegates to `CallLogService.log_note`
- [x] 13.9 Implement `POST /api/leads/:id/calls` — delegates to `CallLogService.log_call`
- [x] 13.10 Implement `POST /api/leads/:id/do-not-contact` — sets `lead_status='do_not_contact'`, sets `recommended_action=null`, cancels all open tasks, appends `status_changed` timeline entry
- [x] 13.11 Implement `POST /api/leads/:id/park` — sets `lead_status='nurture'`, validates optional re-activation date (future, ≤ 365 days), appends `status_changed` timeline entry
- [x] 13.12 Implement `POST /api/leads/:id/reactivate` — sets `lead_status='active'`, triggers RA recomputation, appends `status_changed` timeline entry
- [x] 13.13 Implement `POST /api/leads/:id/suppress` — sets `lead_status='suppressed'`, sets `recommended_action=null`, appends `status_changed` timeline entry
- [x] 13.14 Add `CommandCenterPayloadSchema` to `backend/app/schemas.py`; register `command_center_bp` in `backend/app/__init__.py`

### 14. Bulk Action Controller

- [x] 14.1 Create `backend/app/controllers/bulk_action_controller.py` — `bulk_action_bp` Blueprint with prefix `/api/leads/bulk`
- [x] 14.2 Implement `POST /api/leads/bulk/suppress` — suppresses multiple leads, returns count of successes and failures
- [x] 14.3 Implement `POST /api/leads/bulk/create-task` — creates a task for multiple leads, returns count of successes and failures
- [x] 14.4 Implement `POST /api/leads/bulk/do-not-contact` — marks multiple leads as DNC, returns count of successes and failures
- [x] 14.5 Add `BulkActionRequestSchema` and `BulkActionResultSchema` to `backend/app/schemas.py`; register `bulk_action_bp` in `backend/app/__init__.py`

### 15. HubSpot Timeline Import Service

- [x] 15.1 Create `backend/app/services/hubspot_timeline_import_service.py` — `HubSpotTimelineImportService` class
- [x] 15.2 Implement `import_activities_for_lead(lead_id, hubspot_activities) -> int` — maps HubSpot record types (notes, calls, tasks, deal stage changes) to `LeadTimelineEntry` rows with `source='hubspot'`; deduplicates by `hubspot_activity_id`; returns count of new entries written; updates `last_hubspot_sync_at` and `hubspot_deal_stage` on the lead; sets `review_required=true` if new entries were written
- [x] 15.3 Implement `derive_is_warm(lead_id) -> bool` — evaluates `is_warm` from imported call records: `true` iff at least one call with `outcome='connected'` and `occurred_at` within past 180 days exists
- [x] 15.4 Re-export `HubSpotTimelineImportService` from `backend/app/services/__init__.py`


## Phase 5: Frontend Types and API Layer

### 16. TypeScript Types

- [x] 16.1 Add all new TypeScript interfaces and enums to `frontend/src/types/index.ts`: `LeadStatus`, `RecommendedAction`, `LeadTaskType`, `LeadTaskStatus`, `TimelineEventType`, `LeadTask`, `LeadTimelineEntry`, `QueueRow`, `QueuePage`, `QueueCounts`, `CommandCenterPayload`, `RecommendedActionMeta`, `LogCallPayload`, `LogNotePayload`, `BulkActionResult`

### 17. Frontend API Service Extensions

- [x] 17.1 Add `queueService` to `frontend/src/services/api.ts`: `getCounts()`, `getTodaysAction(page, perPage)`, `getPreviouslyWarm(page, perPage)`, `getFollowUpOverdue(page, perPage)`, `getNoNextAction(page, perPage)`, `getNeedsReview(page, perPage)`, `getDoNotContact(page, perPage)`, `getMissingPropertyMatch(page, perPage)`
- [x] 17.2 Add `commandCenterService` to `frontend/src/services/api.ts`: `getCommandCenter(leadId)`, `getRecommendedAction(leadId)`, `updateStatus(leadId, status)`, `doNotContact(leadId)`, `park(leadId, reactivationDate?)`, `reactivate(leadId)`, `suppress(leadId)`, `getTimeline(leadId, page)`
- [x] 17.3 Add `leadTaskService` to `frontend/src/services/api.ts`: `createTask(leadId, data)`, `updateTask(leadId, taskId, data)`, `completeTask(leadId, taskId)`, `snoozeTask(leadId, taskId, newDueDate)`
- [x] 17.4 Add `callLogService` to `frontend/src/services/api.ts`: `logCall(leadId, payload)`, `logNote(leadId, payload)`
- [x] 17.5 Add `bulkActionService` to `frontend/src/services/api.ts`: `bulkSuppress(leadIds)`, `bulkCreateTask(leadIds, taskData)`, `bulkDoNotContact(leadIds)`


## Phase 6: Frontend Components — Command Center

### 18. RecommendedActionPanel Component

- [x] 18.1 Create `frontend/src/components/RecommendedActionPanel.tsx` — displays RA label, explanation (≤ 280 chars), and 1–5 action buttons; shows inline error on action failure without changing Timeline or RA; shows "DO NOT CONTACT" badge and disables outreach buttons when `lead_status='do_not_contact'`
- [x] 18.2 Create `frontend/src/components/RecommendedActionPanel.test.tsx` — tests: renders label/explanation/buttons, inline error on failure, DNC badge disables buttons, `create_task` RA shows inline CTA when no open tasks

### 19. LeadTaskList Component

- [x] 19.1 Create `frontend/src/components/LeadTaskList.tsx` — displays open tasks ordered by `due_date` asc (nulls last); inline task creation form (title 1–255 chars, optional due date); updates list without full page reload on save; shows inline error on failure preserving form data; shows "Create Task" CTA when RA is `create_task` and no open tasks
- [x] 19.2 Create `frontend/src/components/LeadTaskList.test.tsx` — tests: task ordering, inline form opens/closes, validation error on empty title, list updates on save, form preserved on server error

### 20. LeadTimeline Component

- [x] 20.1 Create `frontend/src/components/LeadTimeline.tsx` — paginated timeline (25/page) in reverse-chronological order; "Load more" control; HubSpot logo icon on `source='hubspot'` entries; shows event type, UTC timestamp, actor, summary; read-only for HubSpot entries
- [x] 20.2 Create `frontend/src/components/LeadTimeline.test.tsx` — tests: renders entries, HubSpot icon on hubspot entries, load more appends entries, read-only HubSpot entries

### 21. LogNoteForm Component

- [x] 21.1 Create `frontend/src/components/LogNoteForm.tsx` — free-text input (max 5,000 chars), character count display, save button; shows validation error on empty or over-limit; preserves form data on server error; usable from both Command Center and Queue rows
- [x] 21.2 Create `frontend/src/components/LogNoteForm.test.tsx` — tests: character count, validation error on empty, validation error on >5000 chars, form preserved on server error

### 22. LogCallForm Component

- [x] 22.1 Create `frontend/src/components/LogCallForm.tsx` — outcome dropdown (answered/voicemail/no_answer/busy/wrong_number), duration field (1–999, optional), notes textarea (max 2,000 chars); shows validation error on missing outcome or invalid duration; preserves form data on server error; usable from both Command Center and Queue rows
- [x] 22.2 Create `frontend/src/components/LogCallForm.test.tsx` — tests: outcome required validation, duration range validation, form preserved on server error

### 23. LeadCommandCenter Component

- [x] 23.1 Create `frontend/src/components/LeadCommandCenter.tsx` — main detail view; renders lead header (name, address, lead score, status badge), `RecommendedActionPanel`, `LeadTaskList`, `LeadTimeline`, `LogNoteForm`, `LogCallForm`, quick-action toolbar; status badge is an editable dropdown (all valid `Lead_Status` values); reverts badge on status change failure; shows property match status with link to analysis or Missing Property Match workflow; clears `review_required` on open (calls timeline endpoint)
- [x] 23.2 Create `frontend/src/components/LeadCommandCenter.test.tsx` — tests: renders all sections, status badge dropdown, status change success/failure, property match link, DNC badge visible


## Phase 7: Frontend Components — Queue Views

### 24. QueueTable Component

- [x] 24.1 Create `frontend/src/components/QueueTable.tsx` — reusable sortable table; sortable columns: lead name, lead score, `Lead_Status`, property address; bulk selection checkbox; optimistic UI updates on row actions; reverts row and shows inline error on optimistic update failure; "No leads in this queue" empty state (≤ 20 words); action buttons as icon buttons with hover tooltips fitting within row at 1280px viewport; bulk action summary on partial failure (X succeeded, Y failed)
- [x] 24.2 Create `frontend/src/components/QueueTable.test.tsx` — tests: sortable columns, bulk selection, optimistic update revert on failure, empty state, bulk partial failure summary

### 25. QueueSidebar Component

- [x] 25.1 Create `frontend/src/components/QueueSidebar.tsx` — sidebar nav with 7 queue links and live badge counts; uses React Query polling every 60 seconds via `queueService.getCounts()`; highlights active queue
- [x] 25.2 Create `frontend/src/components/QueueSidebar.test.tsx` — tests: renders all 7 links, badge counts displayed, active link highlighted

### 26. Queue View Components

- [x] 26.1 Create `frontend/src/components/TodaysActionQueue.tsx` — wraps `QueueTable`; displays summary header (total leads, count with overdue tasks, count with `follow_up_now`); three sort groups as defined in Req 18.2; "You're all caught up" empty state with active lead count and link to No Next Action Queue; auto-refreshes every 60 seconds without resetting scroll position; row actions: Log Call, Log Note, Create Task
- [x] 26.2 Create `frontend/src/components/PreviouslyWarmQueue.tsx` — wraps `QueueTable`; columns include last HubSpot activity type and date; row actions: Log Call, Log Note, Create Task, Suppress (with confirmation dialog)
- [x] 26.3 Create `frontend/src/components/FollowUpOverdueQueue.tsx` — wraps `QueueTable`; columns include overdue task description or follow-up date, days overdue; row actions: Complete Task, Snooze (date picker, must be ≥ 1 day future), Log Call, Log Note
- [x] 26.4 Create `frontend/src/components/NoNextActionQueue.tsx` — wraps `QueueTable`; columns include days since last activity; row actions: Create Task (inline form), Log Note, Park (optional re-activation date), Suppress (confirmation dialog)
- [x] 26.5 Create `frontend/src/components/NeedsReviewQueue.tsx` — wraps `QueueTable`; columns include review reason and trigger date; context-specific action button: "View Analysis" or "View Activity"
- [x] 26.6 Create `frontend/src/components/DoNotContactQueue.tsx` — wraps `QueueTable`; columns include DNC date and actor; row action: Reactivate (sets `lead_status='active'`, triggers RA recomputation)
- [x] 26.7 Create `frontend/src/components/MissingPropertyMatchQueue.tsx` — wraps `QueueTable`; columns include address as entered; row actions: Search Property (opens match interface pre-populated with address), Research PIN (creates `research_missing_pin` task), Suppress (confirmation dialog)


## Phase 8: Frontend Routing

### 27. Routing Updates

- [x] 27.1 Update `frontend/src/App.tsx` to add routes: `/` → `TodaysActionQueue` (default landing page after login), `/queues/previously-warm` → `PreviouslyWarmQueue`, `/queues/follow-up-overdue` → `FollowUpOverdueQueue`, `/queues/no-next-action` → `NoNextActionQueue`, `/queues/needs-review` → `NeedsReviewQueue`, `/queues/do-not-contact` → `DoNotContactQueue`, `/queues/missing-property-match` → `MissingPropertyMatchQueue`, `/leads/:id/command-center` → `LeadCommandCenter`
- [x] 27.2 Integrate `QueueSidebar` into the main layout in `App.tsx` so it is visible on all queue and command center routes


## Phase 9: Property-Based Tests (Hypothesis)

### 28. Action Engine Properties

- [x] 28.1 Write property test for **Property 1: Active Lead Actionability Invariant** — for any lead with `lead_status` in (`new`, `active`, `follow_up`), after `recompute_and_persist` runs, `recommended_action` is non-null OR at least one open `LeadTask` exists
  **Validates: Requirements 1.1, 21.7**
- [x] 28.2 Write property test for **Property 2: Action Engine Determinism** — for any combination of signal values, calling `compute_recommended_action` twice with identical inputs produces identical outputs
  **Validates: Requirements 2.2, 20.6**
- [x] 28.3 Write property test for **Property 3: Action Engine Priority Ordering** — for any signal combination, `compute_recommended_action` returns the action corresponding to the first matching rule; no lower-priority rule fires when a higher-priority rule matches
  **Validates: Requirements 16.1**
- [x] 28.4 Write property test for **Property 11: DNC Status Invariants** — for any lead with `lead_status='do_not_contact'`, `recommended_action` is null, lead does not appear in any active work queue, and all `LeadTask` records have `status` in (`completed`, `cancelled`)
  **Validates: Requirements 2.1, 5.4, 14.2, 21.2, 21.3**
- [x] 28.5 Write property test for **Property 16: Action Engine Timeline Entry Idempotency** — running `recompute_and_persist` twice with no signal changes between runs produces at most one `recommended_action_changed` timeline entry
  **Validates: Requirements 16.5**
- [x] 28.6 Place all action engine property tests in `backend/tests/test_action_engine_properties.py`; each test tagged with `# Feature: actionable-lead-command-center, Property N: <text>`; `@settings(max_examples=100)` minimum

### 29. Lead Task Properties

- [x] 29.1 Write property test for **Property 4: Task Title Validation Boundary** — strings of length 1–255 are accepted; length 0 or >255 are rejected with a validation error; task list unchanged after rejected creation
  **Validates: Requirements 3.2**
- [x] 29.2 Write property test for **Property 5: Task State Machine Validity** — only valid transition is `open → completed`; completing a completed task is a no-op; invalid status values are rejected with 400
  **Validates: Requirements 3.4, 21.5, 21.6**
- [x] 29.3 Write property test for **Property 6: Task Snooze Date Validation** — dates strictly after today are accepted and `due_date` updated; dates on or before today are rejected and `due_date` unchanged
  **Validates: Requirements 3.5**
- [x] 29.4 Write property test for **Property 14: Unanswered Call Count Monotonically Increments** — logging N calls with outcome `voicemail` or `no_answer` increments `unanswered_call_count` by exactly N
  **Validates: Requirements 9.4**
- [x] 29.5 Write property test for **Property 15: Note Length Validation Boundary** — strings of length 1–5,000 are accepted; length 0 or >5,000 are rejected; timeline unchanged after rejected note
  **Validates: Requirements 9.1**
- [x] 29.6 Place all lead task property tests in `backend/tests/test_lead_task_properties.py`

### 30. Timeline Properties

- [x] 30.1 Write property test for **Property 7: HubSpot Timeline Deduplication** — importing the same set of HubSpot activities twice produces zero new `LeadTimelineEntry` rows on the second import; total hubspot entry count is identical after both imports
  **Validates: Requirements 8.3, 8.4, 19.7**
- [x] 30.2 Write property test for **Property 8: Timeline Soft-Delete Preserves Audit Trail** — soft-deleting a native entry replaces `summary` with `'[deleted]'` but preserves `id`, `event_type`, `occurred_at`, `actor`, `lead_id`; entry remains queryable
  **Validates: Requirements 8.8, 21.4**
- [x] 30.3 Write property test for **Property 12: Lead Status Transition Recorded in Timeline** — for any `lead_status` transition, a `status_changed` timeline entry is appended; entry `metadata` contains previous status, new status, and UTC timestamp; entry is never absent after a successful status change
  **Validates: Requirements 5.8**
- [x] 30.4 Place all timeline property tests in `backend/tests/test_timeline_properties.py`

### 31. Queue Properties

- [x] 31.1 Write property test for **Property 9: Suppressed/Nurture/DNC Queue Exclusion** — leads with `lead_status='nurture'` do not appear in Previously Warm, Follow-Up Overdue, or No Next Action queues; leads with `lead_status` in (`suppressed`, `do_not_contact`) do not appear in any active work queue
  **Validates: Requirements 5.6, 5.7**
- [x] 31.2 Write property test for **Property 10: Queue Membership is a Pure Function of Lead State** — for any lead, its membership in each of the 7 queues is fully determined by its current state as defined in the design; a lead satisfying multiple criteria appears in each applicable queue exactly once per queue
  **Validates: Requirements 6.3–6.9, 22.6**
- [x] 31.3 Place all queue property tests in `backend/tests/test_queue_properties.py`

### 32. Lead Status Properties

- [x] 32.1 Write property test for **Property 13: Re-import Preserves Lead Status** — for any lead with any `lead_status`, re-importing that lead does not change the `lead_status`; status after re-import equals status before re-import
  **Validates: Requirements 5.10**
- [x] 32.2 Write property test for **Property 17: is_warm Signal Derivation** — `is_warm=true` iff at least one HubSpot call record has `outcome='connected'` and `occurred_at` within past 180 days; `is_warm=false` otherwise; holds for any combination of call records
  **Validates: Requirements 19.4**
- [x] 32.3 Write property test for **Property 18: Park Re-activation Date Boundary** — dates strictly after today and ≤ 365 days from today are accepted; dates on or before today or >365 days from today are rejected with a validation error
  **Validates: Requirements 5.5**
- [x] 32.4 Place all lead status property tests in `backend/tests/test_lead_status_properties.py`


## Phase 10: Unit and Integration Tests

### 33. Backend Unit Tests

- [x] 33.1 Create `backend/tests/test_action_engine_service.py` — unit tests for `compute_recommended_action`: each of the 11 priority rules fires correctly with a minimal signal set; Priority 4 split (no address → `enrich_data`, has address → `resolve_match`); suppressed/DNC leads return null; `recompute_and_persist` appends timeline entry only when RA changes
- [x] 33.2 Create `backend/tests/test_lead_task_service.py` — unit tests: task creation sets `status='open'`; completing an open task sets `completed_at`; completing a completed task is a no-op; snooze with past date raises `LeadTaskValidationError`; `list_open` orders by `due_date` asc nulls last
- [x] 33.3 Create `backend/tests/test_lead_timeline_service.py` — unit tests: `append` creates entry with correct fields; `get_page` returns reverse-chronological order; `soft_delete` replaces summary with `'[deleted]'`; soft-delete on HubSpot entry raises error
- [x] 33.4 Create `backend/tests/test_call_log_service.py` — unit tests: `answered` outcome updates `last_contact_date`; `voicemail`/`no_answer` increments `unanswered_call_count`; `wrong_number` sets `has_phone=false`; DNC lead raises `DoNotContactViolationError`; note body >5,000 chars raises validation error
- [x] 33.5 Create `backend/tests/test_queue_service.py` — unit tests: each queue's membership criteria with specific lead state examples; DNC lead excluded from active queues; nurture lead excluded from Previously Warm/Follow-Up Overdue/No Next Action; lead in multiple queues appears in each; `get_counts` returns correct badge counts
- [x] 33.6 Create `backend/tests/test_hubspot_timeline_import_service.py` — unit tests: importing activities creates entries with `source='hubspot'`; re-importing same activities creates zero new entries; `derive_is_warm` returns `true` with a connected call within 180 days; `derive_is_warm` returns `false` with no connected calls or all calls older than 180 days

### 34. Backend Integration Tests

- [x] 34.1 Create `backend/tests/test_queue_controller.py` — integration tests for all 8 queue endpoints: correct HTTP status, pagination params, sort params, empty queue returns 200 with empty list
- [x] 34.2 Create `backend/tests/test_command_center_controller.py` — integration tests: `GET /command-center` returns all sections; `PATCH /status` persists change and appends timeline entry; `POST /tasks` creates task; `POST /tasks/:id/complete` completes task; `POST /notes` and `POST /calls` log entries; `POST /do-not-contact` sets RA to null and cancels open tasks; `POST /park` validates re-activation date; DNC lead returns 403 on log-call/log-note
- [x] 34.3 Create `backend/tests/test_bulk_action_controller.py` — integration tests: bulk suppress, bulk create-task, bulk DNC; partial failure returns correct success/failure counts
- [x] 34.4 Add integration test to `backend/tests/test_command_center_controller.py` for HubSpot sync → timeline entries created with correct source and deduplication (using `HubSpotTimelineImportService` directly)
- [x] 34.5 Add integration test for bulk recomputation Celery task: processes 1,000 leads without error (using `bulk_recompute` directly, not via Celery broker)

### 35. Frontend Unit Tests

- [x] 35.1 Verify `frontend/src/components/LeadCommandCenter.test.tsx` covers: renders all sections, status badge dropdown opens, status change success updates badge, status change failure reverts badge, DNC badge visible and outreach buttons disabled
- [x] 35.2 Verify `frontend/src/components/RecommendedActionPanel.test.tsx` covers: renders RA label/explanation/buttons, inline error on action failure, `create_task` RA shows CTA when no open tasks
- [x] 35.3 Verify `frontend/src/components/LeadTaskList.test.tsx` covers: tasks ordered by due_date asc nulls last, inline form validation, list updates on save, form preserved on server error
- [x] 35.4 Verify `frontend/src/components/LeadTimeline.test.tsx` covers: entries in reverse-chronological order, HubSpot logo icon on hubspot entries, load more appends entries
- [x] 35.5 Verify `frontend/src/components/QueueTable.test.tsx` covers: sortable columns, bulk selection, optimistic update revert on failure, empty state message, bulk partial failure summary
- [x] 35.6 Verify `frontend/src/components/LogNoteForm.test.tsx` and `LogCallForm.test.tsx` cover all validation rules and form preservation on error


## Notes

- All backend tests use SQLite in-memory database (via `conftest.py` fixtures) — no live PostgreSQL required for the test suite.
- Property-based tests (Phase 9) use `hypothesis` which is already in `backend/requirements.txt`. Each test file uses `@settings(max_examples=100)` minimum and is tagged with `# Feature: actionable-lead-command-center, Property N: <text>`.
- The Action Engine (`compute_recommended_action`) is designed as a pure function operating on a `LeadSignals` dataclass or equivalent — it must not perform DB queries internally. DB access is handled by `recompute_and_persist`.
- The `lead_status` column uses `server_default='new'` so the Alembic migration can be applied to an existing `leads` table without a data migration step.
- Bulk action endpoints (Task 14) return partial-success responses — they do not roll back successful updates when some leads fail.
- The `research_missing_pin` task creation (Missing Property Match Queue) permanently removes the lead from that queue even if the task is later completed — the queue re-entry condition requires both no property match AND no such task.
- Frontend components use React Query for all data fetching. Queue badge counts are polled every 60 seconds. The Today's Action Queue auto-refreshes every 60 seconds without resetting scroll position.
- The `QueueTable` component is the single reusable table used by all 7 queue views — queue-specific wrappers (Tasks 26.1–26.7) configure columns, row actions, and sort behavior via props.
