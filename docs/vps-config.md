# VPS Configuration Reference

**Host:** bbanalyzer.duckdns.org (Hetzner CX22)  
**OS:** Ubuntu 22.04 LTS  
**SSH user:** `deploy`

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

### `verify-backup-health.sh` reports missing cron
Run `bash /home/deploy/install-backup-cron.sh` or redeploy from `main` after merging the backup redundancy PR.

### Cloud backup not uploading
Check `grep REMOTE_METHOD /home/deploy/backup.conf` (must be `rclone`), `rclone listremotes`, and GitHub secrets `B2_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`.
