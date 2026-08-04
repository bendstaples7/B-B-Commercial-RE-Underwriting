---
name: live-ui-visibility
description: >-
  Project binding for live-ui-visibility: authenticated Playwright snapshots,
  DEV Capture FAB, Chromium CDP/session import, Cursor hooks, and CI auth smoke.
  Use on every UI implementation before done/retest claims.
---

# Live-UI visibility (this repo)

Follow the full gate in `~/.agents/skills/live-ui-visibility/SKILL.md`.

## Hard enforcement

- **Hooks:** `.cursor/hooks/live-ui-visibility-*.js` (also registered in user
  `~/.cursor/hooks.json`) — veto blind UI done / invalid `SEEN`
- **Claim guard:** `scripts/live-ui/claim-guard.mjs`
- **CI meta:** `node scripts/check-live-ui-ci-gate.mjs`
- **CI auth smoke:** job `live-ui-auth-smoke` (seed + Flask + preview + snapshot)

## Quick commands

```bash
npm run live-ui:auth-save --prefix frontend

npm run live-ui:snapshot --prefix frontend -- \
  --url /leads/10305 \
  --selector '[data-testid="property-overview-header"]' \
  --label cc-header

npm run live-ui:import-session --prefix frontend -- --cdp http://127.0.0.1:9222
```

DEV UI: floating **Live-UI (dev)** → Export session / Capture header.

`SEEN` must cite `artifacts/live-ui/<file>.png` (Read the PNG before claiming).
