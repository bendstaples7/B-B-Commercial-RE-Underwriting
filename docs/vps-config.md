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
```
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
| Backup dumps | `/home/deploy/backups/` | Local dump files (30-day retention) |
| Manifest | `/home/deploy/backups/backup_manifest.log` | NDJSON backup manifest |

### Testing backup connectivity

```bash
ssh deploy@bbanalyzer.duckdns.org '/home/deploy/backup.sh --check'
```

This runs a fast connectivity test (`pg_dump --schema-only`) without creating a full backup. Exit 0 = OK, exit 1 = connectivity problem.

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

---

## Common failure modes

### `pg_dump: FATAL: role "deploy" does not exist`
The backup is trying to connect as the `deploy` Linux user. Fix: ensure `PGUSER="app_user"` in `/home/deploy/backup.conf` and that `/home/deploy/.pgpass` has the correct `app_user` password. The deploy workflow injects these automatically from `DATABASE_URL`.

### `Cannot stat /home/deploy/backup.conf`
The file doesn't exist or has wrong permissions. The deploy workflow creates a stub automatically. If it persists, check that `setup-stub-conf.py` ran successfully in the Deploy step.

### `backup.sh --check` fails
Run `tail -20 /home/deploy/logs/backup.log` on the VPS to see the specific error.
