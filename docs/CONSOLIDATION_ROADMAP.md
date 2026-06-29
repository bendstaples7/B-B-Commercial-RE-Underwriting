# Consolidation Roadmap

Follow-up work from the [architecture audit](ARCHITECTURE.md). Prefer **one focused PR per item** — batch only when items are tightly coupled (see PR 2–4 note below).

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

## PR 2–4 — Queues, ULCC extraction, retire property views (combined in PR #68)

**Theme:** One logging UX in queues; slimmer ULCC; canonical queue API only. Shipped as one PR because queue logging, ULCC extraction, and view retirement were coordinated in a single user-facing migration.

- [x] Navigate queue row actions to `/leads/:id?log=note|call|email`; ULCC opens `LogActivityModal`
- [x] Remove `window.prompt` and direct `callLogService` calls from queue row actions
- [x] Deduplicate `TodaysActionQueue` vs `HomePage` embedded copy
- [x] Extract `SuppressLeadDialog` (shared by 3 queues)
- [x] Extract `LeadDetailTabPanel` + `PropertySidebar` to `frontend/src/components/lead-detail/`
- [x] `utils/formatters.ts` + `constants/scoringRecommendedActions.ts`
- [x] `ALL_LEAD_STATUSES` derived from `LEAD_STATUS_LABELS`
- [x] `/api/properties/views/*` → 301 redirect to `/api/queues/*`

## PR 5 — Split `api.ts`

**Theme:** Mechanical refactor; follow `condoFilterApi.ts` pattern.

- [ ] `commandCenterApi.ts`, `hubspotApi.ts`, `multifamilyApi.ts`, etc.
- [ ] Lower `API_TS_MAX_LINES` in `check_duplication.py` as file shrinks

## PR 6+ — Contract hygiene & backend domain

**Contract hygiene (can be its own PR series):**

- [ ] Marshmallow → OpenAPI → codegen → retire hand-written `types/index.ts` overlap
- [ ] Shared test factories (`tests/factories/lead.py`, `test/mockApiServices.ts`)

**Backend domain (staged, higher risk):**

- [x] Decide canonical scoring engine long-term — unified `LeadScoringEngine` (scoring + recommended action)
- [x] Extract shared rule helpers → `scoring_rubric.py`, `enrichment_scoring.py`
- [ ] `ActionEngineService.explain_recommended_action` — remove controller mirror
- [ ] Shared `handle_errors` in `app/controllers/decorators.py`
- [ ] Single activity store (Interaction model) with unified HubSpot import
- [ ] Task model collapse (`LeadTask` → `Task`) or formalized sync layer

## How to use this doc

1. Pick the next unchecked PR section.
2. Run the `consolidation-check` skill before coding.
3. Check off items when merged to `main`.
4. Update [ARCHITECTURE.md](ARCHITECTURE.md) if canonical ownership changes.
