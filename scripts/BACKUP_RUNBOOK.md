# Backup & Recovery Runbook

**System:** B and B Real Estate Analyzer — Hetzner VPS  
**Database:** PostgreSQL (`real_estate_analysis`)  
**Owner:** `deploy` user  
**Last updated:** 2025-07-15

---

## 1. Backup Schedule

All times are UTC. All jobs run as the `deploy` user.

| Cron Expression | UTC Time | Script | Description |
|---|---|---|---|
| `0 2 * * *` | 02:00 daily | `backup.sh` | PostgreSQL + Redis backup (scheduled) |
| `0 10 * * *` | 10:00 daily | `backup.sh` | PostgreSQL + Redis backup (scheduled) |
| `0 18 * * *` | 18:00 daily | `backup.sh` | PostgreSQL + Redis backup (scheduled) |
| `0 1 * * 0` | 01:00 Sunday | `pg-basebackup.sh` | Weekly full base backup for PITR |
| `30 0 * * *` | 00:30 daily | `daily-summary.sh` | Daily backup status summary report |

The three daily backups at 02:00, 10:00, and 18:00 UTC limit the maximum data loss window to 8 hours or less (RPO ≤ 8 hours).

To verify all 5 entries are installed:

```bash
crontab -u deploy -l
```

---

## 2. Backup Locations

| Type | Path | Retention |
|---|---|---|
| Local dump files | `/home/deploy/backups/` | 30 days |
| WAL archive segments | `/home/deploy/wal-archive/` | 7 days |
| Base backup (PITR) | `/home/deploy/backups/base/` | — (manual management) |
| Remote (off-site) | `<RCLONE_BUCKET>/<RCLONE_PATH_PREFIX>/YYYY/MM/DD/backup_YYYY-MM-DD_HH-MM-SS.dump` | 30 days |
| Backup manifest | `/home/deploy/backups/backup_manifest.log` | — (append-only) |
| Log file | `/home/deploy/logs/backup.log` | — |

**Remote path example:**  
`my-bucket/backups/2025/07/15/backup_2025-07-15_02-00-01.dump`

The remote bucket and path prefix are configured in `/home/deploy/backup.conf` via `RCLONE_BUCKET` and `RCLONE_PATH_PREFIX`.

---

## 3. Listing Available Backups

### List the 20 most recent valid backups

```bash
grep '"integrity": "valid"' /home/deploy/backups/backup_manifest.log | tail -20
```

### List all backups (valid and invalid) with filename, timestamp, and integrity

```bash
cat /home/deploy/backups/backup_manifest.log | python3 -c "import json,sys; [print(e['filename'], e['timestamp'], e['integrity']) for e in [json.loads(l) for l in sys.stdin if l.strip()]]"
```

### List all backups using jq (if installed)

```bash
jq -r '[.filename, .timestamp, .integrity] | @tsv' /home/deploy/backups/backup_manifest.log
```

---

## 4. Restore from Local Snapshot

### Step 1 — Identify the backup file to restore

```bash
grep '"integrity": "valid"' /home/deploy/backups/backup_manifest.log | tail -5
```

Pick the filename from the output, e.g. `backup_2025-07-15_02-00-01.dump`.

### Step 2 — Run the restore script

```bash
/home/deploy/restore.sh backup_2025-07-15_02-00-01.dump
```

### Expected output

The script prints a timestamped progress message for each of the 6 steps:

```
[2025-07-15T02:00:01Z] restore.sh starting — target: backup_2025-07-15_02-00-01.dump
[2025-07-15T02:00:01Z] manifest lookup complete
[2025-07-15T02:00:02Z] checksum verification passed
[2025-07-15T02:00:15Z] safety backup created: pre_restore_2025-07-15T02-00-15Z.dump
[2025-07-15T02:01:30Z] pg_restore complete
[2025-07-15T02:01:35Z] flask db upgrade complete — restore finished
```

### What the script does

1. Looks up the filename in `/home/deploy/backups/backup_manifest.log` — aborts if not found.
2. Verifies the SHA-256 checksum of the file against the manifest — aborts with both checksums if mismatch.
3. Creates a safety backup of the current database state (`pre_restore_<ISO8601>.dump`) before overwriting — aborts if this fails.
4. Runs `pg_restore -d real_estate_analysis --clean --if-exists <backup_file>`.
5. Runs `flask db upgrade head` from `/home/deploy/app/backend/` — exits with error if migrations fail.

### Abort conditions

- Manifest entry not found → script exits without touching the database.
- Checksum mismatch → script prints both expected and computed checksums and exits without touching the database.
- Safety backup failure → script exits without touching the database.

---

## 5. Point-In-Time Recovery (PITR)

PITR allows restoring the database to any specific moment in time using a base backup plus WAL segments. Use this when you need to recover to a point between two scheduled backups (e.g., to undo a bad migration or data corruption).

### Prerequisites

- A base backup exists in `/home/deploy/backups/base/`
- WAL segments covering the target time exist in `/home/deploy/wal-archive/`

### Step-by-step procedure

**1. Stop PostgreSQL**

```bash
sudo systemctl stop postgresql
```

**2. Clear the data directory and restore the base backup**

Find the most recent base backup directory:

```bash
ls -lt /home/deploy/backups/base/
```

Clear the existing data directory and restore the base backup (preserving attributes):

```bash
# Stop PostgreSQL first (Step 1 above)
# Clear the existing data directory
sudo rm -rf /var/lib/postgresql/<version>/main/*

# Copy base backup contents preserving ownership and permissions
sudo cp -a /home/deploy/backups/base/base_YYYY-MM-DD_HH-MM-SS/. /var/lib/postgresql/<version>/main/

# Restore correct ownership
sudo chown -R postgres:postgres /var/lib/postgresql/<version>/main
```

**3. Configure `restore_command` in `postgresql.conf`**

Edit `/etc/postgresql/<version>/main/postgresql.conf` and add or update:

```ini
restore_command = 'cp /home/deploy/wal-archive/%f %p'
```

**4. Set `recovery_target_time` in `postgresql.conf`**

Add the target recovery time (use UTC):

```ini
recovery_target_time = '2025-07-15 14:30:00 UTC'
```

For older PostgreSQL versions (< 12), these settings go in `recovery.conf` in the data directory instead of `postgresql.conf`.

**5. Create the `recovery.signal` file**

```bash
touch /var/lib/postgresql/<version>/main/recovery.signal
```

This file signals PostgreSQL to enter recovery mode on startup.

**6. Start PostgreSQL**

```bash
sudo systemctl start postgresql
```

PostgreSQL will replay WAL segments up to the target time and then pause in a "paused" recovery state.

**7. Verify recovery**

```bash
psql -d real_estate_analysis -c "SELECT now();"
```

Confirm the timestamp matches the expected recovery point.

**8. Promote to primary**

Once you have verified the data is correct, promote the instance to accept writes:

```bash
psql -c "SELECT pg_promote();"
```

After promotion, remove the `recovery_target_time` line from `postgresql.conf` to prevent it from affecting future restarts.

---

## 6. RTO/RPO Targets

| Layer | RPO (max data loss) | RTO (max recovery time) |
|---|---|---|
| Local snapshot | ≤ 8 hours | ≤ 30 minutes |
| Remote backup | ≤ 8 hours | ≤ 2 hours |
| WAL/PITR | ≤ 5 minutes | ≤ 1 hour |

**RPO** (Recovery Point Objective) — the maximum amount of data that can be lost.  
**RTO** (Recovery Time Objective) — the maximum time to restore service after a failure.

---

## 7. Verifying Database Health After Restore

Run these checks after any restore to confirm the database is in a healthy state.

### Check current migration revision

```bash
flask db current
```

The output should show the latest migration revision hash. If it shows a revision behind the expected head, run `flask db upgrade head`.

### Check row counts for key tables

Connect to the database and run:

```sql
SELECT COUNT(*) FROM leads;
SELECT COUNT(*) FROM analysis_sessions;
SELECT COUNT(*) FROM comparable_sales;
```

Compare these counts against known-good values from before the incident. A count of 0 in any table may indicate an incomplete restore.

### Check application health endpoint

```bash
curl http://localhost:5000/api/health
```

Expected response: HTTP 200 with a JSON body indicating the application and database are reachable.

### Check for recent errors in the application log

```bash
tail -50 /home/deploy/logs/backup.log
```

---

## 8. Disaster Recovery Checklist (VPS Completely Lost)

Use this checklist when the VPS is unrecoverable and you need to rebuild from scratch.

1. **Provision a new Hetzner VPS** with the same specs (CPU, RAM, disk) as the original. Use the same OS (Ubuntu LTS).

2. **Install dependencies** on the new VPS:
   ```bash
   sudo apt update && sudo apt install -y postgresql python3 python3-pip rclone msmtp redis-server
   ```
   Redis runs via WSL Ubuntu on Windows. On a Linux VPS, install it natively.

3. **Create the `deploy` user**:
   ```bash
   adduser deploy && usermod -aG sudo deploy
   ```

4. **Download the most recent remote backup** from off-site storage:
   ```bash
   rclone copy <RCLONE_REMOTE>:<RCLONE_BUCKET>/<RCLONE_PATH_PREFIX>/YYYY/MM/DD/<filename> /home/deploy/backups/
   ```
   Replace `YYYY/MM/DD/<filename>` with the actual date path and filename of the most recent valid backup.

5. **Restore the backup manifest** — the manifest (`backup_manifest.log`) is stored locally on the VPS and is not uploaded off-site. After a total VPS loss, the manifest is unavailable. You have two options:

   **Option A — Use `restore.sh` with a reconstructed manifest entry** (recommended):
   Create a minimal manifest entry for the downloaded backup file:
   ```bash
   # Compute the SHA-256 of the downloaded backup
   SHA256=$(sha256sum /home/deploy/backups/<filename> | awk '{print $1}')
   SIZE=$(stat -c "%s" /home/deploy/backups/<filename>)
   # Pipe the JSON directly into serialize-manifest and write to the manifest file
   echo "{\"filename\":\"<filename>\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"size_bytes\":$SIZE,\"sha256\":\"$SHA256\",\"integrity\":\"valid\",\"type\":\"scheduled\",\"remote_transferred\":true,\"remote_path\":\"\"}" \
     | python3 /home/deploy/backup_lib.py serialize-manifest \
     > /home/deploy/backups/backup_manifest.log
   ```
   Then run `restore.sh <filename>` normally.

   **Option B — Manual restore** (when manifest reconstruction is not feasible):
   ```bash
   pg_restore -d real_estate_analysis --clean --if-exists /home/deploy/backups/<filename>
   cd /home/deploy/app/backend && flask db upgrade head
   ```
   Note: This bypasses checksum verification. Only use this when you have high confidence in the backup file's integrity (e.g., freshly downloaded from your own off-site storage).

6. **Deploy all scripts** to `/home/deploy/`:
   - `backup.sh`, `restore.sh`, `redis-backup.sh`, `wal-archive.sh`, `pg-basebackup.sh`, `daily-summary.sh`, `backup_lib.py`
   - Set permissions:
     ```bash
     chmod 750 /home/deploy/backup.sh /home/deploy/restore.sh /home/deploy/redis-backup.sh \
               /home/deploy/pg-basebackup.sh /home/deploy/daily-summary.sh
     chmod 755 /home/deploy/wal-archive.sh   # must be executable by the postgres OS user
     chmod 644 /home/deploy/backup_lib.py
     ```

7. **Create and configure `/home/deploy/backup.conf`**:
   ```bash
   cp scripts/backup.conf.example /home/deploy/backup.conf
   chmod 600 /home/deploy/backup.conf
   chown deploy:deploy /home/deploy/backup.conf
   ```
   Edit the file and fill in all real values: `PGDATABASE`, `RCLONE_REMOTE`, `RCLONE_BUCKET`, `ALERT_EMAIL`, `WEBHOOK_URL`, etc.

8. **Run `scripts/setup-backup-dirs.sh`** to create required directories and set permissions:
   ```bash
   bash scripts/setup-backup-dirs.sh
   ```
   This creates `/home/deploy/backups/`, `/home/deploy/wal-archive/`, `/home/deploy/logs/`, and `/home/deploy/backups/base/` with correct ownership.

9. **Run `restore.sh` to restore the database**:
   ```bash
   /home/deploy/restore.sh <backup_filename>
   ```
   Use the filename downloaded in step 4.

10. **Verify data integrity**:
    ```bash
    flask db current
    psql -d real_estate_analysis -c "SELECT COUNT(*) FROM leads;"
    curl http://localhost:5000/api/health
    ```

11. **Resume application services and install cron entries**:
    ```bash
    sudo systemctl start gunicorn
    bash scripts/setup-cron.sh
    ```
    Verify cron entries: `crontab -u deploy -l`

---

## 9. Alert Troubleshooting

### Test msmtp email delivery manually

```bash
echo "Test alert" | msmtp --account=default operator@example.com
```

Replace `operator@example.com` with the address configured in `ALERT_EMAIL` in `/home/deploy/backup.conf`.

### Test webhook delivery with curl

```bash
curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" -d '{"text": "Test alert from backup system"}'
```

Replace `$WEBHOOK_URL` with the actual webhook URL from `/home/deploy/backup.conf`, or source the config first:

```bash
source /home/deploy/backup.conf
curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" -d '{"text": "Test alert from backup system"}'
```

### Locate alert delivery failures in the log

```bash
grep "ALERT DELIVERY FAILED" /home/deploy/logs/backup.log
```

Each failed delivery attempt is logged with a UTC timestamp and the error returned by the notification channel. If you see repeated failures, check:

- **Email**: verify `msmtp` config at `~/.msmtprc` or `/etc/msmtprc`; confirm SMTP credentials and port.
- **Webhook**: verify the URL is reachable from the VPS (`curl -I "$WEBHOOK_URL"`); check for firewall rules blocking outbound HTTPS.

### View recent backup log entries

```bash
tail -100 /home/deploy/logs/backup.log
```

### Check last backup run status

```bash
grep -E "(backup complete|FAILED|ERROR)" /home/deploy/logs/backup.log | tail -20
```
