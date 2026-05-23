# Implementation Plan

## Overview

Implement HubSpot webhook sync: a webhook receiver endpoint, Celery processing pipeline, webhook log API, frontend panel, and cleanup job. Reuses existing migration infrastructure, services, and models from the hubspot-crm-migration spec.

## Tasks

- [x] 1. Database Migration — Webhook Tables
  - Create Alembic migration `add_hubspot_webhook_tables` with idempotent `IF NOT EXISTS` DDL for: `hubspot_webhook_logs`, `hubspot_sync_runs`, `hubspot_platform_writes`
  - Add `encrypted_client_secret TEXT` column to `hubspot_config` via `ADD COLUMN IF NOT EXISTS`
  - Create enum type `webhook_log_status_enum` using `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$`
  - Add indexes on `hubspot_webhook_logs(hubspot_object_type, hubspot_object_id)`, `(status)`, and `(received_at)`
  - Implement `downgrade()` with `DROP ... IF EXISTS` for all objects
  - _Requirements: 1, 2, 6, 7_

- [x] 2. SQLAlchemy Models
  - Create `backend/app/models/hubspot_webhook_log.py` — `HubSpotWebhookLog` model with all columns and indexes as specified in the design
  - Create `backend/app/models/hubspot_sync_run.py` — `HubSpotSyncRun` model
  - Create `backend/app/models/hubspot_platform_write.py` — `HubSpotPlatformWrite` model (stub for loop guard)
  - Add `encrypted_client_secret = db.Column(db.Text, nullable=True)` to `backend/app/models/hubspot_config.py`
  - Re-export all new models from `backend/app/models/__init__.py`
  - _Requirements: 1, 2, 6, 7_
  - _Depends on: 1_

- [x] 3. Marshmallow Schemas
  - Add `WebhookLogSchema` to `backend/app/schemas.py` — serializes `HubSpotWebhookLog` (id, hubspot_object_type, hubspot_object_id, event_type, status, error_message, received_at, processed_at)
  - Add `WebhookLogSummarySchema` — serializes the 24-hour summary (processed_count, failed_count, deduplicated_count, last_synced_at)
  - Add `HubSpotConfigUpdateSchema` extension — adds optional `client_secret` field to the existing config save endpoint
  - _Requirements: 7, 10_
  - _Depends on: 2_

- [x] 4. WebhookService
  - Create `backend/app/services/hubspot_webhook_service.py` with `HubSpotWebhookService` class
  - Implement `verify_signature(raw_body, signature_header, timestamp_header)` using HMAC-SHA256 with constant-time comparison (`hmac.compare_digest`) and 5-minute timestamp staleness check
  - Implement `handle_batch(events)` — parse each event, insert `HubSpotWebhookLog` records with `status=pending`, dispatch `process_webhook_event.delay(log_id)` for each
  - Implement `get_log_summary()` — query last 24 hours, return counts by status and most recent `processed_at`
  - Implement `retry_failed_event(log_id)` — reset status to `pending`, re-dispatch to Celery
  - Add `HubSpotWebhookService` to `backend/app/services/__init__.py`
  - _Requirements: 1, 2, 3, 7_
  - _Depends on: 2_

- [x] 5. Celery Processing Pipeline
  - Create `backend/app/tasks/hubspot_webhook_tasks.py`
  - Implement `process_webhook_event(log_id)` — load log, set status=processing; check dedup window via `is_duplicate()`; check loop guard via `is_loop_event()`; dispatch `fetch_and_upsert_record` chain; update log status at each step
  - Implement `fetch_and_upsert_record(object_type, object_id, log_id)` — call `HubSpotClientService` to fetch full record; upsert into the appropriate raw table using existing migration upsert logic; create `HubSpotSyncRun`; chain to `run_incremental_matching`; retry with exponential backoff on API errors (max 3 retries)
  - Implement `run_incremental_matching(object_type, object_id)` — call the appropriate `HubSpotMatcherService` method; only add to Review_Queue if confidence is MEDIUM/UNMATCHED AND no confirmed match exists; chain to `convert_incremental_activity` for engagements
  - Implement `convert_incremental_activity(engagement_id)` — call `HubSpotActivityConverterService`; skip if Interaction/Task already exists with unchanged payload; chain to `extract_incremental_signals`
  - Implement `extract_incremental_signals(engagement_id, lead_id)` — call `HubSpotSignalExtractorService`; chain to `rescore_lead`
  - Implement `rescore_lead(lead_id)` — call `LeadScoringEngine` for a single lead
  - Implement `is_duplicate(object_type, object_id, current_log_id)` helper — query for a newer log for the same object within `DEDUP_WINDOW_SECONDS` (default 60, env-configurable via `HUBSPOT_DEDUP_WINDOW_SECONDS`)
  - Implement `is_loop_event(object_type, object_id)` helper — query `HubSpotPlatformWrite` within `LOOP_GUARD_SECONDS` (default 30, env-configurable via `HUBSPOT_LOOP_GUARD_SECONDS`); always returns False until write-back is enabled
  - _Requirements: 3, 4, 5, 6_
  - _Depends on: 4_

- [x] 6. Webhook Controller
  - Create `backend/app/controllers/hubspot_webhook_controller.py` with `hubspot_webhook_bp` blueprint, URL prefix `/api/hubspot`
  - Implement `POST /api/hubspot/webhook` — read raw body before JSON parsing (required for signature verification); call `HubSpotWebhookService.verify_signature()`; return 401 on failure; call `handle_batch()`; return 200 within 5 seconds
  - Apply a separate rate limit to the webhook endpoint (e.g., 500/minute) distinct from the authenticated API rate limits
  - Register `hubspot_webhook_bp` in `backend/app/__init__.py`
  - _Requirements: 1, 2_
  - _Depends on: 4_

- [x] 7. Webhook Log API Endpoints
  - Add `GET /api/hubspot/webhook-log` to `hubspot_controller.py` — paginated list of `HubSpotWebhookLog` records, filterable by status and object type
  - Add `GET /api/hubspot/webhook-log/summary` — return 24-hour summary via `WebhookService.get_log_summary()`
  - Add `POST /api/hubspot/webhook-log/{log_id}/retry` — call `WebhookService.retry_failed_event(log_id)`; return 404 if log not found; return 400 if log is not in `failed` status
  - Extend `POST /api/hubspot/config` to accept and encrypt an optional `client_secret` field; extend `GET /api/hubspot/config` to return a `has_client_secret` boolean (never the secret value itself)
  - _Requirements: 7, 10_
  - _Depends on: 3, 4_

- [x] 8. HubSpotConfig Client Secret Storage
  - Add `encrypt_client_secret(secret: str) -> str` and `decrypt_client_secret() -> str` methods to `HubSpotClientService` (or a shared crypto utility), using the same Fernet key as the API token
  - Update the config save endpoint handler to encrypt and store `client_secret` when provided
  - Ensure the config GET endpoint never returns the raw or encrypted client secret — only `has_client_secret: bool`
  - Update `WebhookService.verify_signature()` to decrypt and use the stored client secret
  - _Requirements: 2, 10_
  - _Depends on: 4, 7_

- [x] 9. Frontend — WebhookSyncPanel
  - Add TypeScript types to `frontend/src/types/index.ts`: `WebhookLog`, `WebhookLogSummary`
  - Add API service methods to `frontend/src/services/api.ts`: `getWebhookLog`, `getWebhookLogSummary`, `retryWebhookEvent`, `updateHubSpotConfig` (extended to include optional `client_secret`)
  - Create `frontend/src/components/WebhookSyncPanel.tsx` containing: client secret input (write-only; shows "Configured ✓" badge when `has_client_secret` is true), webhook URL display (read-only copyable text field showing `{BASE_URL}/api/hubspot/webhook`), setup instructions section with step-by-step HubSpot UI guide and the list of event types to subscribe to, last Synced timestamp with warning banner when no event received in 24 hours, 24-hour summary counts (processed / failed / deduplicated), webhook log table (paginated, filterable by status) with Retry button on failed rows
  - Integrate `WebhookSyncPanel` as a new tab or section within the existing `HubSpotImportArea` component
  - Wire up React Query hooks: `useQuery` for log and summary; `useMutation` for retry and client secret save
  - _Requirements: 7, 8, 10_
  - _Depends on: 7, 8_

- [x] 10. Webhook Log Cleanup Job
  - Add `purge_old_webhook_logs` Celery task to `hubspot_webhook_tasks.py` — delete `HubSpotWebhookLog` records where `received_at < NOW() - 30 days`
  - Register the task in the Celery beat schedule (run daily at 3 AM)
  - _Requirements: 7_
  - _Depends on: 5_

- [x] 11. End-to-End Integration Test
  - Write a pytest integration test that seeds a `HubSpotConfig` with an encrypted token and client secret, seeds a `HubSpotDeal` and matched `Lead`, POSTs a valid signed `engagement.creation` webhook payload to `/api/hubspot/webhook`, runs the Celery tasks synchronously (using `task.apply()`), and asserts: `HubSpotWebhookLog` status is `processed`, `HubSpotEngagement` record exists, `Interaction` record exists linked to the lead, `HubSpotSyncRun` record exists
  - Write a test for the deduplication path: two events for the same object within 60 seconds → only one `SyncRun` created, the earlier log marked `deduplicated`
  - Write a test for the invalid signature path: POST with wrong signature → 401, no `WebhookLog` created
  - _Requirements: 1, 2, 3, 4, 5_
  - _Depends on: 6, 7, 8, 9, 10_

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3", "4"] },
    { "wave": 4, "tasks": ["5", "6", "7"] },
    { "wave": 5, "tasks": ["8", "10"] },
    { "wave": 6, "tasks": ["9"] },
    { "wave": 7, "tasks": ["11"] }
  ]
}
```

## Notes

- The `/api/hubspot/webhook` endpoint is not protected by user auth middleware — HMAC signature verification is the sole authentication mechanism.
- The `hubspot_platform_writes` table will always be empty until write-back is enabled; the loop guard always returns False in the current implementation.
- HubSpot legacy private apps do not support API-based subscription management — subscriptions must be configured manually in the HubSpot UI.
- All migrations must follow the idempotent pattern (`IF NOT EXISTS`, `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$`) per the migrations steering guide.
