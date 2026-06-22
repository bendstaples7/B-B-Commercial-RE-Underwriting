# Deployment Runbook

This document describes the process for deploying the B&B Real Estate Analyzer to
the production VPS. All steps are automated by the GitHub Actions deploy workflow
(`.github/workflows/deploy.yml`), which calls `scripts/deploy.sh` on the VPS over
SSH.

---

## Overview

Deployments trigger automatically when a pull request to `main` passes CI and is
merged. They can also be triggered manually from the GitHub Actions UI
(**Actions → Deploy → Run workflow**).

The deploy script (`scripts/deploy.sh`) performs these steps in order:

1. Pre-deploy health checks (disk space, memory, service status)
2. Pre-deploy database backup
3. Pull the target commit from Git
4. Install Python dependencies (`pip install -r backend/requirements.txt`)
5. Install the pre-built frontend dist (built on the CI runner to avoid VPS OOM)
6. **Apply database migrations** — `flask db upgrade`
7. Reload Gunicorn (zero-downtime graceful reload via `SIGHUP`)
8. Ensure async stack is healthy (Redis, Celery worker, Celery Beat)
9. Post-deploy HubSpot sync (`scripts/post_deploy_sync.py`)

If any step fails, the deploy script aborts immediately and automatically rolls
back to the previous commit.

---

## Async stack prerequisite (existing VPSes)

PR #57+ requires Redis, Celery, and expanded deploy-user sudoers. **Before the
first deploy** after merging async-stack changes, run this **once as root** on
the VPS:

```bash
cd /home/deploy/app
git fetch origin main && git pull origin main
sudo bash scripts/vps-setup/migrate-async-stack.sh
```

Verify:

```bash
sudo -u deploy sudo -n -l /usr/local/sbin/bootstrap-async-stack
systemctl is-active redis-server celery celery-beat
```

### Optional: automatic migration on deploy

Add GitHub secret **`VPS_ROOT_SSH_KEY`** (private key for `root@VPS_HOST`). When
the deploy workflow detects an un-provisioned async stack, it will run
`migrate-async-stack.sh` as root before continuing.

When `deploy.sh` gains **new sudo commands**, re-run on the VPS as root:

```bash
sudo bash /home/deploy/app/scripts/vps-setup/11-sudoers-deploy.sh
```

---

## CI gates (prevent deploy surprises)

| Check | When | What it catches |
|-------|------|----------------|
| `deploy-contract` | Every PR | `deploy.sh` / sudoers drift, shell syntax errors |
| `vps-readiness` | PRs touching deploy infra | VPS not migrated before merge |
| `vps-smoke-test` | Every push to `main` | VPS drift between deploys |
| `Ensure VPS readiness` | Deploy workflow | Blocks deploy; auto-migrates if `VPS_ROOT_SSH_KEY` set |

---

## Schema Step

**The only schema step required for any deployment is:**

```bash
flask db upgrade
```

That is it. No `psql`, no raw SQL files, no manual SQL statements.

The command runs automatically during every deploy (step 6 above). It is a no-op
when the database is already at the current head revision.

---

## What `flask db upgrade` does

- Reads the Alembic migration chain from `backend/alembic_migrations/`
- Determines which revisions have not yet been applied to the database
- Applies each pending revision in dependency order
- Records the new head revision in the `alembic_version` table
- Exits with status code 0 on success, non-zero on any failure

All migrations are idempotent (`IF NOT EXISTS` / `EXCEPTION WHEN duplicate_object`),
so re-running after a partial failure is safe and requires no manual intervention.

---

## Files that are NOT part of the deployment schema

The files in `backend/migrations/` are **historical reference only** and are never
read, applied, or depended on during deployment:

- `backend/migrations/001_create_schema.sql`
- `backend/migrations/002_lead_management.sql`
- `backend/migrations/003_add_lead_category.sql`

See `backend/migrations/README.md` for details. The Alembic chain in
`backend/alembic_migrations/` is the single authoritative schema source.

---

## Triggering a Deploy

### Automatic (normal workflow)

1. Open a pull request against `main`
2. CI runs and must pass (tests, lint, migration smoke test, deploy contract)
3. If the PR changes deploy infra, `vps-readiness` must pass on the live VPS
4. Merge the PR — the deploy workflow triggers automatically

### Manual (emergency / after workflow file change)

1. Go to **Actions → Deploy → Run workflow** in the GitHub UI
2. Optionally enter a specific commit SHA to deploy (leave blank for `main` HEAD)
3. Click **Run workflow**

> Use the manual trigger when the deploy workflow itself was changed in the merged
> PR — GitHub skips the automatic `workflow_run` trigger in that case.

---

## Rollback

The deploy script automatically rolls back on failure. To manually roll back after
a bad deploy:

```bash
ssh deploy@<VPS_HOST>
# Roll back to the previous commit (HEAD~1):
bash /home/deploy/deploy.sh <PREVIOUS_SHA>
```

Or use the `rollback.log` to find the previous SHA:

```bash
cat /home/deploy/rollback.log
```

---

## Monitoring a Deploy

Watch the deploy logs in real time from the GitHub Actions UI, or SSH to the VPS
and tail the Gunicorn journal:

```bash
ssh deploy@<VPS_HOST>
journalctl -u gunicorn -f
```

---

## Required GitHub Secrets

See `docs/deployment/github-secrets.md` for the full list and setup instructions.

| Secret | Purpose |
|--------|---------|
| `VPS_SSH_KEY` | Private SSH key for the `deploy` user |
| `VPS_USER` | `deploy` |
| `VPS_HOST` | VPS public IP address |
| `VPS_HOST_KEY` | VPS host key for known_hosts |
| `VPS_SUBDOMAIN` | DuckDNS subdomain prefix (e.g. `bbanalyzer`) |
| `DATABASE_URL` | PostgreSQL connection string — used by `flask db upgrade` |
| `VPS_ROOT_SSH_KEY` | Optional — root SSH key for auto-migrate on deploy |

---

## First-Time / Fresh Environment Setup

For provisioning a brand-new environment from scratch, see the VPS setup scripts
in `scripts/vps-setup/` and the VPS configuration reference in `docs/vps-config.md`.

The schema step for a fresh environment is the same single command:

```bash
flask db upgrade
```

Run from `/home/deploy/app/backend/` with `FLASK_ENV=production` set. This creates
the complete schema from scratch — no additional SQL files or manual steps needed.
