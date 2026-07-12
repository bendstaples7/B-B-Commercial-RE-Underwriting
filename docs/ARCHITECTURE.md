# Architecture — Canonical Sources

This document is the single registry of **canonical implementations**. Before adding a component, service, route, or enum, search here and extend the listed file — do not create parallel implementations.

Update this doc when ownership changes.

## Frontend

| Domain | Canonical | Do not add |
|--------|-----------|------------|
| Lead detail page | [`UnifiedLeadCommandCenter.tsx`](../frontend/src/components/UnifiedLeadCommandCenter.tsx) at `/leads/:id` | New detail pages, `PropertyDetailPage`-style layouts |
| Activity logging UI | [`LogActivityModal.tsx`](../frontend/src/components/LogActivityModal.tsx) + [`LogNoteForm`](../frontend/src/components/LogNoteForm.tsx) / [`LogCallForm`](../frontend/src/components/LogCallForm.tsx) / [`LogEmailForm`](../frontend/src/components/LogEmailForm.tsx) | Inline log forms, `window.prompt`, direct `callLogService` from queue row actions |
| Activity timeline (UI) | [`LeadTimeline.tsx`](../frontend/src/components/LeadTimeline.tsx) via `commandCenterService.getTimeline` | New timeline components on alternate APIs |
| Work queues (UI) | [`*Queue.tsx`](../frontend/src/components/) components + `queueService` | `HubSpotLeadViews`, embedded queue copies in pages |
| Queue bulk actions / multi-select | [`queueBulkActions.tsx`](../frontend/src/components/queueBulkActions.tsx) + [`useQueueSelection.ts`](../frontend/src/hooks/useQueueSelection.ts) + [`QueueTable.tsx`](../frontend/src/components/QueueTable.tsx) | Per-queue parallel bulk handlers or selection state |
| Queue pagination | [`pagination.ts`](../frontend/src/utils/pagination.ts) | Local page math in queue components |
| Queue context banners | [`deriveQueueContext.ts`](../frontend/src/utils/deriveQueueContext.ts) | Inline banner logic in detail pages |
| Lead status UI | [`LeadStatusSelector.tsx`](../frontend/src/components/LeadStatusSelector.tsx) | Inline status Select + reason fields |
| Motivation score (product) | [`MotivationSignalService`](../backend/app/services/motivation_signal_service.py) → `lead.motivation_score` + MotivationSignalsPanel | Second motivation formula; treating HubSpot SIGNAL_ADJUSTMENTS as motivation_score |
| Owners / phones / emails (CC + queues) | [`Contact`](../backend/app/models/contact.py) + [`PropertyContact`](../backend/app/models/property_contact.py) via [`ContactService`](../backend/app/services/contact_service.py); CC phone **display** reads `contacts[].phones` (full phone DTO via [`PhoneConfidenceService.serialize_contact_phone`](../backend/app/services/phone_confidence_service.py)); top-level `phones[]` is merge/sort for outreach + no-contact fallback; UI via [`PhoneRow.tsx`](../frontend/src/components/PhoneRow.tsx) | Dual Info-tab flat owner/phone editor; queue rows reading only `owner_first_name`/`phone_1` when contacts exist; skinny `{id,value,label}` phone dumps; stripping confidence in sidebar |
| Organizations / LLC filings | [`Organization`](../backend/app/models/organization.py) + [`OrganizationParty`](../backend/app/models/organization_party.py) via [`OrganizationService`](../backend/app/services/organization_service.py) / [`EntityResolutionService`](../backend/app/services/entity_resolution_service.py); `org_type` includes `nonprofit` | Scraping Illinois SOS; parallel LLC tables; putting managers only on flat lead fields |
| LLC → person resolution (IL) | [`EntityResolutionService`](../backend/app/services/entity_resolution_service.py): institutional name / IRS EO BMF ([`irs_eo.py`](../backend/app/services/entity_lookup/irs_eo.py)) nonprofit research first, then free [`IllinoisSosBulkProvider`](../backend/app/services/entity_lookup/ilsos_bulk.py); cold-mail gate via [`entity_owner_policy`](../backend/app/services/entity_owner_policy.py) + [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) | Interactive ILSOS scraping; Google/Serp as primary nonprofit classifier; parallel mail-skip engines; Cook County plugins owning SOS/manager lookup; calling skip-trace vendors from entity resolution |
| Skip-trace handoff | [`SkipTraceEnqueue`](../backend/app/services/skip_trace_enqueue.py) → v1 manual `skip_trace_owner` task / `needs_skip_trace` | Calling a skip-trace API from EntityResolutionService; duplicate enqueue paths |
| Mail readiness | `recommended_action == 'mail_ready'` + [`MailQueueItem`](../backend/app/models/mail_queue_item.py) / Ready to Mail; staged → pending follow-up task (`due_date` null) via [`mail_task_lifecycle_service`](../backend/app/services/mail_task_lifecycle_service.py); send sets due +7d | Competing `up_next_to_mail` as mailer status; score dampening while queued |
| Today's Action (due work) | [`QueueService.get_todays_action`](../backend/app/services/queue_service.py) — open tasks with `due_date <= today` (sorted by `lead_score`); not bare `follow_up_now` | RA-only membership; mixing proposal queues into due work |
| API client pattern | Domain modules like [`condoFilterApi.ts`](../frontend/src/services/condoFilterApi.ts), [`leadApi.ts`](../frontend/src/services/leadApi.ts) | New exports appended to monolithic [`api.ts`](../frontend/src/services/api.ts) |
| Shared formatters | [`helpers.ts`](../frontend/src/utils/helpers.ts) (extend as needed) | Local `formatDate` / `humanize` copies in components |

## Backend

| Domain | Canonical | Do not add |
|--------|-----------|------------|
| Unified scoring + recommended action | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) + [`scoring_rubric.py`](../backend/app/services/scoring_rubric.py) via [`refresh_lead_scoring`](../backend/app/services/lead_refresh.py) | `DeterministicScoringEngine`, `ActionEngineService`, or second writers to `leads.lead_score` / `leads.recommended_action` |
| Pipeline status | `lead.lead_status` via lead_status_service / LeadStatusSelector | Treating `hubspot_deal_stage` as editable pipeline status (it is a read-only HubSpot mirror) |
| Live `leads.lead_score` | [`LeadScoringEngine.persist()`](../backend/app/services/lead_scoring_engine.py) — same value as latest `lead_scores.total_score` | Second writer to `leads.lead_score` |
| Per-phone confidence | [`PhoneConfidenceService`](../backend/app/services/phone_confidence_service.py) → `contact_phones.confidence_score`; all contact phone API dumps use `serialize_contact_phone` | Parallel phone tracking tables; hand-built phone dicts that omit `confidence_score` |
| HubSpot contact refresh | [`HubSpotContactSyncService`](../backend/app/services/hubspot_contact_sync_service.py) | Ad-hoc contact API fetch outside enrich/backfill |
| Score history / audit API | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) → `lead_scores` table (append-only) | Separate scoring engine writing different scores |
| Recommended action (live) | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) → `leads.recommended_action` (same as `lead_scores.recommended_action`) | Parallel action engines or unmapped RA enums |
| Lead timeline (read/write) | [`command_center_controller.py`](../backend/app/controllers/command_center_controller.py) + [`CallLogService`](../backend/app/services/call_log_service.py) → `LeadTimelineEntry` | Duplicate `GET /api/leads/:id/timeline` handlers; injecting Interaction rows into CC |
| HubSpot activity → CC timeline | [`HubSpotTimelineImportService`](../backend/app/services/hubspot_timeline_import_service.py) → `LeadTimelineEntry` | Writing HubSpot activities only to `Interaction` for product UI |
| Lead open tasks (CC) | [`LeadTask`](../backend/app/models/lead_task.py) via [`LeadTaskService`](../backend/app/services/lead_task_service.py) (incl. `hubspot_task_id`) | UNION of CRM `tasks` into CC `open_tasks` |
| Interaction timeline (CRM) | `GET /api/leads/:id/interaction-timeline` in [`interaction_controller.py`](../backend/app/controllers/interaction_controller.py) — **frozen for CC/product** | Overlapping URL with command-center timeline; new product consumers |
| Work queues (API) | [`queue_service.py`](../backend/app/services/queue_service.py) at `/api/queues/*` | `/api/properties/views/*` (301 → queues; legacy only) |
| Lead list/detail API | [`property_controller.py`](../backend/app/controllers/property_controller.py) at `/api/properties/*` | Logic in stub [`lead_controller.py`](../backend/app/controllers/lead_controller.py) |
| Controller error handling | Shared decorator in `app/controllers/decorators.py` (target) | Per-file `handle_errors` copies |
| Unified score + action refresh | [`refresh_lead_scoring()`](../backend/app/services/lead_refresh.py) | Ad-hoc score-only or action-only refresh at mutation sites |
| One-off scripts | Thin wrappers calling service layer (e.g. [`rescore_all.py`](../backend/scripts/rescore_all.py)) | Inlined SQL/field lists duplicating services |

## API routes (quick reference)

| Concern | Route | Handler |
|---------|-------|---------|
| Lead detail (command center) | `GET /api/leads/:id/command-center` | command center controller |
| Lead activity timeline | `GET /api/leads/:id/timeline` | command center → `{ entries, total, page }` |
| CRM interaction timeline | `GET /api/leads/:id/interaction-timeline` | interaction controller → `{ timeline }` |
| Log note / call | `POST /api/leads/:id/notes`, `/calls` | CallLogService |
| Work queues | `GET /api/queues/*` | queue controller |
| Lead score history | `GET /api/lead-scores/:id` | lead score controller (LeadScoringEngine) |

## Migration rules

1. **Extend or delete** — replacing behavior means deleting the old file in the same PR (or a tracked follow-up within one release).
2. **One writer per column** — only one code path updates persisted derived fields (`lead_score`, `recommended_action`).
3. **Stubs are temporary** — re-export shims (`LeadDetailPage`, `lead_controller`) must not outlive one release; track removal in PR description.

## Known dual-path follow-ups

Active gaps where product UI can miss data that exists on a parallel path (fix in separate PRs; do not expand these paths):

1. **HubSpot activity → CC timeline** — live sync still writes `Interaction` via `HubSpotActivityConverterService`; docs/canonical import is `HubSpotTimelineImportService` → `LeadTimelineEntry`. CC timeline does not UNION Interactions.
2. **Queue task membership vs CC `open_tasks`** — Today’s Action / overdue still EXISTS against CRM `tasks`; CC open tasks are `LeadTask` only. Mirror gaps show due work with an empty Open Tasks panel.
3. **Flat owner/phone on All Properties / marketing** — queues enrich via contacts; list/marketing UIs still lean on flat `owner_*` / `phone_*`.
4. **`up_next_to_mail` vs `mail_ready` + `MailQueueItem`** — legacy flag still OR’d into awaiting-mail / lifecycle for uncleared rows.
5. **Follow-Up Overdue membership** — still mixes `follow_up_now` RA + CRM tasks, unlike Today’s Action (due `LeadTask` only).

## Related specs

Feature specs live in [`.kiro/specs/`](../.kiro/specs/). When a spec task says "remove file", deletion is part of **done**, not optional cleanup.
