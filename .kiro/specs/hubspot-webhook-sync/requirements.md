# Requirements Document

## Introduction

This feature adds ongoing one-way synchronization from HubSpot to the platform via HubSpot webhooks. After the initial historical migration (covered by the `hubspot-crm-migration` spec), this feature ensures that new and updated records in HubSpot — deals, contacts, companies, notes, calls, and tasks — are automatically reflected in the platform without requiring manual re-imports.

The platform remains the authoritative source of truth. HubSpot pushes change events to a webhook endpoint on the platform, which processes them asynchronously using the existing Celery infrastructure. The matching, deduplication, and signal extraction logic built for the migration is reused here.

**Important constraint**: HubSpot's legacy private apps do not support managing webhook subscriptions via API. Subscriptions must be configured manually in the HubSpot UI (Settings → Development → Legacy Apps → your app → Webhooks tab). The platform therefore does not attempt to register or deactivate subscriptions programmatically — it only receives and processes the events.

This spec assumes the `hubspot-crm-migration` spec has been implemented and the following are already in place: `HubSpotConfig`, `HubSpotDeal/Contact/Company/Engagement` raw tables, `HubSpotMatch`, `HubSpotSignal`, `HubSpotImportRun`, `HubSpotClientService`, `HubSpotMatcherService`, `HubSpotActivityConverterService`, and `HubSpotSignalExtractorService`.

---

## Glossary

- **Webhook_Event**: A JSON payload delivered by HubSpot to the platform's webhook endpoint when a record is created or updated in HubSpot.
- **Webhook_Log**: A platform record capturing the raw payload, processing status, and outcome of each received Webhook_Event.
- **Sync_Run**: A logged execution of webhook event processing, analogous to an Import_Run but triggered by incoming events rather than a manual import.
- **Dedup_Window**: A configurable time window (default: 60 seconds) within which duplicate webhook events for the same HubSpot object ID are collapsed into a single processing job.
- **Loop_Guard**: A mechanism that prevents a record updated by the platform from triggering a webhook that re-processes the same change.
- **Signature_Verification**: Validation that an incoming webhook request was genuinely sent by HubSpot using the HubSpot client secret.

---

## Requirements

### Requirement 1: Webhook Endpoint

**User Story:** As a platform operator, I want the platform to receive HubSpot webhook events at a dedicated endpoint, so that HubSpot can push changes to the platform automatically.

#### Acceptance Criteria

1. THE Platform SHALL expose a POST endpoint at `/api/hubspot/webhook` that accepts HubSpot webhook event payloads.
2. THE Platform SHALL verify the HubSpot webhook signature on every incoming request using the `X-HubSpot-Signature-v3` header and the configured HubSpot client secret; IF signature verification fails, THE Platform SHALL return HTTP 401 and log the failure without processing the payload.
3. THE Platform SHALL return HTTP 200 to HubSpot within 5 seconds of receiving a webhook event, regardless of whether processing has completed; processing SHALL continue asynchronously via Celery after the 200 response is sent.
4. THE Platform SHALL store the raw webhook payload in a Webhook_Log record before dispatching it for processing; IF storage fails, THE Platform SHALL still return HTTP 200 to HubSpot to prevent retries, and SHALL log the storage failure separately.
5. THE Platform SHALL handle HubSpot's batch delivery format, where a single webhook request may contain an array of multiple event objects.
6. IF the webhook endpoint receives a request with a content type other than `application/json`, THE Platform SHALL return HTTP 400 without processing.

---

### Requirement 2: Webhook Signature Verification

**User Story:** As a platform operator, I want all incoming webhook requests to be authenticated, so that the platform cannot be fed fake HubSpot events by a third party.

#### Acceptance Criteria

1. THE Platform SHALL store the HubSpot client secret in encrypted form alongside the existing HubSpot API token in `HubSpotConfig`; the raw client secret SHALL never appear in any API response or log.
2. WHEN verifying a webhook signature, THE Platform SHALL use the HMAC-SHA256 algorithm with the client secret as the key and the raw request body as the message, comparing the result to the `X-HubSpot-Signature-v3` header value.
3. IF the `X-HubSpot-Signature-v3` header is absent, THE Platform SHALL reject the request with HTTP 401.
4. THE Platform SHALL use a constant-time comparison when checking the signature to prevent timing attacks.
5. THE Platform SHALL log every signature verification failure with the source IP address and timestamp, without logging the raw payload.

---

### Requirement 3: Event Deduplication

**User Story:** As a platform operator, I want duplicate webhook events for the same record to be collapsed, so that a burst of HubSpot events does not cause redundant processing.

#### Acceptance Criteria

1. WHEN multiple webhook events arrive for the same HubSpot object ID within the Dedup_Window, THE Platform SHALL process only the most recent event and mark the earlier events as deduplicated in the Webhook_Log.
2. THE Dedup_Window SHALL default to 60 seconds and SHALL be configurable via an environment variable without requiring a code deployment.
3. WHEN an event is deduplicated, THE Platform SHALL record in the Webhook_Log that it was skipped due to deduplication and which event superseded it.
4. THE Platform SHALL NOT deduplicate events across different object types; a deal-updated event and a contact-updated event for records that happen to share the same HubSpot ID SHALL both be processed.

---

### Requirement 4: Incremental Record Processing

**User Story:** As a platform operator, I want each incoming webhook event to trigger a fetch-and-upsert of the affected HubSpot record, so that the platform's raw tables stay current with HubSpot.

#### Acceptance Criteria

1. WHEN a deal-created or deal-updated event is received, THE Platform SHALL fetch the full deal record from the HubSpot API using the deal ID in the event, then upsert it into `hubspot_deals` using the existing duplicate-prevention logic from the migration spec.
2. WHEN a contact-created or contact-updated event is received, THE Platform SHALL fetch the full contact record and upsert it into `hubspot_contacts`.
3. WHEN a company-created or company-updated event is received, THE Platform SHALL fetch the full company record and upsert it into `hubspot_companies`.
4. WHEN an engagement-created or engagement-updated event is received, THE Platform SHALL fetch the full engagement record and upsert it into `hubspot_engagements`.
5. WHEN a record is upserted via webhook, THE Platform SHALL create a Sync_Run record capturing: trigger type (webhook), object type, HubSpot ID, upsert result (created or updated), and timestamp.
6. IF the HubSpot API fetch fails (e.g., rate limit, network error), THE Platform SHALL retry up to 3 times with exponential backoff before marking the Webhook_Log entry as failed; a failed fetch SHALL NOT mark the Webhook_Log entry as successfully processed.

---

### Requirement 5: Incremental Matching and Conversion

**User Story:** As a platform operator, I want newly synced HubSpot records to be automatically matched to internal records and converted to Interactions and Tasks, so that the platform stays current without manual intervention.

#### Acceptance Criteria

1. AFTER a deal record is upserted via webhook, THE Platform SHALL run the existing `HubSpotMatcherService.match_deal()` logic against the updated record and update or create the corresponding `HubSpotMatch`.
2. AFTER a contact record is upserted via webhook, THE Platform SHALL run `HubSpotMatcherService.match_contact()` and update or create the corresponding `HubSpotMatch`.
3. AFTER a company record is upserted via webhook, THE Platform SHALL run `HubSpotMatcherService.match_company()` and update or create the corresponding `HubSpotMatch`.
4. AFTER an engagement record is upserted via webhook, THE Platform SHALL run `HubSpotActivityConverterService` to create or update the corresponding internal Interaction or Task, using the same deduplication logic as the migration (no duplicate Interactions or Tasks for the same HubSpot engagement ID).
5. AFTER engagement conversion, THE Platform SHALL run `HubSpotSignalExtractorService` on the new or updated engagement and update the associated Lead's signals and score.
6. IF matching produces a MEDIUM or UNMATCHED confidence result for a new record, THE Platform SHALL add it to the Review_Queue exactly as the migration does; existing confirmed matches SHALL NOT be re-queued.

---

### Requirement 6: Loop Guard

**User Story:** As a platform operator, I want the platform to detect and suppress webhook events that were triggered by its own write-back operations, so that sync loops cannot occur.

#### Acceptance Criteria

1. WHEN the platform writes a record to HubSpot (via the write-back feature, if enabled), THE Platform SHALL record the HubSpot object type and ID in a `hubspot_platform_writes` table with a timestamp.
2. WHEN a webhook event arrives, THE Platform SHALL check whether the event's HubSpot ID was written by the platform within the last 30 seconds; IF so, THE Platform SHALL mark the Webhook_Log entry as loop-suppressed and skip processing.
3. THE Platform SHALL log every loop-suppressed event with the HubSpot object ID, event type, and suppression reason.
4. THE loop guard window SHALL default to 30 seconds and SHALL be configurable via an environment variable.

> **Note:** Since write-back is deferred, the `hubspot_platform_writes` table will always be empty until write-back is enabled. The loop guard is in place so it works correctly the moment write-back is turned on.

---

### Requirement 7: Webhook Event Log and Monitoring

**User Story:** As a platform user, I want to see a log of recent webhook events and their processing status, so that I can diagnose sync problems without digging through server logs.

#### Acceptance Criteria

1. THE Platform SHALL display a Webhook_Log view in the Import_Area showing the 100 most recent webhook events with: event type, HubSpot object ID, received timestamp, processing status (pending, processing, processed, failed, deduplicated, loop-suppressed), and error message if failed.
2. THE Platform SHALL display a summary count of events by status (processed, failed, deduplicated) for the last 24 hours in the Import_Area.
3. WHEN a webhook event fails processing after all retries, THE Platform SHALL display it prominently in the Import_Area with a "Retry" action that allows the user to manually re-trigger processing.
4. THE Platform SHALL retain Webhook_Log records for 30 days, after which they may be purged by a scheduled cleanup job.
5. THE Platform SHALL display the timestamp of the most recently successfully processed webhook event as a "Last Synced" indicator in the Import_Area.

---

### Requirement 8: Webhook Setup Instructions

**User Story:** As a platform user, I want the platform to show me the webhook URL and setup instructions, so that I can configure the subscription in HubSpot without having to look up the endpoint myself.

#### Acceptance Criteria

1. THE Platform SHALL display the full webhook endpoint URL (`{BASE_URL}/api/hubspot/webhook`) in the Import_Area as a read-only copyable field.
2. THE Platform SHALL display step-by-step instructions in the Import_Area explaining how to configure the webhook subscription in HubSpot (navigate to Settings → Development → Legacy Apps → your app → Webhooks tab, enter the URL, select event types).
3. THE Platform SHALL display the list of event types that should be subscribed to: deal.creation, deal.propertyChange, contact.creation, contact.propertyChange, company.creation, company.propertyChange, engagement.creation, engagement.propertyChange.
4. WHEN no webhook event has been received within the last 24 hours, THE Platform SHALL display a warning in the Import_Area indicating that sync may not be configured or may be stalled.

---

### Requirement 9: Graceful Degradation

**User Story:** As a platform operator, I want the platform to continue functioning normally if HubSpot webhooks stop arriving, so that a HubSpot outage does not break the platform.

#### Acceptance Criteria

1. THE Platform SHALL operate fully without any active HubSpot webhook subscriptions; all core platform features (lead management, scoring, timeline, tasks) SHALL function regardless of webhook status.
2. THE Platform SHALL allow a user to trigger a manual full re-import at any time from the Import_Area, which will catch any changes missed during a webhook outage.
3. IF the Celery worker is unavailable when a webhook event arrives, THE Platform SHALL still store the raw event in the Webhook_Log and process it when the worker becomes available; events SHALL NOT be lost due to worker downtime.

---

### Requirement 10: Configuration and Security

**User Story:** As a platform user, I want webhook configuration to be managed securely within the platform, so that I do not need to handle secrets outside the application.

#### Acceptance Criteria

1. THE Platform SHALL store the HubSpot client secret (used for signature verification) in encrypted form using the same Fernet encryption used for the API token.
2. THE Platform SHALL allow the client secret to be entered and saved from the Import_Area without requiring a server restart.
3. THE Platform SHALL display a "Client secret configured" indicator in the Import_Area when a secret is saved, without revealing the secret value.
4. THE Platform SHALL NOT log the raw webhook payload body at INFO level or above; payload logging SHALL only occur at DEBUG level to prevent sensitive seller data from appearing in production logs.
