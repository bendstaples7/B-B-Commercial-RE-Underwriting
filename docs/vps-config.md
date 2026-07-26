# VPS Configuration Reference

**Host:** bbanalyzer.duckdns.org (Hetzner CX22)  
**OS:** Ubuntu 22.04 LTS  
**SSH user:** `deploy`

---

## Capacity / memory (Celery OOM)

The app (Gunicorn + Celery + Postgres + Redis) shares one small VPS. A single
Celery prefork child historically grew past **1.5 GiB RSS**, exhausted RAM and
swap, and blanked the UI (browser API calls aborted with HTTP 499) while
`/api/health` still looked fine.

**Required headroom:** keep the production VPS at **≥ 4 GiB RAM** (upgrade the
CX22 / relocate Celery to a separate worker host). On a ~2 GiB box, one leaked
worker *is* the machine.

**In-tree guards (apply via setup scripts):**

| Guard | Where |
|---|---|
| `--max-tasks-per-child=50`, `--max-memory-per-child=400000` | `scripts/vps-setup/09b-celery-service.sh` |
| `MemoryHigh=700M` / `MemoryMax=900M` | same Celery unit |
| `OOMScoreAdjust=500` (Celery) / `-500` (Gunicorn) | `09b` + `09-gunicorn-service.sh` |
| Soft restart on high RSS / low `MemAvailable` | `scripts/celery-liveness-check.sh` (cron; separate alert cooldown) |
| Health reports memory pressure as **WARN** (not 503) | `GET /api/health` `host_memory` |
| Deploy re-applies unit guards | `scripts/vps-setup/apply-memory-guard-units.sh` via sudo |

Re-apply units after pulling these changes (or let Deploy call `apply-memory-guard-units`):

```bash
sudo bash /home/deploy/app/scripts/vps-setup/migrate-async-stack.sh
# or:
sudo bash /home/deploy/app/scripts/vps-setup/apply-memory-guard-units.sh
```

Longer-term: run heavy GIS/ER on a dedicated worker VM or a separate Redis
queue so interactive API never shares a tight cgroup with batch jobs.

---

## Nginx

Site config is rendered by `scripts/vps-setup/11-nginx-config.sh`. It enables **gzip** for JS/CSS/JSON/SVG (`gzip_types` + `gzip_min_length 1024`). Applying template changes requires re-running that setup script (or equivalent) and `nginx -t && systemctl reload nginx` on the VPS — deploy alone does not rewrite the live nginx site file unless your deploy path includes that step.

---

## PostgreSQL

| Setting | Value |
|---|---|
| Version | PostgreSQL 15 |
| Database | `real_estate_analysis` |
| Application role | `app_user` (NOT `deploy`) |
| Auth method | Password via `.pgpass` (TCP, `-h localhost`) |
| `.pgpass` location | `/home/deploy/.pgpass` (permissions: `600`) |

**Important:** The PostgreSQL application role is `app_user`, not `deploy`. The `deploy` Linux user does NOT have a matching PostgreSQL role. All `pg_dump` and `pg_restore` commands must use `-U app_user -h localhost` and rely on `/home/deploy/.pgpass` for authentication.

The `DATABASE_URL` GitHub secret contains the full connection string:
```text
postgresql://app_user:<password>@localhost:5432/real_estate_analysis
```

The deploy workflow automatically injects `PGUSER`, `PGHOST`, and `.pgpass` credentials from `DATABASE_URL` into `/home/deploy/backup.conf` on every deploy via `scripts/inject-db-creds.py`.

---

## Backup System

| File | Location | Notes |
|---|---|---|
| `backup.sh` | `/home/deploy/backup.sh` | Main backup orchestrator |
| `backup.conf` | `/home/deploy/backup.conf` | Config file (permissions: `600 deploy:deploy`) |
| `.pgpass` | `/home/deploy/.pgpass` | PostgreSQL password file (permissions: `600`) |
| `backup_lib.py` | `/home/deploy/backup_lib.py` | Python helper library |
| `install-backup-cron.sh` | `/home/deploy/install-backup-cron.sh` | Idempotent cron installer (runs on deploy) |
| `verify-backup-health.sh` | `/home/deploy/verify-backup-health.sh` | Health check for CI |
| Backup dumps | `/home/deploy/backups/` | Local dump files (30-day retention) |
| Manifest | `/home/deploy/backups/backup_manifest.log` | NDJSON backup manifest |

### Local schedule (cron)

Installed automatically on each deploy via `install-backup-cron.sh`:

| UTC | Job |
|---|---|
| 02:00, 10:00, 18:00 daily | `backup.sh` (PostgreSQL + Redis) |
| 01:00 Sunday | `pg-basebackup.sh` (PITR base) |
| 00:30 daily | `daily-summary.sh` |

Verify: `crontab -l | grep backup-system-managed`

### Cloud off-site (Backblaze B2)

When GitHub secrets `B2_KEY_ID`, `B2_APPLICATION_KEY`, and `B2_BUCKET_NAME` are set, each deploy:

1. Configures `rclone` remote `b2` (`setup-b2-rclone.py`)
2. Sets `REMOTE_METHOD=rclone` in `backup.conf` (`inject-remote-backup.py`)
3. Uploads each new dump to `b2:<bucket>/backups/YYYY/MM/DD/`

**Production measurement (Jun 2026):** ~57 MB per dump → ~5.1 GB steady-state on B2 with default retention → **$0/month** (under B2’s permanent 10 GB free tier).

| B2 item | Cost |
|---|---|
| Storage ≤ 10 GB | **$0** |
| Uploads | **$0** |
| Storage above 10 GB | ~$0.007/GB/month |
| Occasional restore | **$0** at current scale |

Manual one-time setup (if not using GitHub secrets):

```bash
# On VPS as deploy — create bucket + app key in Backblaze console first
rclone config create b2 b2 account=<key_id> key=<app_key> --non-interactive
# Edit backup.conf: REMOTE_METHOD="rclone", RCLONE_BUCKET="<bucket>", etc.
/home/deploy/backup.sh
rclone ls b2:<bucket>/backups/
```

### Testing backup connectivity

```bash
ssh deploy@bbanalyzer.duckdns.org '/home/deploy/backup.sh --check'
ssh deploy@bbanalyzer.duckdns.org '/home/deploy/verify-backup-health.sh'
ssh deploy@bbanalyzer.duckdns.org '/home/deploy/restore-drill.sh'
```

`backup.sh --check` runs `pg_dump --schema-only` without a full backup.  
`verify-backup-health.sh` checks cron, manifest freshness, and cloud transfer when enabled.  
`restore-drill.sh` runs `pg_restore --list` on the latest dump (no DB overwrite).

---

## GitHub Actions Secrets

| Secret | Value |
|---|---|
| `VPS_SSH_KEY` | Contents of `~/.ssh/bbanalyzer_deploy` (Ed25519 private key) |
| `VPS_USER` | `deploy` |
| `VPS_HOST` | `5.161.200.46` |
| `VPS_HOST_KEY` | `5.161.200.46 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3qSNJa8RTI+PBjSz6Z332g9LVw82et/xpdNnZ4KpcJ` |
| `VPS_SUBDOMAIN` | `bbanalyzer` |
| `DATABASE_URL` | `postgresql://app_user:<password>@localhost:5432/real_estate_analysis` |
| `B2_KEY_ID` | Backblaze application key ID (optional — enables cloud backup) |
| `B2_APPLICATION_KEY` | Backblaze application key secret (optional) |
| `B2_BUCKET_NAME` | Private B2 bucket name (optional) |

---

## Common failure modes

### `pg_dump: FATAL: role "deploy" does not exist`
The backup is trying to connect as the `deploy` Linux user. Fix: ensure `PGUSER="app_user"` in `/home/deploy/backup.conf` and that `/home/deploy/.pgpass` has the correct `app_user` password. The deploy workflow injects these automatically from `DATABASE_URL`.

### `Cannot stat /home/deploy/backup.conf`
The file doesn't exist or has wrong permissions. The deploy workflow creates a stub automatically. If it persists, check that `setup-stub-conf.py` ran successfully in the Deploy step.

### `backup.sh --check` fails
Run `tail -20 /home/deploy/logs/backup.log` on the VPS to see the specific error.

**CI / Deploy policy**

| Gate | Behavior |
|------|----------|
| **App CI** (`.github/workflows/ci.yml`) | App lint/typecheck/build/tests, migration smoke tests, and deploy-contract validation. Does **not** run VPS backup checks such as `backup.sh --check`. |
| **Deploy** | Still hard-fails on **pre-deploy** `backup.sh --check` (and `--pre-deploy` backup). Post-deploy `backup.sh --check` is **advisory** (`::warning::` only) — backup breakage alone does not roll back a healthy ship. Before deploy work, waits for public `/api/health` (~10 min, **soft**) then SSH (~15 min, **hard**); see **Deploy SSH / reachability** below. |
| **Ops health** (`.github/workflows/ops-health.yml`) | **Hourly** SSH + HTTP canary (not on the 6h cron — avoids double-counting); **every 6 hours** (+ after Deploy + manual) full `backup.sh --check`, `verify-backup-health.sh`, soft readiness. Failures open/update a GitHub issue labeled `ops-health` (optional Slack via `SLACK_WEBHOOK_URL`). **Never** triggers or blocks Deploy. |

Branch protection should require **`App CI success`** only (not Ops health).

After App CI → Deploy is green on `main`, stranded merges (e.g. Command Center #136 when only VPS backup smoke failed) ship without re-merging the feature PR.

### Deploy SSH / reachability

**Symptom:** Deploy fails at preflight with `Connection timed out during banner exchange`, port 22 timeout, or public `/api/health` never returning 200. Secrets and SSH key setup often already succeeded; `deploy.sh` never ran.

**Cause:** Transient VPS/network/firewall blip (or a longer outage). A short single-shot SSH check used to strand green App CI merges on `main`.

**What Deploy does now**

1. Checkout the target SHA (scripts needed for waits).
2. Wait for public `https://<VPS_SUBDOMAIN>.duckdns.org/api/health` (~10 minutes) via `scripts/ci-http-health-wait.sh` — **soft** (`continue-on-error`). A down site does not block an SSH deploy (so you can ship a fix). Manual Dispatch can set **`skip_http_preflight`** to skip this wait entirely.
3. Wait for SSH (~15 minutes) via `scripts/ci-ssh-verify.sh` — **hard** gate (retries with backoff; classifies timeout / banner / permission / refused). Auth (`permission`) fails fast; `connection refused` fails after 2 attempts.
4. On SSH unreachable: network/connectivity diagnostics (skip Alembic). If SSH still works after a later deploy failure, Alembic/migration diagnostics still run.
5. After an **App CI → Deploy** (`workflow_run`) **SSH** preflight exhaustion, Deploy **auto re-dispatches once** as `workflow_dispatch` for the same SHA (`gh workflow run deploy.yml`). Requires workflow `permissions.actions: write` and org policy allowing `GITHUB_TOKEN` to start `workflow_dispatch`. Manual Dispatch never auto-requeues (no loop).

**If both attempts fail:** Actions → **Deploy** → **Run workflow** (optionally set `target_sha`; use `skip_http_preflight` if the site is down). Confirm the VPS answers on 22 from your machine first.

**Ops hourly canary**

- Job **VPS SSH/HTTP canary** runs every hour (`0 * * * *`), after non-cancelled Deploy runs, and on manual dispatch — **not** on the overlapping 6h schedule.
- Short budgets (~60s SSH, ~90s HTTP). Does not block App CI or Deploy.
- After **≥ 2 consecutive** canary job failures, opens/updates an issue titled `Ops health: VPS SSH unreachable` or `Ops health: VPS public /api/health down` (label `ops-health`; optional Slack).
- When both canaries succeed again, comments **Reachability recovered** and closes that open issue.

Shared helpers: `scripts/ci-ssh-verify.sh`, `scripts/ci-http-health-wait.sh`.

### `verify-backup-health.sh` reports missing cron
Run `bash /home/deploy/install-backup-cron.sh` or redeploy from `main` after merging the backup redundancy PR.

### Cloud backup not uploading
Check `grep REMOTE_METHOD /home/deploy/backup.conf` (must be `rclone`), `rclone listremotes`, and GitHub secrets `B2_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`.
