# Live-UI tooling

Authenticated visibility for agents (skill `live-ui-visibility`).

| Script | Purpose |
|--------|---------|
| `auth-save.mjs` | Login via `BB_E2E_*` → `artifacts/auth/session-export.json` + storageState |
| `import-session.mjs` | Import from CDP / export JSON / raw JWT |
| `snapshot.mjs` | Screenshot + metrics for a real app URL |
| `claim-guard.mjs` | Single choke point: valid SEEN proof (hooks + CI) |
| `ci_seed_auth_lead.py` | CI user + lead seed for auth smoke |
| `vite-plugin.mjs` | DEV middleware for Capture FAB |
| `lib.mjs` | Shared helpers |

CI meta: `scripts/check-live-ui-ci-gate.mjs`  
CI job: `live-ui-auth-smoke` in `.github/workflows/ci.yml`

Never commit `artifacts/auth/` (JWTs).
