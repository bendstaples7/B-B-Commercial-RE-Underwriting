# Consolidation Roadmap

Follow-up work from the [architecture audit](ARCHITECTURE.md). Each item is a **separate PR** — do not batch unrelated refactors.

## PR 1 — This branch (merge first)

**Theme:** Stop duplication from growing; remove dead code; fix two backend correctness issues.

- [x] `docs/ARCHITECTURE.md` canonical registry
- [x] Cursor rules + `consolidation-check` skill
- [x] `scripts/check_duplication.py` + CI + pre-pr-check hook
- [x] PR template consolidation checklist
- [x] Delete legacy UI: `LeadCommandCenter`, `PropertyDetailPage`, `HubSpotLeadViews`, `TimelinePanel`
- [x] Remove dead API clients: `leadViewService`, `timelineService`
- [x] Fix timeline route collision → `GET /api/leads/:id/interaction-timeline`
- [x] Stop `DeterministicScoringEngine` writing `leads.lead_score`
- [x] Activity logging UX: `LogActivityModal`, contact method fields, ULCC wiring

## PR 2 — Unify queue activity logging

**Theme:** One logging UX everywhere (fixes “multiple log call buttons” in queues).

- [ ] Shared `useQueueActions` or navigate to `/leads/:id?log=note|call|email`
- [ ] Remove `window.prompt` and empty-note `callLogService` calls from queue row actions
- [ ] Deduplicate `TodaysActionQueue` vs `HomePage` embedded copy
- [ ] Extract `SuppressLeadDialog` (shared by 3+ queues)

**Test plan:** Each queue’s row actions open modal or deep-link; no silent empty API logs.

## PR 3 — ULCC structure + micro-utils

**Theme:** Readability without behavior change.

- [ ] Extract tab panels to `frontend/src/components/lead-detail/`
- [ ] Extract `PropertySidebar` + sidebar helpers
- [ ] `utils/formatters.ts` — `formatDate`, `humanize`, shared `ACTION_LABELS`
- [ ] Move `ALL_LEAD_STATUSES` next to `LEAD_STATUS_LABELS` (single source)

## PR 4 — Retire property views API

**Theme:** One queue backend.

- [ ] Deprecate `/api/properties/views/*` (301 or remove after client audit)
- [ ] Align queue filter semantics (`is_warm` vs HubSpot signals, etc.) in `queue_service.py`
- [ ] Document canonical queue definitions in ARCHITECTURE.md

## PR 5 — Split `api.ts`

**Theme:** Mechanical refactor; follow `condoFilterApi.ts` pattern.

- [ ] `commandCenterApi.ts`, `hubspotApi.ts`, `multifamilyApi.ts`, etc.
- [ ] Lower `API_TS_MAX_LINES` in `check_duplication.py` as file shrinks

## PR 6+ — Contract hygiene & backend domain

**Contract hygiene (can be its own PR series):**

- [ ] Marshmallow → OpenAPI → codegen → retire hand-written `types/index.ts` overlap
- [ ] Shared test factories (`tests/factories/lead.py`, `test/mockApiServices.ts`)

**Backend domain (staged, higher risk):**

- [ ] Decide canonical scoring engine long-term (A/B from audit); extract shared rule helpers
- [ ] `ActionEngineService.explain_recommended_action` — remove controller mirror
- [ ] Shared `handle_errors` in `app/controllers/decorators.py`
- [ ] Single activity store (Interaction model) with unified HubSpot import
- [ ] Task model collapse (`LeadTask` → `Task`) or formalized sync layer

## How to use this doc

1. Pick the next unchecked PR section.
2. Run the `consolidation-check` skill before coding.
3. Check off items when merged to `main`.
4. Update [ARCHITECTURE.md](ARCHITECTURE.md) if canonical ownership changes.
