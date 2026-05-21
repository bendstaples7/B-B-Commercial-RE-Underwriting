# Implementation Plan: HubSpot CRM Migration

## Overview

Transforms the platform into a self-sufficient, property-first CRM by migrating all historical data from HubSpot and building the internal structures needed to replace it. The implementation spans six active phases: (1) Internal CRM Foundation — Organization, Interaction, and Task models with timeline support; (2) HubSpot Raw Historical Import — Celery-driven paginated import; (3) HubSpot Mapping and Matching — PIN/address/email/name matching with confidence levels; (4) Activity Conversion and Timeline — converting raw engagements to internal records; (5) Lead Scoring and Signal Enrichment — keyword-based signal extraction and score adjustments; (6) Frontend — import area, review queue, timeline panel, note/task form, and lead views. Twenty correctness properties are verified with Hypothesis property-based tests.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8"] },
    { "id": 1, "tasks": ["1.9", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "2.9"] },
    { "id": 2, "tasks": ["2.10", "3.1", "5.1"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "6.1", "6.2", "6.3", "6.4"] },
    { "id": 4, "tasks": ["4.4", "7.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["7.2", "8.2", "8.3", "9.2"] },
    { "id": 6, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 7, "tasks": ["10.4", "11.1"] },
    { "id": 8, "tasks": ["11.2", "12.1"] },
    { "id": 9, "tasks": ["12.2", "13.1"] },
    { "id": 10, "tasks": ["13.2", "14.1"] },
    { "id": 11, "tasks": ["14.2", "15.1"] },
    { "id": 12, "tasks": ["16.1"] },
    { "id": 13, "tasks": ["16.2", "17.1"] },
    { "id": 14, "tasks": ["17.2", "18.1"] },
    { "id": 15, "tasks": ["18.2", "19.1"] },
    { "id": 16, "tasks": ["19.2", "19.3"] },
    { "id": 17, "tasks": ["20.1", "20.2", "20.3", "20.4"] },
    { "id": 18, "tasks": ["21.1", "22.1", "23.1", "24.1"] },
    { "id": 19, "tasks": ["25.1", "25.2", "25.3"] },
    { "id": 20, "tasks": ["26.1", "26.2", "27.1", "28.1", "29.1", "29.2"] },
    { "id": 21, "tasks": ["30.1", "30.2", "31.1", "32.1", "33.1", "33.2", "33.3"] },
    { "id": 22, "tasks": ["34.1", "34.2", "35.1", "36.1", "37.1", "38.1", "39.1"] },
    { "id": 23, "tasks": ["40.1", "40.2", "40.3", "40.4", "40.5"] },
    { "id": 24, "tasks": ["41.1", "41.2", "41.3", "41.4"] }
  ]
}
```

## Tasks

- [x] 1. Database Models — Organization, Interaction, Task
  - [x] 1.1 Create `backend/app/models/organization.py` with `Organization` model: id, name (String 500, not null), org_type (Enum: llc/trust/corporation/brokerage/law_firm/property_management/unknown), status (Enum: active/inactive/unknown), notes (Text nullable), source (String 100 nullable), hubspot_company_id (String 50 nullable, indexed), created_at, updated_at; relationships to PropertyOrganizationLink, OwnerOrganizationLink, OrganizationAuditLog
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 Create `backend/app/models/organization_audit_log.py` with `OrganizationAuditLog` model: id, organization_id (FK→organizations.id CASCADE, indexed), field_name (String 100), old_value (Text nullable), new_value (Text nullable), changed_by (String 100), changed_at (DateTime)
    - _Requirements: 1.4_
  - [x] 1.3 Create `backend/app/models/property_organization_link.py` with `PropertyOrganizationLink` model: id, property_id (FK→leads.id CASCADE, indexed), organization_id (FK→organizations.id CASCADE, indexed), role (String 100), created_at
    - _Requirements: 1.2, 1.6_
  - [x] 1.4 Create `backend/app/models/owner_organization_link.py` with `OwnerOrganizationLink` model: id, owner_id (FK→leads.id CASCADE, indexed), organization_id (FK→organizations.id CASCADE, indexed), role (String 100), created_at
    - _Requirements: 1.3, 1.6_
  - [x] 1.5 Create `backend/app/models/interaction.py` with `Interaction` model: id, interaction_type (Enum: note/call/email/meeting/other), body (Text not null), occurred_at (DateTime not null), source (Enum: manual/hubspot_import), hubspot_engagement_id (String 50 unique indexed nullable), raw_payload (JSON nullable), is_orphaned (Boolean default False), created_at, updated_at; relationship to InteractionAssociation
    - _Requirements: 2.1, 2.5_
  - [x] 1.6 Create `backend/app/models/interaction_association.py` with `InteractionAssociation` model: id, interaction_id (FK→interactions.id CASCADE, indexed), target_type (Enum: lead/organization/contact), target_id (Integer); composite index on (target_type, target_id)
    - _Requirements: 2.1, 2.4_
  - [x] 1.7 Create `backend/app/models/task.py` with `Task` model: id, title (String 500 not null), body (Text nullable), due_date (DateTime nullable), status (Enum: open/completed/cancelled/overdue), priority (Enum: high/medium/low), source (Enum: manual/hubspot_import), hubspot_task_id (String 50 unique indexed nullable), raw_payload (JSON nullable), completion_timestamp (DateTime nullable), created_at, updated_at; relationship to TaskAssociation
    - _Requirements: 3.1, 3.4_
  - [x] 1.8 Create `backend/app/models/task_association.py` with `TaskAssociation` model: id, task_id (FK→tasks.id CASCADE, indexed), target_type (Enum: lead/organization), target_id (Integer); composite index on (target_type, target_id)
    - _Requirements: 3.1_
  - [x] 1.9 Re-export all new models (Organization, OrganizationAuditLog, PropertyOrganizationLink, OwnerOrganizationLink, Interaction, InteractionAssociation, Task, TaskAssociation) from `backend/app/models/__init__.py`
    - _Requirements: 1.1, 2.1, 3.1_

- [x] 2. Database Models — HubSpot Raw Tables
  - [x] 2.1 Create `backend/app/models/hubspot_config.py` with `HubSpotConfig` model: id, encrypted_token (Text not null), portal_id (String 50 nullable), account_name (String 255 nullable), created_at, updated_at
    - _Requirements: 6.1, 6.2_
  - [x] 2.2 Create `backend/app/models/hubspot_import_run.py` with `HubSpotImportRun` model: id, object_type (String 50), status (Enum: running/success/partial/failed), start_time, end_time (nullable), total_fetched (Integer default 0), created_count (Integer default 0), updated_count (Integer default 0), skipped_count (Integer default 0), error_count (Integer default 0), error_message (Text nullable)
    - _Requirements: 7.6, 7.7, 20.1, 20.4_
  - [x] 2.3 Create `backend/app/models/hubspot_deal.py` with `HubSpotDeal` model: id, hubspot_id (String 50 unique indexed not null), raw_payload (JSON not null), import_run_id (FK→hubspot_import_runs.id nullable), first_imported_at (DateTime), last_updated_at (DateTime)
    - _Requirements: 7.1, 7.5, 8.1, 8.6_
  - [x] 2.4 Create `backend/app/models/hubspot_contact.py` with `HubSpotContact` model (same structure as HubSpotDeal, table name `hubspot_contacts`)
    - _Requirements: 7.2, 7.5, 8.2, 8.6_
  - [x] 2.5 Create `backend/app/models/hubspot_company.py` with `HubSpotCompany` model (same structure as HubSpotDeal, table name `hubspot_companies`)
    - _Requirements: 7.3, 7.5, 8.3, 8.6_
  - [x] 2.6 Create `backend/app/models/hubspot_engagement.py` with `HubSpotEngagement` model: id, hubspot_id (String 50 unique indexed not null), engagement_type (String 50 not null: NOTE/CALL/TASK), raw_payload (JSON not null), import_run_id (FK nullable), first_imported_at, last_updated_at
    - _Requirements: 7.4, 7.5, 8.4, 8.6_
  - [x] 2.7 Create `backend/app/models/hubspot_match.py` with `HubSpotMatch` model: id, hubspot_record_type (String 50), hubspot_id (String 50 indexed), internal_record_type (String 50 nullable), internal_record_id (Integer nullable), confidence (Enum: HIGH/MEDIUM/LOW/UNMATCHED), status (Enum: pending/confirmed/rejected default pending), matching_criteria (String 100 nullable), created_at, updated_at; unique constraint on (hubspot_record_type, hubspot_id)
    - _Requirements: 10.2, 10.3, 10.4, 11.2, 11.3, 12.2, 13.1_
  - [x] 2.8 Create `backend/app/models/hubspot_signal.py` with `HubSpotSignal` model: id, lead_id (FK→leads.id CASCADE indexed), signal_type (Enum: PRIOR_INTERACTION_EXISTS/PRIOR_RESPONSE_EXISTS/PRIOR_WARM_CONVERSATION/ASKING_PRICE_GIVEN/APPOINTMENT_OCCURRED/OFFER_PREVIOUSLY_SENT/SELLER_SAID_MAYBE_LATER/SELLER_NOT_INTERESTED/WRONG_NUMBER/DO_NOT_CONTACT/FOLLOW_UP_OVERDUE/PRIOR_LEAD_SOURCE_KNOWN), source_engagement_id (String 50 nullable), extracted_at (DateTime), raw_evidence (Text nullable)
    - _Requirements: 16.2, 16.5_
  - [x] 2.9 Create `backend/app/models/hubspot_signal_dictionary.py` with `HubSpotSignalDictionary` model: id, signal_type (String 50 unique), keywords (JSON not null), updated_at
    - _Requirements: 16.1, 16.6_
  - [x] 2.10 Re-export all new HubSpot models from `backend/app/models/__init__.py`
    - _Requirements: 6.1, 7.1, 7.2, 7.3, 7.4_

- [x] 3. Lead Model Extensions
  - [x] 3.1 Add `suppression_flag` (Boolean not null default False) and `recommended_action` (Enum: CONTACT_NOW/FOLLOW_UP_LATER/REVISIT_OFFER/DO_NOT_CONTACT, nullable) columns to `backend/app/models/lead.py`
    - _Requirements: 16.3, 17.3, 17.4, 17.6_

- [x] 4. Alembic Migration
  - [x] 4.1 Generate Alembic migration script for all new tables: organizations, organization_audit_log, property_organization_links, owner_organization_links, interactions, interaction_associations, tasks, task_associations, hubspot_config, hubspot_import_runs, hubspot_deals, hubspot_contacts, hubspot_companies, hubspot_engagements, hubspot_matches, hubspot_signals, hubspot_signal_dictionary; include all enum types, indexes, foreign keys, and unique constraints
    - _Requirements: 1.1, 2.1, 3.1, 6.1, 7.1, 7.2, 7.3, 7.4_
  - [x] 4.2 Add migration steps for Lead model extensions: suppression_flag column, recommended_action column, recommended_action_enum type
    - _Requirements: 16.3, 17.3, 17.4_
  - [x] 4.3 Add seed data migration step that inserts the 11 default signal keyword dictionary entries into hubspot_signal_dictionary (PRIOR_WARM_CONVERSATION, APPOINTMENT_OCCURRED, OFFER_PREVIOUSLY_SENT, SELLER_SAID_MAYBE_LATER, SELLER_NOT_INTERESTED, WRONG_NUMBER, DO_NOT_CONTACT, ASKING_PRICE_GIVEN, PRIOR_INTERACTION_EXISTS, PRIOR_RESPONSE_EXISTS, PRIOR_LEAD_SOURCE_KNOWN)
    - _Requirements: 16.1, 16.6_
  - [x] 4.4 Verify migration runs cleanly with `flask db upgrade` against a local PostgreSQL instance
    - _Requirements: 1.1, 2.1, 3.1_

- [x] 5. New Exception Classes
  - [x] 5.1 Add `HubSpotReadOnlyViolation` (status 500), `HubSpotAuthenticationError` (status 401), `HubSpotRateLimitError` (status 429, retry_after field), `ImportRunNotFoundError` (extends ResourceNotFoundError), `MatchNotFoundError` (extends ResourceNotFoundError), `OrganizationValidationError` (extends ValidationException), `InteractionValidationError` (extends ValidationException), and `TaskValidationError` (extends ValidationException) to `backend/app/exceptions.py`; each with appropriate payload dict and error_type field
    - _Requirements: 1.5, 2.3, 3.3, 19.3_

- [x] 6. Marshmallow Schemas
  - [x] 6.1 Add `OrganizationSchema`, `OrganizationAuditLogSchema`, `PropertyOrganizationLinkSchema`, `OwnerOrganizationLinkSchema` to `backend/app/schemas.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 6.2 Add `InteractionSchema`, `InteractionAssociationSchema`, `TimelineEntrySchema` to `backend/app/schemas.py`
    - _Requirements: 2.1, 4.3_
  - [x] 6.3 Add `TaskSchema`, `TaskAssociationSchema` to `backend/app/schemas.py`
    - _Requirements: 3.1_
  - [x] 6.4 Add `HubSpotConfigSchema` (token masked/excluded in output), `HubSpotImportRunSchema`, `HubSpotMatchSchema`, `HubSpotSignalSchema` to `backend/app/schemas.py`
    - _Requirements: 6.2, 7.6, 13.2_

- [x] 7. OrganizationService
  - [x] 7.1 Create `backend/app/services/organization_service.py` with `OrganizationService` class implementing: `create(data, changed_by)` — validate name non-empty (raise `OrganizationValidationError`), create org, write audit log entry for creation; `update(org_id, data, changed_by)` — update fields, write audit log entry for each changed field; `soft_delete(org_id, changed_by)` — set status=inactive, write audit log entry; `link_property(org_id, property_id, role)` — create `PropertyOrganizationLink`; `unlink_property(link_id)` — delete link; `link_owner(org_id, owner_id, role)` — create `OwnerOrganizationLink`; `unlink_owner(link_id)` — delete link; `get_audit_log(org_id)` — return all audit entries; `list(page, per_page, filters)` — paginated list with name/type/status filters
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 7.2 Re-export `OrganizationService` from `backend/app/services/__init__.py`
    - _Requirements: 1.1_

- [x] 8. TimelineService and InteractionService
  - [x] 8.1 Create `backend/app/services/timeline_service.py` with `TimelineService` class: `get_timeline(target_type, target_id, entry_type=None, subtype=None, date_from=None, date_to=None)` — query `InteractionAssociation` for matching interactions, query `TaskAssociation` for matching tasks, apply filters, sort combined list descending by occurred_at/due_date, return unified list of timeline entry dicts with fields: entry_type, subtype, date, body_or_title, source, hubspot_engagement_id
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - [x] 8.2 Create `backend/app/services/interaction_service.py` with `InteractionService` class: `create(data)` — validate body non-empty and at least one association target (raise `InteractionValidationError`), create `Interaction` and `InteractionAssociation` records; `update(interaction_id, data)` — update body/occurred_at/interaction_type; `delete(interaction_id)` — delete with cascade; `get(interaction_id)` — return with associations; `list(filters, page, per_page)` — paginated, filterable by target; `get_timeline(target_type, target_id, filters)` — delegate to `TimelineService`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_
  - [x] 8.3 Re-export `TimelineService` and `InteractionService` from `backend/app/services/__init__.py`
    - _Requirements: 4.1_

- [x] 9. TaskService
  - [x] 9.1 Create `backend/app/services/task_service.py` with `TaskService` class: `create(data)` — validate title non-empty (raise `TaskValidationError`), create `Task` and `TaskAssociation` records; `update(task_id, data)` — update fields; `complete(task_id)` — set status=completed, completion_timestamp=now; `delete(task_id)` — delete with cascade; `get(task_id)` — return with overdue check applied; `list(filters, page, per_page)` — paginated, filterable by status/priority/due_date_range/target; `mark_overdue_if_needed(task)` — if due_date < now and status=open, set status=overdue (called on every read); `get_overdue_tasks()` — return all tasks where due_date < now and status=open
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6_
  - [x] 9.2 Re-export `TaskService` from `backend/app/services/__init__.py`
    - _Requirements: 3.1_

- [x] 10. Organization, Interaction, and Task Controllers
  - [x] 10.1 Create `backend/app/controllers/organization_controller.py` as Flask Blueprint (`organization_bp`, prefix `/api/organizations`) with `@handle_errors` decorator on all routes: `GET /` list (paginated, filterable); `POST /` create; `GET /<id>` detail; `PUT /<id>` update; `DELETE /<id>` soft-delete; `GET /<id>/audit-log` audit log; `POST /<id>/links/properties` link property; `DELETE /<id>/links/properties/<link_id>` remove property link; `POST /<id>/links/owners` link owner; `DELETE /<id>/links/owners/<link_id>` remove owner link
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 10.2 Create `backend/app/controllers/interaction_controller.py` as Flask Blueprint (`interaction_bp`, prefix `/api/interactions`) with `@handle_errors` on all routes: `GET /` list; `POST /` create; `GET /<id>` detail; `PUT /<id>` update; `DELETE /<id>` delete; also register `GET /api/leads/<lead_id>/timeline` and `GET /api/organizations/<org_id>/timeline` timeline endpoints
    - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.4_
  - [x] 10.3 Create `backend/app/controllers/task_controller.py` as Flask Blueprint (`task_bp`, prefix `/api/tasks`) with `@handle_errors` on all routes: `GET /` list; `POST /` create; `GET /<id>` detail; `PUT /<id>` update; `DELETE /<id>` delete; `POST /<id>/complete` mark completed
    - _Requirements: 3.1, 3.2, 3.3, 3.5_
  - [x] 10.4 Register `organization_bp`, `interaction_bp`, and `task_bp` in `backend/app/__init__.py` with correct URL prefixes
    - _Requirements: 1.1, 2.1, 3.1_


- [x] 11. HubSpotClientService
  - [x] 11.1 Create `backend/app/services/hubspot_client_service.py` with `HubSpotClientService` class: constructor decrypts Fernet-encrypted token from `HubSpotConfig` using `HUBSPOT_ENCRYPTION_KEY` env var; `_get(path, params)` — execute GET with Bearer token, raise `HubSpotAuthenticationError` on 401/403, `HubSpotRateLimitError` on 429, `ExternalServiceError` on 5xx or timeout >30s; `enforce_get_only(method)` — raise `HubSpotReadOnlyViolation` if method is not GET; `fetch_all_deals()` — cursor-based pagination via `after` param, yield one record at a time; `fetch_all_contacts()`, `fetch_all_companies()`, `fetch_all_engagements()` — same pattern; `test_connection()` — call `/account-info/v3/details`, return `{success, account_name, portal_id}`; `encrypt_token(raw_token)` — static method to Fernet-encrypt a raw token for storage
    - _Requirements: 6.2, 6.3, 6.4, 7.8, 19.1, 19.2, 19.3_
  - [x] 11.2 Re-export `HubSpotClientService` from `backend/app/services/__init__.py`
    - _Requirements: 6.1_

- [x] 12. HubSpotImportService
  - [x] 12.1 Create `backend/app/services/hubspot_import_service.py` with `HubSpotImportService` class: `start_import(object_types)` — create `HubSpotImportRun` records (one per object type), dispatch Celery tasks (`import_hubspot_deals.delay(run_id)` etc.), return list of run records; `get_run_status(run_id)` — return `HubSpotImportRun` or raise `ImportRunNotFoundError`; `list_runs(page, per_page)` — paginated list newest first; `get_config()` — return current `HubSpotConfig` with token masked; `save_config(token, portal_id)` — encrypt token with Fernet, upsert `HubSpotConfig`
    - _Requirements: 6.1, 6.2, 7.6, 7.7, 7.8, 20.5_
  - [x] 12.2 Re-export `HubSpotImportService` from `backend/app/services/__init__.py`
    - _Requirements: 7.8_

- [x] 13. Celery Import Tasks
  - [x] 13.1 Create `backend/app/tasks/hubspot_tasks.py` with all nine Celery tasks registered on the existing Celery app: `import_hubspot_deals(run_id)` — paginate via `HubSpotClientService.fetch_all_deals()`, UPSERT each record into `hubspot_deals` using PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` (preserve `first_imported_at`, update `last_updated_at` and `raw_payload`), update `ImportRun` counts after each page, handle non-fatal record errors (log + increment error_count + continue), handle fatal errors (mark run failed + stop); `import_hubspot_contacts(run_id)`, `import_hubspot_companies(run_id)`, `import_hubspot_engagements(run_id)` — same pattern for respective tables; `run_hubspot_matching(run_id)` — process all unmatched records via `HubSpotMatcherService`; `convert_hubspot_activities(run_id)` — process all unconverted engagements via `HubSpotActivityConverterService`, skip if hubspot_engagement_id already exists; `extract_hubspot_signals(run_id)` — process all hubspot_import Interactions via `HubSpotSignalExtractorService`, apply suppression flags; `rescore_leads_after_import(user_id)` — call `LeadScoringEngine.bulk_rescore()` with signals; `generate_backup_export()` — serialize all raw HubSpot tables to JSON with import metadata, write to temp file
    - _Requirements: 7.6, 7.7, 7.8, 8.1, 8.2, 8.3, 8.4, 8.6, 9.4, 20.2, 20.3_
  - [x] 13.2 Ensure `import_hubspot_deals`, `import_hubspot_contacts`, `import_hubspot_companies`, `import_hubspot_engagements` use `bind=True, max_retries=3` with exponential backoff for `HubSpotRateLimitError` and `ExternalServiceError`; mark `ImportRun.status='partial'` when some records fail non-fatally
    - _Requirements: 20.2, 20.3_

- [x] 14. HubSpot Controller
  - [x] 14.1 Create `backend/app/controllers/hubspot_controller.py` as Flask Blueprint (`hubspot_bp`, prefix `/api/hubspot`) with `@handle_errors` on all routes: `GET /config` (token masked); `POST /config` (encrypt token before storing); `POST /config/test` (return `{success, account_name, portal_id, error?}`); `POST /import/trigger` (202 response with `{run_id, status: "running"}`); `GET /import/runs` (paginated); `GET /import/runs/<run_id>`; `GET /import/<run_id>/progress` (SSE stream via `EventSource`); `POST /export/backup` (dispatch Celery task, return `{task_id}`); `GET /export/backup/download` (JSON file download); `GET /review-queue` (filterable by type/confidence/page); `POST /review-queue/<match_id>/confirm`; `POST /review-queue/<match_id>/reject`; `POST /review-queue/<match_id>/new-record`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.7, 7.8, 9.1, 9.2, 9.3, 9.4, 9.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 19.4, 20.1_
  - [x] 14.2 Register `hubspot_bp` in `backend/app/__init__.py`
    - _Requirements: 6.1_

- [x] 15. Lead Controller Extensions
  - [x] 15.1 Add six new view endpoints to `backend/app/controllers/lead_controller.py` using `@handle_errors`: `GET /api/leads/views/previously-warm` (leads with PRIOR_WARM_CONVERSATION or APPOINTMENT_OCCURRED signal); `GET /api/leads/views/needs-review` (HubSpot-imported with UNMATCHED confidence or needs_review status); `GET /api/leads/views/follow-up-overdue` (leads with open overdue Task); `GET /api/leads/views/no-next-action` (PRIOR_INTERACTION_EXISTS signal, no open Task, no future Interaction); `GET /api/leads/views/do-not-contact` (suppression_flag=True on Lead or any associated Owner); `GET /api/leads/views/missing-property-match` (HubSpot placeholder properties with no confirmed match)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

- [x] 16. HubSpotMatcherService
  - [x] 16.1 Create `backend/app/services/hubspot_matcher_service.py` with `HubSpotMatcherService` class: `normalize_address(address)` static — strip+uppercase → expand abbreviations as whole-word replacements (ST→STREET, AVE→AVENUE, BLVD→BOULEVARD, DR→DRIVE, RD→ROAD, CT→COURT, LN→LANE, PL→PLACE, HWY→HIGHWAY, PKWY→PARKWAY, CIR→CIRCLE) → remove punctuation [.,#-/]; `normalize_phone(phone)` static — strip all non-digit characters; `normalize_company_name(name)` static — uppercase, strip punctuation, collapse whitespace; `match_deal(deal)` — priority: (1) PIN match→HIGH, (2) normalized address match→MEDIUM, (3) no match→UNMATCHED + create placeholder Lead with source=hubspot_import and status=needs_review; `match_contact(contact)` — priority: (1) email match→HIGH, (2) phone match (digits only)→HIGH, (3) name+property match→MEDIUM, (4) no match→create new Owner; `match_company(company)` — priority: (1) exact normalized name match→MEDIUM, (2) name+deal property match→MEDIUM, (3) no match→create new Organization; `_upsert_match(...)` — create or update `HubSpotMatch` record
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4_
  - [x] 16.2 Re-export `HubSpotMatcherService` from `backend/app/services/__init__.py`
    - _Requirements: 10.1_

- [x] 17. HubSpotActivityConverterService
  - [x] 17.1 Create `backend/app/services/hubspot_activity_converter_service.py` with `HubSpotActivityConverterService` class: `convert_engagement(engagement)` — route to convert_note/convert_call/convert_task based on engagement_type, return None for unrecognized types; `convert_note(engagement)` — create `Interaction(type=note)` with body from HubSpot note body, occurred_at from engagement created-at, source=hubspot_import, hubspot_engagement_id preserved, raw_payload stored; `convert_call(engagement)` — create `Interaction(type=call)` with body from call body or disposition; `convert_task(engagement)` — create `Task` with title from subject, body from task body, due_date from HubSpot due date, status mapped (COMPLETED→completed, all others→open), source=hubspot_import, hubspot_task_id preserved, raw_payload stored; `_resolve_associations(engagement)` — look up confirmed `HubSpotMatch` records for each associated deal/contact/company ID, return list of `{target_type, target_id}` dicts, return empty list if no matches; attach Interaction/Task to all resolved targets; if no associations, set is_orphaned=True; skip if hubspot_engagement_id already exists (idempotent)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 15.1, 15.2, 15.3, 15.4_
  - [x] 17.2 Re-export `HubSpotActivityConverterService` from `backend/app/services/__init__.py`
    - _Requirements: 14.1_

- [x] 18. HubSpotSignalExtractorService
  - [x] 18.1 Create `backend/app/services/hubspot_signal_extractor_service.py` with `HubSpotSignalExtractorService` class: `__init__()` — load signal keyword dictionary from `HubSpotSignalDictionary` table via `_load_dictionary()`; `_load_dictionary()` — query all records, return `{signal_type: [keywords]}` dict; `extract_signals(engagement, lead_id)` — scan engagement body text case-insensitively against all keyword lists, check for overdue task condition for FOLLOW_UP_OVERDUE signal, return list of `HubSpotSignal` records to persist; `apply_suppression(signals)` — for any DO_NOT_CONTACT or WRONG_NUMBER signal, set `suppression_flag=True` on the associated Lead record
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_
  - [x] 18.2 Re-export `HubSpotSignalExtractorService` from `backend/app/services/__init__.py`
    - _Requirements: 16.1_

- [x] 19. LeadScoringEngine Extensions
  - [x] 19.1 Extend `compute_score(lead, weights, signals=None)` in the existing `LeadScoringEngine` service: apply `SIGNAL_ADJUSTMENTS` dict (PRIOR_WARM_CONVERSATION: +15.0, APPOINTMENT_OCCURRED: +20.0, OFFER_PREVIOUSLY_SENT: +10.0, SELLER_SAID_MAYBE_LATER: -5.0, SELLER_NOT_INTERESTED: -40.0, DO_NOT_CONTACT: -50.0, WRONG_NUMBER: -30.0) to base score when signals provided; clamp score to max 10.0 when `lead.suppression_flag=True`; clamp final score to [0.0, 100.0] rounded to 2 decimal places
    - _Requirements: 17.1, 17.2, 17.6_
  - [x] 19.2 Add `compute_recommended_action(signals)` method — determine `recommended_action` from most recently extracted signal using priority: DO_NOT_CONTACT > SELLER_NOT_INTERESTED > SELLER_SAID_MAYBE_LATER > OFFER_PREVIOUSLY_SENT; return None if no applicable signal
    - _Requirements: 17.3, 17.4, 17.5_
  - [x] 19.3 Add `ACTIVE_OUTREACH_THRESHOLD = 30.0` constant; update `bulk_rescore()` to pass signals to `compute_score` for each lead and persist `recommended_action` on the Lead record
    - _Requirements: 17.6, 17.7_


- [x] 20. TypeScript Types and API Service Layer
  - [x] 20.1 Add all new TypeScript interfaces and enums to `frontend/src/types/index.ts`: `Organization`, `OrganizationAuditLog`, `PropertyOrganizationLink`, `OwnerOrganizationLink`, `Interaction`, `InteractionAssociation`, `TimelineEntry`, `Task`, `TaskAssociation`, `HubSpotConfig`, `HubSpotImportRun`, `HubSpotMatch`, `HubSpotSignal`; enums: `OrgType`, `OrgStatus`, `InteractionType`, `InteractionSource`, `TaskStatus`, `TaskPriority`, `MatchConfidence`, `MatchStatus`, `SignalType`, `RecommendedAction`
    - _Requirements: 1.1, 2.1, 3.1, 6.1, 7.1_
  - [x] 20.2 Add HubSpot API methods to `frontend/src/services/api.ts`: `getHubSpotConfig()`, `saveHubSpotConfig(token, portalId)`, `testHubSpotConnection()`, `triggerHubSpotImport(objectTypes?)`, `listImportRuns(page, perPage)`, `getImportRun(runId)`, `getReviewQueue(filters)`, `confirmMatch(matchId, internalRecordId?)`, `rejectMatch(matchId, internalRecordId)`, `markMatchAsNewRecord(matchId)`, `triggerBackupExport()`, `downloadBackupExport()`
    - _Requirements: 6.1, 7.7, 9.1, 13.3_
  - [x] 20.3 Add Organization, Interaction, Task, and Timeline API methods to `frontend/src/services/api.ts`: `listOrganizations(filters)`, `createOrganization(data)`, `getOrganization(id)`, `updateOrganization(id, data)`, `deleteOrganization(id)`, `getOrganizationAuditLog(id)`, `linkOrganizationToProperty(orgId, propertyId, role)`, `linkOrganizationToOwner(orgId, ownerId, role)`, `createInteraction(data)`, `updateInteraction(id, data)`, `deleteInteraction(id)`, `createTask(data)`, `updateTask(id, data)`, `deleteTask(id)`, `completeTask(id)`, `getLeadTimeline(leadId, filters?)`, `getOrganizationTimeline(orgId, filters?)`
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 5.1, 5.2_
  - [x] 20.4 Add Lead view API methods to `frontend/src/services/api.ts`: `getPreviouslyWarmLeads()`, `getNeedsReviewLeads()`, `getFollowUpOverdueLeads()`, `getNoNextActionLeads()`, `getDoNotContactLeads()`, `getMissingPropertyMatchLeads()`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

- [x] 21. HubSpotImportArea Component
  - [x] 21.1 Create `frontend/src/components/HubSpotImportArea.tsx` with: connection config form (masked token input, save button, test connection button showing account name/portal ID on success or error message on failure); "Read-Only Mode" badge always visible when configured; import trigger panel (object type checkboxes for deals/contacts/companies/engagements, "Start Import" button); SSE-driven progress bar per object type via `EventSource` on `/api/hubspot/import/{run_id}/progress`; import history table (HubSpotImportRun list with status badge, counts, timestamps); backup export section ("Generate Backup" button, "Download" button disabled until backup exists); Review Queue badge showing pending count; React Query for import run list and config
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.7, 7.8, 9.1, 9.4, 9.5, 13.6, 19.4, 20.1_

- [x] 22. ReviewQueue Component
  - [x] 22.1 Create `frontend/src/components/ReviewQueue.tsx` with: filterable table by object type (deal/contact/company) and confidence (MEDIUM/LOW/UNMATCHED); each row shows HubSpot record summary, proposed internal match, color-coded confidence badge, matching criteria label; side-by-side field comparison panel for conflict detection (existing vs incoming values); action buttons per row: "Confirm", "Reject + Re-link" (opens record search), "Mark as New Record"; pending count badge in navigation; optimistic UI updates with React Query invalidation on action
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 22.4_

- [x] 23. TimelinePanel Component
  - [x] 23.1 Create `frontend/src/components/TimelinePanel.tsx` with props `targetType: 'lead' | 'organization'` and `targetId: number`; chronological list of `TimelineEntry` items (Interactions and Tasks merged); filter bar for entry type, subtype, and date range; each entry shows type icon, subtype label, formatted occurred_at or due_date, body/title text, source badge (manual/hubspot_import), HubSpot engagement ID if applicable; empty state message when no entries; React Query with `queryKey: ['timeline', targetType, targetId]`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 24. NoteTaskForm Component
  - [x] 24.1 Create `frontend/src/components/NoteTaskForm.tsx` with: tab switcher "Note" | "Task"; Note tab: body textarea (required), submit button; Task tab: title input (required), body textarea (optional), MUI DatePicker for due date, priority selector (high/medium/low); auto-populates association from page context props (`targetType`, `targetId`) — no re-selection needed; on success: invalidate `['timeline', targetType, targetId]` React Query cache so timeline refreshes without page reload; inline validation error display below each invalid field; loading state on submit button
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 25. HubSpotLeadViews Component
  - [x] 25.1 Create `frontend/src/components/HubSpotLeadViews.tsx` with six pre-built filtered views reusing the existing lead list table component: "Previously Warm Leads" at `/leads/views/previously-warm`; "Needs Review" at `/leads/views/needs-review`; "Follow-Up Overdue" at `/leads/views/follow-up-overdue`; "No Current Next Action" at `/leads/views/no-next-action`; "Do Not Contact" at `/leads/views/do-not-contact`; "Missing Property Match" at `/leads/views/missing-property-match`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_
  - [x] 25.2 Add routes for all six lead views, HubSpotImportArea (`/import/hubspot`), and ReviewQueue (`/import/hubspot/review-queue`) to `frontend/src/App.tsx`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_
  - [x] 25.3 Add navigation links for HubSpot Import Area and the six lead views to the sidebar in `frontend/src/App.tsx`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

- [x] 26. Property-Based Test: Address Normalization (Properties 1 and 2)
  - [x] 26.1 Write property test for address normalization idempotent (Property 1) in `backend/tests/test_hubspot_address_normalization.py`; strategy: `st.text(min_size=0, max_size=200)`; property: `normalize_address(normalize_address(s)) == normalize_address(s)` for all strings s; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 1: Address normalization is idempotent`
    - **Validates: Requirements 10.5**
  - [x] 26.2 Write property test for address normalization deterministic (Property 2) in `backend/tests/test_hubspot_address_normalization.py`; strategy: `st.text(min_size=0, max_size=200)`; property: calling `normalize_address(s)` three times always returns the same result; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 2: Address normalization is deterministic`
    - **Validates: Requirements 10.5**

- [x] 27. Property-Based Test: Validation (Property 3)
  - [x] 27.1 Write property test for empty/whitespace inputs rejected (Property 3) in `backend/tests/test_hubspot_validation.py`; strategy: `st.text(alphabet=st.characters(whitelist_categories=('Zs', 'Cc')), min_size=0, max_size=50)` for whitespace-only strings; property: submitting whitespace-only string as Organization name raises `OrganizationValidationError` and no record is created; same for Interaction body (`InteractionValidationError`) and Task title (`TaskValidationError`); `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 3: Empty and whitespace inputs are always rejected`
    - **Validates: Requirements 1.5, 2.3, 3.3**

- [x] 28. Property-Based Test: Import Upsert (Property 4)
  - [x] 28.1 Write property test for duplicate prevention upsert by HubSpot ID (Property 4) in `backend/tests/test_hubspot_import_upsert.py`; strategy: `st.text(min_size=1, max_size=50)` for hubspot_id, `st.integers(min_value=2, max_value=10)` for import_count; property: importing the same hubspot_id N times results in exactly one row; `first_imported_at` equals timestamp of first import; `last_updated_at` equals timestamp of most recent import; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 4: Duplicate prevention — upsert by HubSpot ID`
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6**

- [x] 29. Property-Based Test: Matching Confidence (Properties 5 and 6)
  - [x] 29.1 Write property test for deal match confidence deterministic (Property 5) in `backend/tests/test_hubspot_matching.py`; strategy: generate HubSpotDeal-like dicts with varying PIN and address fields; generate Lead-like records with matching/non-matching PIN and address; property: PIN match→confidence=HIGH; address-only match→confidence=MEDIUM; no match→confidence=UNMATCHED; same input always produces same confidence; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 5: Match confidence assignment is deterministic`
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
  - [x] 29.2 Write property test for contact match confidence (Property 6) in `backend/tests/test_hubspot_matching.py`; strategy: generate HubSpotContact-like dicts with varying email/phone/name fields; generate Lead-like records; property: email match→HIGH; phone match (digits only)→HIGH; name+property match only→MEDIUM; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 6: Contact match confidence assignment`
    - **Validates: Requirements 11.1, 11.2, 11.3**

- [x] 30. Property-Based Test: Timeline (Properties 7 and 8)
  - [x] 30.1 Write property test for timeline always reverse chronological (Property 7) in `backend/tests/test_hubspot_timeline.py`; strategy: generate lists of Interaction and Task dicts with random `occurred_at`/`due_date` datetimes; property: `TimelineService.get_timeline()` result is sorted in descending order by date with no gaps or reorderings; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 7: Timeline is always reverse chronological`
    - **Validates: Requirements 4.1, 2.6**
  - [x] 30.2 Write property test for timeline completeness (Property 8) in `backend/tests/test_hubspot_timeline.py`; strategy: `st.integers(min_value=0, max_value=20)` for K (manual records) and M (hubspot records); property: timeline for a target with K manually-created and M HubSpot-imported records returns exactly K+M entries with no filters applied; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 8: Timeline completeness`
    - **Validates: Requirements 4.2**

- [x] 31. Property-Based Test: Overdue Detection (Property 9)
  - [x] 31.1 Write property test for overdue detection invariant (Property 9) in `backend/tests/test_hubspot_overdue.py`; strategy: generate Task dicts with `due_date` strictly in the past and `status=open`; property: every query response for such a task reflects `status=overdue` regardless of when the task was created or last updated; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 9: Overdue detection invariant`
    - **Validates: Requirements 3.6, 15.4**

- [x] 32. Property-Based Test: Source Round-Trip (Property 10)
  - [x] 32.1 Write property test for HubSpot source fields preserved on round-trip (Property 10) in `backend/tests/test_hubspot_source_roundtrip.py`; strategy: generate valid `hubspot_engagement_id` strings and arbitrary JSON `raw_payload` dicts; property: Interaction or Task created with `source=hubspot_import` has non-null `hubspot_engagement_id` and `raw_payload` equal to provided values after persist-and-retrieve cycle; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 10: HubSpot source fields are preserved on round-trip`
    - **Validates: Requirements 2.5, 3.4**

- [x] 33. Property-Based Test: Scoring (Properties 11, 12, and 13)
  - [x] 33.1 Write property test for suppressed lead score always below threshold (Property 11) in `backend/tests/test_hubspot_scoring.py`; strategy: generate Lead-like objects with `suppression_flag=True`; generate arbitrary `ScoringWeights` and signal lists; property: `LeadScoringEngine.compute_score(lead, weights, signals)` ≤ 10.0 for all suppressed leads; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 11: Suppressed lead score is always below threshold`
    - **Validates: Requirements 17.6**
  - [x] 33.2 Write property test for signal score adjustments monotone (Property 12) in `backend/tests/test_hubspot_scoring.py`; strategy: generate Lead-like objects with `suppression_flag=False`; generate base signal lists without positive/negative signals; generate positive signals (PRIOR_WARM_CONVERSATION, APPOINTMENT_OCCURRED) and negative signals (SELLER_NOT_INTERESTED, DO_NOT_CONTACT); property: adding a positive-adjustment signal produces score ≥ score without it; adding a negative-adjustment signal produces score ≤ score without it; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 12: Signal score adjustments are monotone`
    - **Validates: Requirements 17.1, 17.2**
  - [x] 33.3 Write property test for scoring weights sum to 1.0 (Property 13) in `backend/tests/test_hubspot_scoring.py`; strategy: generate valid `ScoringWeights` objects or query from database; property: `property_characteristics_weight + data_completeness_weight + owner_situation_weight + location_desirability_weight` is within 0.01 of 1.0 for every ScoringWeights record; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 13: Scoring weights always sum to 1.0`
    - **Validates: Requirements 17.1, 17.2, 17.6**

- [x] 34. Property-Based Test: Signal Extraction (Properties 14 and 15)
  - [x] 34.1 Write property test for signal extraction keyword match case-insensitive (Property 14) in `backend/tests/test_hubspot_signal_extraction.py`; strategy: for each signal type, draw a keyword from the dictionary; generate random case variations (upper/lower/mixed); embed keyword in a larger text body; property: `HubSpotSignalExtractorService.extract_signals()` includes a signal of the expected type for any body text containing a keyword in any case variation; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 14: Signal extraction keyword match is case-insensitive`
    - **Validates: Requirements 16.1, 16.2**
  - [x] 34.2 Write property test for suppression flag set for DO_NOT_CONTACT/WRONG_NUMBER (Property 15) in `backend/tests/test_hubspot_signal_extraction.py`; strategy: generate Lead records; generate HubSpotSignal lists containing DO_NOT_CONTACT or WRONG_NUMBER signals; property: after `apply_suppression(signals)`, the associated Lead's `suppression_flag` is True; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals`
    - **Validates: Requirements 16.3**

- [x] 35. Property-Based Test: Review Queue (Property 16)
  - [x] 35.1 Write property test for review queue membership invariant (Property 16) in `backend/tests/test_hubspot_review_queue.py`; strategy: generate `HubSpotMatch` records with varying confidence (MEDIUM/LOW/UNMATCHED/HIGH) and status (pending/confirmed/rejected); property: matches with confidence MEDIUM/LOW/UNMATCHED and status=pending appear in review queue; matches with status=confirmed or status=rejected do not appear in review queue; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 16: Review queue membership invariant`
    - **Validates: Requirements 13.1, 13.4, 13.5**

- [x] 36. Property-Based Test: Read-Only Enforcement (Property 17)
  - [x] 36.1 Write property test for HubSpot client enforces GET-only (Property 17) in `backend/tests/test_hubspot_readonly.py`; strategy: `st.sampled_from(['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'post', 'put', 'delete'])`; property: calling `HubSpotClientService.enforce_get_only(method)` with any non-GET method raises `HubSpotReadOnlyViolation` and does not execute any HTTP call; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only`
    - **Validates: Requirements 19.1, 19.2, 19.3**

- [x] 37. Property-Based Test: Import Run Counts (Property 18)
  - [x] 37.1 Write property test for import run counts accurate (Property 18) in `backend/tests/test_hubspot_import_counts.py`; strategy: `st.integers(min_value=1, max_value=50)` for N (total records), `st.integers(min_value=0)` constrained to ≤ N for E (error records); property: after processing N records where E fail with non-fatal errors, `HubSpotImportRun` satisfies `total_fetched = created_count + updated_count + skipped_count + error_count` and `error_count = E`; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 18: Import run counts are accurate`
    - **Validates: Requirements 20.2, 20.4**

- [x] 38. Property-Based Test: No Overwrite of Protected Fields (Property 19)
  - [x] 38.1 Write property test for no overwrite of protected fields without confirmation (Property 19) in `backend/tests/test_hubspot_no_overwrite.py`; strategy: generate Lead records with existing `county_assessor_pin`, `property_street`, `lead_score`, `source`; generate HubSpot import data that would conflict with those fields; generate unconfirmed `HubSpotMatch` records; property: after running the import/matching pipeline with an unconfirmed match, the Lead's protected fields remain unchanged; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation`
    - **Validates: Requirements 22.1, 22.2, 22.3**

- [x] 39. Property-Based Test: Audit Log Growth (Property 20)
  - [x] 39.1 Write property test for organization audit log grows on every mutation (Property 20) in `backend/tests/test_hubspot_audit_log.py`; strategy: `st.integers(min_value=1, max_value=20)` for N (number of create/update operations); generate valid organization data dicts for each operation; property: after N create/update operations on an Organization, the audit log for that organization contains at least N entries; `@settings(max_examples=100)`; tag: `# Feature: hubspot-crm-migration, Property 20: Organization audit log grows on every mutation`
    - **Validates: Requirements 1.4**

- [x] 40. Frontend Tests
  - [x] 40.1 Create `frontend/src/components/HubSpotImportArea.test.tsx` covering: config save (renders token input, calls `saveHubSpotConfig` on submit, shows success state); test connection (calls `testHubSpotConnection`, displays account name/portal ID on success, displays error on failure); trigger import (calls `triggerHubSpotImport` with selected object types, shows progress indicator); progress display (SSE events update progress bar per object type); import history (renders HubSpotImportRun list with status badges and counts); Read-Only Mode badge visible when config present; Review Queue badge shows pending count
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 7.7, 7.8, 19.4, 20.1_
  - [x] 40.2 Create `frontend/src/components/ReviewQueue.test.tsx` covering: filter by object type renders only matching rows; filter by confidence renders only matching rows; confirm action calls `confirmMatch` and removes item; reject + re-link opens record search and calls `rejectMatch`; mark as new record calls `markMatchAsNewRecord` and removes item; side-by-side comparison displays existing vs incoming values; pending count badge reflects correct count
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_
  - [x] 40.3 Create `frontend/src/components/TimelinePanel.test.tsx` covering: renders entries in reverse chronological order; renders both Interaction and Task entries with correct icons and labels; empty state displays message when no entries; filter by entry type shows only matching entries; filter by date range shows only entries within range; source badge shows manual or hubspot_import correctly; HubSpot engagement ID displayed when present
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - [x] 40.4 Create `frontend/src/components/NoteTaskForm.test.tsx` covering: tab switcher switches between Note and Task forms; note validation shows inline error when body is empty on submit; task validation shows inline error when title is empty on submit; successful note submission calls `createInteraction` and invalidates timeline cache; successful task submission calls `createTask` and invalidates timeline cache; auto-association uses context props without showing selector; loading state on submit button during request
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - [x] 40.5 Create `frontend/src/components/HubSpotLeadViews.test.tsx` covering: Previously Warm Leads view calls `getPreviouslyWarmLeads` and renders lead list; Needs Review view calls `getNeedsReviewLeads`; Follow-Up Overdue view calls `getFollowUpOverdueLeads`; No Current Next Action view calls `getNoNextActionLeads`; Do Not Contact view calls `getDoNotContactLeads`; Missing Property Match view calls `getMissingPropertyMatchLeads`; each view renders with correct page title/label
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

- [x] 41. Environment Configuration and Integration Wiring
  - [x] 41.1 Add `HUBSPOT_ENCRYPTION_KEY` to `backend/.env.example` with a placeholder value and a comment explaining it must be a valid 32-byte URL-safe base64-encoded Fernet key; document how to generate one: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    - _Requirements: 6.2_
  - [x] 41.2 Verify all new Blueprints (`hubspot_bp`, `organization_bp`, `interaction_bp`, `task_bp`) are registered in `backend/app/__init__.py` with correct URL prefixes; verify all new models are imported in `backend/app/models/__init__.py`; verify all new services are importable from `backend/app/services/__init__.py`; verify Celery tasks in `backend/app/tasks/hubspot_tasks.py` are imported in `backend/celery_worker.py`
    - _Requirements: 1.1, 2.1, 3.1, 6.1, 7.8_
  - [x] 41.3 Run `cd backend && pytest tests/ -v --tb=short` and confirm all new property-based and unit tests pass with no regressions in existing tests
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 6.1, 7.1, 10.1, 13.1, 14.1, 16.1, 17.1, 18.1, 19.1, 22.1_
  - [x] 41.4 Run `cd frontend && npm test` and confirm all new frontend component tests pass with no regressions in existing tests
    - _Requirements: 5.1, 13.1, 18.1_

## Notes

- Requirement 21 (Mobile Quick-Add Workflow) is explicitly deferred and out of scope for this implementation plan.
- Requirement 23 (HubSpot Write-Back) is explicitly deferred and out of scope for this implementation plan.
- The Alembic migration (Task 4) must be applied before any end-to-end testing of services or controllers that touch the database.
- All HubSpot API calls are strictly GET-only; the `enforce_get_only` guard in `HubSpotClientService` provides defense-in-depth against accidental write-back.
- The `HUBSPOT_ENCRYPTION_KEY` environment variable must be set before running any code that reads or writes `HubSpotConfig`; the Fernet key must be exactly 32 bytes URL-safe base64-encoded.
- Property-based tests (Tasks 26–39) use SQLite in-memory database via the existing `conftest.py` pattern; HubSpot API calls are mocked via `unittest.mock.patch` on `HubSpotClientService._get`.
- The signal keyword dictionary is seeded at migration time but can be updated at runtime without a code deployment (Requirement 16.6).
- Frontend SSE progress streaming uses the browser's native `EventSource` API; no additional library is required.
