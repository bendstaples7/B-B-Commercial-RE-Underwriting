# Requirements Document

## Introduction

The platform currently operates 7 work queues in the Actionable Lead Command Center that function as a cold-caller CRM workflow. These queues were originally designed around HubSpot CRM signals and are populated exclusively by HubSpot-sourced leads. DuPage County leads (68,565 records) are invisible in all queues despite being fully ingested, scored, and stored in the same leads table.

This feature makes all 7 queues source-agnostic. Every lead in the platform — regardless of whether it originated from HubSpot CRM or a DuPage County data source (foreclosure, long_owned, absentee_owner, tax_distress, manual_distress) — must be visible in the appropriate queue so that a cold caller's full workload is consolidated in one place. The queues must evaluate leads on the basis of universal lead model fields (`lead_status`, `recommended_action`, `is_warm`, `review_required`, `has_property_match`, open tasks) rather than HubSpot-specific join paths.

Two supporting changes are also included: the ingestion pipeline must correctly set `has_property_match` and `review_required` on DuPage leads at import time so those leads surface in the correct queues, and the sidebar "Properties" section header must navigate to `/properties` when clicked rather than only toggling the collapse.

---

## Glossary

- **Lead**: A record in the `leads` table (SQLAlchemy model `Property`, aliased as `Lead`) representing a property owner who is a potential motivated seller. May originate from HubSpot CRM or any DuPage County ingestion source.
- **Queue**: One of the 7 named views in the Actionable Lead Command Center that surfaces leads matching specific criteria. Implemented in `QueueService` (`backend/app/services/queue_service.py`).
- **QueueService**: The backend service class that computes badge counts and paginated results for all 7 queues.
- **Work_Queue**: Synonym for Queue, used in requirement text when referring to the UI concept.
- **LeadTask**: A CRM-native task record in the `lead_tasks` table associated to a Lead via `lead_id`.
- **Task**: A task record in the `tasks` table, typically imported from HubSpot or created via task associations.
- **TaskAssociation**: A join record in the `task_associations` table linking a Task to a target entity (target_type='lead', target_id=Lead.id).
- **Open_Task**: A LeadTask or Task whose `status` is `'open'` or `'overdue'`.
- **Overdue_Task**: An Open_Task whose `due_date` is strictly before today's date.
- **HubSpotSignal**: A record in the `hubspot_signals` table representing a CRM event signal (e.g., `PRIOR_WARM_CONVERSATION`, `APPOINTMENT_OCCURRED`) associated with a Lead.
- **DuPage_Lead**: A Lead whose `source_type` is one of `foreclosure`, `long_owned`, `absentee_owner`, `tax_distress`, or `manual_distress`.
- **HubSpot_Lead**: A Lead whose `source_type` is null (imported via HubSpot sync or Google Sheets).
- **Lead_Ingestion_Service**: The backend service (`LeadIngestionService`) that transforms raw source data into Lead records during import runs.
- **Cold_Caller**: A business development representative who works through the queues daily as their primary interface for outreach.
- **Lead_Status**: The `lead_status` enum column on the Lead model. Valid values: `new`, `active`, `follow_up`, `nurture`, `under_contract`, `closed`, `suppressed`, `do_not_contact`.
- **Recommended_Action**: The `recommended_action` enum column on the Lead model. Valid values: `enrich_data`, `resolve_match`, `analyze_property`, `follow_up_now`, `ready_for_outreach`, `add_contact_info`, `create_task`, `nurture`, `suppress`, `do_not_contact`.
- **is_warm**: A boolean column on the Lead model. When `true`, indicates that the lead has had a prior warm interaction regardless of source. For HubSpot leads, set during sync when a `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED` HubSpotSignal is present. For DuPage leads, set manually or via future enrichment.
- **review_required**: A boolean column on the Lead model. When `true`, the lead appears in the Needs Review queue.
- **review_reason**: A string column on the Lead model describing why `review_required` was set.
- **has_property_match**: A boolean column on the Lead model. When `false`, indicates the lead lacks a verified property record match and appears in the Missing Property Match queue.
- **county_assessor_pin**: The DuPage County parcel identification number on the Lead model. A null value means no parcel has been matched.
- **Badge_Count**: The integer shown next to a queue name in the sidebar, computed by `QueueService.get_counts()`.
- **NAV_SECTIONS**: The static navigation structure in `App.tsx` that defines the sidebar layout including section headers and queue items.
- **Properties_Section**: The "Properties" top-level entry in `NAV_SECTIONS` with `path: '/properties'`. Currently clicking this header only toggles the sidebar collapse; it does not navigate.

---

## Requirements

### Requirement 1: No Next Action Queue — Source-Agnostic Criteria

**User Story:** As a Cold_Caller, I want the No Next Action queue to surface every unworked lead with no open task, regardless of source, so that fresh DuPage leads appear in my queue the moment they are ingested.

#### Acceptance Criteria

1. WHEN the QueueService computes the No Next Action queue, THE QueueService SHALL include every Lead whose `lead_status` is in `('new', 'active')` AND whose `recommended_action` is in `(null, 'create_task', 'ready_for_outreach', 'add_contact_info')` AND that has no Open_Task (no open or overdue LeadTask and no open or overdue Task via direct `lead_id` or TaskAssociation).
2. WHEN the QueueService returns No Next Action results, THE QueueService SHALL sort results by `lead_score` descending as the primary sort key.
3. THE QueueService SHALL NOT restrict the No Next Action queue to any specific `source_type` value; HubSpot_Leads and DuPage_Leads with qualifying `lead_status` and `recommended_action` values SHALL both be included.
4. IF a Lead's `recommended_action` is `'follow_up_now'`, `'enrich_data'`, `'resolve_match'`, `'analyze_property'`, `'nurture'`, `'suppress'`, or `'do_not_contact'`, THEN THE QueueService SHALL exclude that Lead from the No Next Action queue regardless of `lead_status`. A Lead with `recommended_action = null` SHALL be included, consistent with criterion 1.
5. WHEN the QueueService computes the No Next Action badge count, THE QueueService SHALL apply the same filter criteria as the paginated results so that the badge count matches the total row count.

---

### Requirement 2: Today's Action Queue — Source-Agnostic Criteria

**User Story:** As a Cold_Caller, I want the Today's Action queue to show me every lead that needs attention today — whether that urgency comes from a HubSpot task, a CRM-native task, or a lead status — so that I work from one list regardless of source.

#### Acceptance Criteria

1. WHEN the QueueService computes the Today's Action queue, THE QueueService SHALL include every Lead that satisfies at least one of the following conditions: (a) the Lead's `lead_status` is in `('active', 'follow_up')` AND has an Open_Task with `due_date` on or before today; (b) the Lead has a Task (via TaskAssociation or direct `lead_id`) whose `status` is in `('open', 'overdue')` and whose `due_date` is on or before today; (c) the Lead's `lead_status` is in `('active', 'follow_up')` AND `recommended_action` is `'follow_up_now'`.
2. THE QueueService SHALL NOT require a Lead to have a HubSpotSignal or a non-null `source_type` to appear in the Today's Action queue; task-based and status-based conditions SHALL apply identically to all leads regardless of source.
3. WHEN the QueueService computes the Today's Action badge count, THE QueueService SHALL apply the same filter criteria as the paginated results so that the badge count matches the total row count.

---

### Requirement 3: Follow-Up Overdue Queue — Source-Agnostic Criteria

**User Story:** As a Cold_Caller, I want the Follow-Up Overdue queue to include any lead where I'm past due — whether overdue on a CRM task, a HubSpot task, or just haven't contacted the lead in over a week — so that nothing slips regardless of how the lead entered the system.

#### Acceptance Criteria

1. WHEN the QueueService computes the Follow-Up Overdue queue, THE QueueService SHALL include every Lead that satisfies at least one of the following conditions: (a) the Lead has an Overdue_Task (a LeadTask with `status = 'open'` and `due_date` before today); (b) the Lead has a Task (via TaskAssociation or direct `lead_id`) whose `status` is in `('open', 'overdue')` and whose `due_date` is strictly before today; (c) the Lead's `recommended_action` is `'follow_up_now'` AND (`last_contact_date` is more than 7 calendar days before today OR `last_contact_date` is null).
2. THE QueueService SHALL NOT restrict the Follow-Up Overdue queue to any `lead_status` value; a Lead with any `lead_status` value SHALL be included if it satisfies condition (c) of criterion 1.
3. THE QueueService SHALL NOT require a HubSpotSignal or non-null `source_type` for any condition in the Follow-Up Overdue queue.
4. WHEN the QueueService computes the Follow-Up Overdue badge count, THE QueueService SHALL apply the same filter criteria as the paginated results.

---

### Requirement 4: Previously Warm Queue — Source-Agnostic via `is_warm`

**User Story:** As a Cold_Caller, I want the Previously Warm queue to include any lead I've had a warm prior conversation with, whether that warmth was detected via HubSpot signals or set directly on the lead, so that I never lose track of a hot prospect regardless of source.

#### Acceptance Criteria

1. WHEN the QueueService computes the Previously Warm queue, THE QueueService SHALL include every Lead whose `is_warm` column is `true`.
2. THE QueueService SHALL NOT query the `hubspot_signals` table as part of the Previously Warm queue filter; the `is_warm` column on the Lead is the sole criterion for Previously Warm queue inclusion. Queries to `hubspot_signals` for other non-warmth purposes during queue computation are permitted.
3. WHEN the HubSpot sync or import process processes a Lead and finds a HubSpotSignal of type `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED` for that Lead, THE Platform SHALL set `is_warm = true` on the Lead record so that the Lead appears in the Previously Warm queue via the `is_warm` criterion.
4. THE Platform SHALL allow `is_warm` to be set to `true` on any Lead regardless of `source_type`, including DuPage_Leads updated manually or through future enrichment workflows.
5. WHEN the QueueService computes the Previously Warm badge count, THE QueueService SHALL apply the same filter criteria as the paginated results.

---

### Requirement 5: Needs Review Queue — Automatic Flagging on DuPage Ingestion

**User Story:** As a Cold_Caller, I want the Needs Review queue to surface DuPage leads that are missing critical contact or property data so that a researcher can complete the record before I waste time on an uncallable lead.

#### Acceptance Criteria

1. WHEN the QueueService computes the Needs Review queue, THE QueueService SHALL include every Lead whose `review_required` column is `true`, regardless of `source_type`.
2. WHEN the Lead_Ingestion_Service creates a new DuPage_Lead and that Lead has `phone_1` null or empty AND `email_1` null or empty AND `county_assessor_pin` null or empty, THEN THE Lead_Ingestion_Service SHALL set `review_required = true` and `review_reason = 'Missing phone, email, and county PIN'` on that Lead record.
3. WHEN the Lead_Ingestion_Service creates a new DuPage_Lead that has all three critical fields (`phone_1`, `email_1`, and `county_assessor_pin`) populated, or that is missing only one or two of those fields but has at least one populated, THE Lead_Ingestion_Service SHALL NOT set `review_required = true` based on data-completeness alone; normal skip-trace and enrichment flags apply instead.
4. IF a DuPage_Lead already has `review_required = true` set from a prior ingestion run and a subsequent update to that Lead results in all three critical fields (`phone_1`, `email_1`, and `county_assessor_pin`) being populated and non-empty, THEN THE Lead_Ingestion_Service SHALL set `review_required = false` and `review_reason = null` on that Lead record. IF `review_required = true` and at least one of the three critical fields remains null or empty after the update, THEN THE Lead_Ingestion_Service SHALL leave `review_required` and `review_reason` unchanged.
5. WHEN the QueueService computes the Needs Review badge count, THE QueueService SHALL apply the same filter criteria as the paginated results.

---

### Requirement 6: Missing Property Match Queue — Correct Flagging on DuPage Ingestion

**User Story:** As a Cold_Caller, I want the Missing Property Match queue to include DuPage leads without a verified parcel match so that a researcher can look up the county PIN and complete the record.

#### Acceptance Criteria

1. WHEN the QueueService computes the Missing Property Match queue, THE QueueService SHALL include every Lead whose `has_property_match` is `false` AND that has no open LeadTask with `task_type = 'research_missing_pin'`.
2. WHEN the Lead_Ingestion_Service creates a new DuPage_Lead and GIS enrichment does not find a matching parcel (i.e., the GIS connector was invoked but returns no result for the Lead's address and PIN), THE Lead_Ingestion_Service SHALL set `has_property_match = false` on that Lead record.
3. WHEN the Lead_Ingestion_Service creates a new DuPage_Lead, a GIS lookup was attempted, and `county_assessor_pin` is still null after that lookup, THE Lead_Ingestion_Service SHALL set `has_property_match = false` on that Lead record. IF GIS enrichment was not attempted (e.g., no GIS connector is configured for the market), THE Lead_Ingestion_Service SHALL NOT set `has_property_match = false` solely on the basis that no GIS lookup occurred.
4. WHEN a GIS enrichment lookup succeeds and sets `has_property_match = true` on a Lead during ingestion, THE Lead_Ingestion_Service SHALL NOT override that value to `false` based on any other criterion, including a null `county_assessor_pin` or a subsequent failed lookup in the same run.
5. WHEN the QueueService computes the Missing Property Match badge count, THE QueueService SHALL apply the same filter criteria as the paginated results.

---

### Requirement 7: Do Not Contact Queue — No Change Required

**User Story:** As a Cold_Caller, I want the Do Not Contact queue to continue working as it does today for all sources.

#### Acceptance Criteria

1. THE QueueService SHALL include every Lead whose `lead_status` is `'do_not_contact'` in the Do Not Contact queue, regardless of `source_type`.
2. THE QueueService SHALL NOT require any changes to the Do Not Contact queue filter; the existing implementation is already source-agnostic.

---

### Requirement 8: Leads May Appear in Multiple Queues

**User Story:** As a Cold_Caller, I want to understand that a DuPage lead missing critical data may appear in both Needs Review and Missing Property Match simultaneously so that both problems are visible and neither is hidden.

#### Acceptance Criteria

1. THE QueueService SHALL allow a single Lead to appear in both the Needs Review queue and the Missing Property Match queue simultaneously if it satisfies the criteria for both; mutual exclusion is not required.
2. THE QueueService SHALL allow a single Lead to appear in both the No Next Action queue and the Needs Review queue simultaneously if it satisfies the criteria for both.

---

### Requirement 9: HubSpot Sync — Set `is_warm` During Signal Import

**User Story:** As a developer, I want the HubSpot sync process to write `is_warm = true` on leads with warm HubSpot signals so that the Previously Warm queue works without joining to the `hubspot_signals` table at query time.

#### Acceptance Criteria

1. WHEN a HubSpot import or sync run processes a Lead and a HubSpotSignal of type `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED` is associated with that Lead, THE Platform SHALL set `is_warm = true` on the Lead record at the time the signal is persisted or detected.
2. WHEN a HubSpot import or sync run processes a Lead and no HubSpotSignal of type `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED` exists for that Lead, THE Platform SHALL leave the Lead's `is_warm` value unchanged, including when other HubSpotSignal types (such as form submissions or email opens) are present.
3. THE Platform SHALL NOT set `is_warm = false` on a Lead that already has `is_warm = true` during a HubSpot sync, even if the corresponding HubSpotSignal is no longer present; warmth is a one-way flag.

---

### Requirement 10: Sidebar — Properties Label Navigates to `/properties`

**User Story:** As a Cold_Caller, I want clicking the "Properties" label text in the sidebar to take me to the full lead list at `/properties`, so that I can browse all leads without having to find a sub-item.

#### Acceptance Criteria

1. WHEN a user clicks the label text of the "Properties" section header in the sidebar, THE Platform SHALL navigate to `/properties`. WHEN a user clicks the expand/collapse icon (chevron) of the "Properties" section header, THE Platform SHALL toggle the section's expand/collapse state only and SHALL NOT navigate to `/properties`. The label text and the expand/collapse icon are separate click targets on the same header row.
2. THE `/properties` route SHALL render the full lead list (`PropertyListPage` / `LeadListRoute`), which is the primary browsing interface for all leads.
3. THE Platform SHALL NOT change the navigation behavior of any other section header (e.g., "Analysis") as a result of this change.

---

### Requirement 11: Urgent Queues Take Priority Over No Next Action

**User Story:** As a Cold_Caller, I want urgent queues (Today's Action, Follow-Up Overdue) to take priority over holding queues (No Next Action) so that I am not distracted by the same lead appearing in both a high-urgency queue and a low-urgency queue simultaneously.

#### Acceptance Criteria

1. IF a Lead appears in the Today's Action queue (has an open task due today or `recommended_action = 'follow_up_now'` with active/follow_up status), THEN THE QueueService SHALL NOT also include that Lead in the No Next Action queue.
2. IF a Lead appears in the Follow-Up Overdue queue (has an overdue task or overdue follow-up condition), THEN THE QueueService SHALL NOT also include that Lead in the No Next Action queue.
3. WHEN a Lead has an Open_Task, THE QueueService No Next Action filter SHALL exclude that Lead because the No Next Action criteria require the absence of any Open_Task.
4. THE QueueService SHALL allow a single Lead to appear in both the Today's Action queue and the Follow-Up Overdue queue simultaneously if it satisfies the criteria for both; no mutual exclusion is applied between urgent queues.

---

### Requirement 12: Badge Counts Reflect Source-Agnostic Criteria

**User Story:** As a Cold_Caller, I want the badge counts shown next to each queue name in the sidebar to accurately reflect the number of leads I will see when I open that queue, so that I can prioritize my day at a glance.

#### Acceptance Criteria

1. WHEN the QueueService computes `get_counts()`, THE QueueService SHALL compute each badge count using the same filter logic as the corresponding paginated `get_*` method so that the count is not artificially understated by HubSpot-only predicates.
2. THE QueueService `get_counts()` method SHALL return counts for all 7 queues in a single call: `todays_action`, `previously_warm`, `follow_up_overdue`, `no_next_action`, `needs_review`, `do_not_contact`, and `missing_property_match`.
3. WHEN `owner_user_id` is set on the QueueService instance, THE QueueService SHALL scope all badge counts and paginated results to leads owned by that user, regardless of `source_type`.
4. WHEN `owner_user_id` is null (admin view), THE QueueService SHALL include all leads in all badge counts and paginated results regardless of `source_type`, with no owner-scoping filter applied.
