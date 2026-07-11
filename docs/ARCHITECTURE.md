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
| API client pattern | Domain modules like [`condoFilterApi.ts`](../frontend/src/services/condoFilterApi.ts), [`leadApi.ts`](../frontend/src/services/leadApi.ts) | New exports appended to monolithic [`api.ts`](../frontend/src/services/api.ts) |
| Shared formatters | [`helpers.ts`](../frontend/src/utils/helpers.ts) (extend as needed) | Local `formatDate` / `humanize` copies in components |

## Backend

| Domain | Canonical | Do not add |
|--------|-----------|------------|
| Unified scoring + recommended action | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) + [`scoring_rubric.py`](../backend/app/services/scoring_rubric.py) via [`refresh_lead_scoring`](../backend/app/services/lead_refresh.py) | `DeterministicScoringEngine`, `ActionEngineService`, or second writers to `leads.lead_score` / `leads.recommended_action` |
| Live `leads.lead_score` | [`LeadScoringEngine.persist()`](../backend/app/services/lead_scoring_engine.py) — same value as latest `lead_scores.total_score` | Second writer to `leads.lead_score` |
| Per-phone confidence | [`PhoneConfidenceService`](../backend/app/services/phone_confidence_service.py) → `contact_phones.confidence_score` | Parallel phone tracking tables |
| HubSpot contact refresh | [`HubSpotContactSyncService`](../backend/app/services/hubspot_contact_sync_service.py) | Ad-hoc contact API fetch outside enrich/backfill |
| Score history / audit API | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) → `lead_scores` table (append-only) | Separate scoring engine writing different scores |
| Recommended action (live) | [`LeadScoringEngine`](../backend/app/services/lead_scoring_engine.py) → `leads.recommended_action` (same as `lead_scores.recommended_action`) | Parallel action engines or unmapped RA enums |
| Lead timeline (read/write) | [`command_center_controller.py`](../backend/app/controllers/command_center_controller.py) + [`CallLogService`](../backend/app/services/call_log_service.py) → `LeadTimelineEntry` | Duplicate `GET /api/leads/:id/timeline` handlers |
| Interaction timeline (CRM) | `GET /api/leads/:id/interaction-timeline` in [`interaction_controller.py`](../backend/app/controllers/interaction_controller.py) | Overlapping URL with command-center timeline |
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

## Related specs

Feature specs live in [`.kiro/specs/`](../.kiro/specs/). When a spec task says "remove file", deletion is part of **done**, not optional cleanup.
