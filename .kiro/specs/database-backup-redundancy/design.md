# Design Document: Database Backup Redundancy

## Overview

This design implements a three-layer backup strategy for the B and B Real Estate Analyzer platform running on a Hetzner VPS (Flask/PostgreSQL/Redis, no Docker). The three layers are:

1. **Local snapshots** — `pg_dump --format=custom` runs at 02:00, 10:00, and 18:00 UTC daily, stored in `/home/deploy/backups/`, giving an RPO ≤ 8 hours and RTO ≤ 30 minutes.
2. **Off-site transfer** — every local backup is copied to Backblaze B2 (or another configured provider) via `rclone` within one hour of creation, giving an RPO ≤ 8 hours and RTO ≤ 2 hours.
3. **WAL/PITR** — continuous WAL archiving plus a weekly `pg_basebackup` enables point-in-time recovery to within minutes, giving an RPO ≤ 5 minutes and RTO ≤ 1 hour.

Redis RDB snapshots are taken alongside each PostgreSQL backup to preserve Celery task queue state. All scripts run as the `deploy` user. Secrets are stored in `/home/deploy/backup.conf` (permissions `600`). Alerting is delivered via `msmtp` email and/or an HTTP webhook. A pre-deploy backup hook is integrated into the existing `scripts/deploy.sh`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Cron (deploy user)                                                 │
│  02:00 / 10:00 / 18:00 UTC ──► backup.sh ──► pg_dump (custom fmt)  │
│                                           ──► redis-backup.sh       │
│                                           ──► integrity check       │
│                                           ──► rclone (B2)           │
│                                           ──► manifest update       │
│                                           ──► alert on failure      │
│                                                                     │
│  Weekly (Sunday 01:00 UTC) ─────────────► pg_basebackup             │
│  Continuous ────────────────────────────► wal-archive.sh            │
│  00:30 UTC daily ───────────────────────► daily-summary.sh          │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
/home/deploy/backups/          (local, 30-day retention)
/home/deploy/wal-archive/      (WAL segments, 7-day retention)
         │
         ▼ rclone
Backblaze B2: YYYY/MM/DD/      (remote, 30-day retention)
```

### Deploy Integration

```
GitHub Actions deploy.yml
  └─► SSH to VPS
        └─► deploy.sh
              ├─► [NEW] backup.sh --pre-deploy   (blocks deploy on failure)
              ├─► git checkout TARGET_SHA
              ├─► pip install
              ├─► flask db upgrade
              └─► systemctl reload gunicorn
```


---

## Components and Interfaces

### Script Inventory

| Script | Location | Runs as | Triggered by |
|---|---|---|---|
| `backup.sh` | `/home/deploy/backup.sh` | `deploy` | cron, deploy.sh |
| `restore.sh` | `/home/deploy/restore.sh` | `deploy` | operator (manual) |
| `wal-archive.sh` | `/home/deploy/wal-archive.sh` | `postgres` | PostgreSQL `archive_command` |
| `redis-backup.sh` | `/home/deploy/redis-backup.sh` | `deploy` | called by backup.sh |
| `daily-summary.sh` | `/home/deploy/daily-summary.sh` | `deploy` | cron (00:30 UTC) |

### `backup.sh` — Main Backup Orchestrator

**Interface:**
```
backup.sh [--pre-deploy]
```

**Execution flow:**
1. Source `/home/deploy/backup.conf`; verify file permissions are `600` owned by `deploy:deploy`; abort on failure.
2. Validate required credentials are present; abort with alert if any are missing.
3. Verify `/home/deploy/backups/` exists and is writable; abort with alert if not.
4. Determine filename: `backup_YYYY-MM-DD_HH-MM-SS.dump` (UTC) or `backup_pre-deploy_YYYY-MM-DD_HH-MM-SS.dump` when `--pre-deploy` is passed.
5. Run `pg_dump -Fc -d real_estate_analysis -f <dump_file>`; on non-zero exit, log + alert + exit 1.
6. Compute SHA-256 checksum of the dump file.
7. Run `pg_restore --list <dump_file>`; record integrity as `valid` or `invalid`.
8. Append manifest entry to `/home/deploy/backups/backup_manifest.log`.
9. Call `redis-backup.sh` (failure is logged and alerted but does NOT block PostgreSQL backup).
10. Transfer dump file to remote via `rclone` (or configured provider); retry up to 3 times with 5-minute delay.
11. Verify remote file size matches local file size.
12. If all steps succeeded, delete local backups older than 30 days; skip deletion on any failure.
13. Delete remote backups older than 30 days.
14. Log completion with UTC timestamp.

**Exit codes:** `0` = success, `1` = any failure.

### `restore.sh` — Database Restore

**Interface:**
```
restore.sh <backup_filename>
```

**Execution flow:**
1. Print timestamped "script start" to stdout.
2. Look up `<backup_filename>` in `/home/deploy/backups/backup_manifest.log`; abort if not found.
3. Print "manifest lookup complete".
4. Compute SHA-256 of the backup file; compare to manifest value; abort with both checksums if mismatch.
5. Print "checksum verification passed".
6. Create safety backup: `pg_dump -Fc -d real_estate_analysis -f pre_restore_<ISO8601>.dump`; abort if this fails.
7. Print "safety backup created: pre_restore_<ISO8601>.dump".
8. Run `pg_restore -d real_estate_analysis --clean --if-exists <backup_file>`; log exit code.
9. Print "pg_restore complete".
10. Run `flask db upgrade head` from `/home/deploy/app/backend/`; print error and exit 1 on failure.
11. Print "flask db upgrade complete — restore finished".

**Permissions:** `750`, owned by `deploy:deploy`.

### `wal-archive.sh` — WAL Segment Archiver

**Interface:** Called by PostgreSQL `archive_command`:
```
wal-archive.sh %p %f
```
where `%p` = full path to WAL segment, `%f` = filename.

**Execution flow:**
1. Copy `%p` to `/home/deploy/wal-archive/%f`.
2. Exit `0` on success (PostgreSQL will recycle the segment).
3. On failure: log segment name + exit code to `/home/deploy/logs/backup.log`, send alert, exit `1` (PostgreSQL will retry).
4. Check free space in `/home/deploy/wal-archive/`; if insufficient, log + alert + exit `1`.

### `redis-backup.sh` — Redis RDB Snapshot

**Interface:** Called by `backup.sh`; no arguments.

**Execution flow:**
1. Ping Redis (via WSL: `wsl -d Ubuntu -- redis-cli ping`); on failure, log + alert + return 1 (non-blocking).
2. Send `BGSAVE` command; poll `LASTSAVE` every 5 seconds for up to 300 seconds.
3. If 300-second timeout expires without completion, log + alert + return 1 without copying.
4. Copy `dump.rdb` from WSL Redis data directory to `/home/deploy/backups/redis_YYYY-MM-DD_HH-MM-SS.rdb`.
5. Delete Redis backup files in `/home/deploy/backups/` older than 7 days.

**Redis path on WSL Ubuntu:** `/var/lib/redis/dump.rdb` (default). Configurable in `backup.conf`.

### `daily-summary.sh` — Daily Status Report

**Interface:** Cron at 00:30 UTC daily.

**Execution flow:**
1. Parse `/home/deploy/backups/backup_manifest.log` for entries in the preceding 24 hours.
2. Count successful backups, failed integrity checks, total storage used in `/home/deploy/backups/` (MB).
3. Find UTC timestamp of most recent successful backup.
4. If most recent successful backup is older than 12 hours, include stale-backup alert in the summary.
5. Send summary via configured notification channel.


---

## Data Models

### `/home/deploy/backup.conf` — Configuration and Secrets File

Permissions: `600`, owned by `deploy:deploy`. Sourced as a shell environment file.

```bash
# /home/deploy/backup.conf
# Permissions: 600, owned by deploy:deploy

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PGDATABASE="real_estate_analysis"
PGUSER="deploy"
# Uses .pgpass or peer auth — no password stored here

# ── Backup directories ────────────────────────────────────────────────────────
BACKUP_DIR="/home/deploy/backups"
WAL_ARCHIVE_DIR="/home/deploy/wal-archive"
LOG_FILE="/home/deploy/logs/backup.log"

# ── Remote storage ────────────────────────────────────────────────────────────
REMOTE_METHOD="rclone"          # rclone | s3 | rsync
RCLONE_REMOTE="b2"              # rclone remote name (configured via rclone config)
RCLONE_BUCKET="my-bucket"
RCLONE_PATH_PREFIX="backups"    # remote path: RCLONE_BUCKET/RCLONE_PATH_PREFIX/YYYY/MM/DD/

# ── Retention ─────────────────────────────────────────────────────────────────
LOCAL_RETENTION_DAYS=30
REMOTE_RETENTION_DAYS=30
REDIS_RETENTION_DAYS=7
WAL_RETENTION_DAYS=7

# ── Alerting ──────────────────────────────────────────────────────────────────
ALERT_METHOD="email"            # email | webhook | both
ALERT_EMAIL="operator@example.com"
MSMTP_ACCOUNT="default"
WEBHOOK_URL=""                  # Slack/Discord/custom HTTP endpoint

# ── Redis (WSL Ubuntu) ────────────────────────────────────────────────────────
REDIS_RDB_PATH="/var/lib/redis/dump.rdb"   # path inside WSL Ubuntu
REDIS_BGSAVE_TIMEOUT=300

# ── Timeouts ──────────────────────────────────────────────────────────────────
REMOTE_CONNECT_TIMEOUT=30
REMOTE_RETRY_COUNT=3
REMOTE_RETRY_DELAY=300          # seconds between retries
```

### Backup Manifest Format — `/home/deploy/backups/backup_manifest.log`

One JSON object per line (newline-delimited JSON / NDJSON). This format is append-only; the restore script and daily-summary script parse it with `grep` + `python3 -c` or `jq`.

```json
{
  "filename": "backup_2025-07-15_02-00-01.dump",
  "timestamp": "2025-07-15T02:00:01Z",
  "size_bytes": 104857600,
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "integrity": "valid",
  "type": "scheduled",
  "remote_transferred": true,
  "remote_path": "backups/2025/07/15/backup_2025-07-15_02-00-01.dump"
}
```

**Field definitions:**

| Field | Type | Description |
|---|---|---|
| `filename` | string | Basename of the dump file |
| `timestamp` | string | ISO 8601 UTC timestamp of backup completion |
| `size_bytes` | integer | Size of dump file on disk in bytes |
| `sha256` | string | SHA-256 hex digest of the dump file |
| `integrity` | string | `"valid"` or `"invalid"` (result of `pg_restore --list`) |
| `type` | string | `"scheduled"` or `"pre-deploy"` |
| `remote_transferred` | boolean | Whether off-site transfer succeeded |
| `remote_path` | string | Full remote path (empty string if transfer failed) |

### WAL Archive Directory Layout

```
/home/deploy/wal-archive/
├── 000000010000000000000001
├── 000000010000000000000002
├── ...
└── 000000010000000000000NNN
```

WAL segments are named by PostgreSQL convention (24-character hex). The `wal-archive.sh` script copies them flat into this directory. Purge logic deletes segments older than 7 days that are not needed to recover from any retained base backup.

### Base Backup Directory Layout

```
/home/deploy/backups/
├── base/
│   └── base_2025-07-13_01-00-00/     # pg_basebackup output directory
│       ├── PG_VERSION
│       ├── backup_label
│       ├── global/
│       └── base/
├── backup_2025-07-15_02-00-01.dump
├── backup_2025-07-15_10-00-01.dump
├── backup_2025-07-15_18-00-01.dump
├── redis_2025-07-15_02-00-05.rdb
└── backup_manifest.log
```

### Remote Storage Path Structure

```
<RCLONE_BUCKET>/<RCLONE_PATH_PREFIX>/
└── YYYY/
    └── MM/
        └── DD/
            └── backup_YYYY-MM-DD_HH-MM-SS.dump
```

Example: `my-bucket/backups/2025/07/15/backup_2025-07-15_02-00-01.dump`


---

## PostgreSQL Configuration Changes

### `postgresql.conf` additions

```ini
# WAL archiving — add to /etc/postgresql/<version>/main/postgresql.conf
wal_level = replica
archive_mode = on
archive_command = '/home/deploy/wal-archive.sh %p %f'
archive_timeout = 300           # force WAL switch every 5 minutes even if segment not full
```

After editing, reload PostgreSQL: `sudo systemctl reload postgresql`.

### `.pgpass` for passwordless `pg_dump`

```
# /home/deploy/.pgpass — permissions 600
localhost:5432:real_estate_analysis:deploy:<password>
```

Or configure PostgreSQL peer authentication for the `deploy` user in `pg_hba.conf` (preferred for local connections):
```
# pg_hba.conf
local   real_estate_analysis   deploy   peer
```

### Cron Schedule (`crontab -u deploy -e`)

```cron
# PostgreSQL + Redis backups — 3× daily
0  2 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1
0 10 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1
0 18 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1

# Weekly base backup — Sunday 01:00 UTC
0  1 * * 0  /home/deploy/pg-basebackup.sh >> /home/deploy/logs/backup.log 2>&1

# Daily summary — 00:30 UTC
30 0 * * *  /home/deploy/daily-summary.sh >> /home/deploy/logs/backup.log 2>&1
```

### Pre-Deploy Hook Integration

The existing `scripts/deploy.sh` is modified to call `backup.sh --pre-deploy` as the first substantive step, immediately after the pre-deploy health checks and before `git checkout`:

```bash
# ── Pre-deploy backup (blocks deploy on failure) ──────────────────────────────
echo "==> (0) Pre-deploy backup"
/home/deploy/backup.sh --pre-deploy || { echo "FAILED: pre-deploy backup failed — aborting deploy"; exit 1; }
echo "    Pre-deploy backup complete"

# ── Deploy steps ─────────────────────────────────────────────────────────────
echo "==> (1) Discard local changes and checkout SHA: $TARGET_SHA"
# ... existing steps continue unchanged ...
```

This ensures a restorable snapshot exists before any code or schema changes are applied.

---

## Alerting Design

### Alert Function (shared across all scripts)

```bash
send_alert() {
    local subject="$1"
    local body="$2"
    # Never log credential values — body must be pre-sanitized by caller
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT: $subject" >> "$LOG_FILE"

    if [[ "$ALERT_METHOD" == "email" || "$ALERT_METHOD" == "both" ]]; then
        echo "$body" | msmtp --account="$MSMTP_ACCOUNT" "$ALERT_EMAIL" \
            --subject="[Backup Alert] $subject" 2>>"$LOG_FILE" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (email): $?" >> "$LOG_FILE"
    fi

    if [[ "$ALERT_METHOD" == "webhook" || "$ALERT_METHOD" == "both" ]]; then
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"[Backup Alert] $subject\n$body\"}" \
            --max-time 10 2>>"$LOG_FILE" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (webhook): $?" >> "$LOG_FILE"
    fi
}
```

Alert messages always include: backup type, UTC timestamp of failure, and failure reason. Credential values are never interpolated into alert messages or log entries.


---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The backup system's core logic is implemented in shell scripts, but the testable pure-function components — filename generation, manifest serialization/parsing, checksum comparison, retention filtering, retry decision logic, alert formatting, and remote path generation — are extracted into a small Python helper module (`/home/deploy/backup_lib.py`) that the shell scripts call via `python3 -c` or as a subprocess. This module is the target of property-based tests.

**Property Reflection:** After reviewing all prework items, the following redundancies were eliminated:
- Requirement 1.2 (scheduled filename format) and 2.4 (pre-deploy filename format) are unified into a single filename-generation property covering both types.
- Requirement 1.4 (local retention) and 6.4 (Redis retention) both test the same age-filter function with different retention thresholds — unified into one retention-filter property.
- Requirement 3.3 (remote size match) and 4.3 (integrity field recording) are distinct enough to keep separate.
- Requirements 7.1 and 7.3 (alert content, summary content) are unified into one alert-fields property.

---

### Property 1: Backup filename generation is correctly formatted

*For any* valid UTC timestamp and backup type (`scheduled` or `pre-deploy`), the filename generation function SHALL produce a string that matches the expected pattern and can be parsed back to recover the original timestamp and type.

**Validates: Requirements 1.2, 2.4**

---

### Property 2: Manifest entry round-trip fidelity

*For any* valid backup metadata record (filename, timestamp, size_bytes, sha256, integrity, type, remote_transferred, remote_path), serializing it to a manifest line and then parsing that line back SHALL produce a record equal to the original.

**Validates: Requirements 1.3, 4.3**

---

### Property 3: Retention filter correctness

*For any* list of backup files with associated creation timestamps and any retention threshold in days, the retention filter function SHALL return exactly the files whose age is strictly less than the threshold, and SHALL exclude all files whose age is greater than or equal to the threshold.

**Validates: Requirements 1.4, 6.4**

---

### Property 4: Checksum comparison is symmetric and exact

*For any* pair of SHA-256 hex strings (expected, computed), the checksum comparison function SHALL return `True` if and only if the strings are identical (case-insensitive), and SHALL return `False` for any pair that differs in any character.

**Validates: Requirements 8.3**

---

### Property 5: Manifest lookup returns the correct entry

*For any* manifest containing one or more entries and any filename that appears in the manifest, the lookup function SHALL return the entry whose `filename` field equals the query, and SHALL return `None` for any filename not present in the manifest.

**Validates: Requirements 8.2**

---

### Property 6: Remote path generation follows date-structured format

*For any* valid UTC timestamp and backup filename, the remote path generation function SHALL produce a path of the form `<prefix>/YYYY/MM/DD/<filename>` where YYYY, MM, DD correspond to the UTC date components of the timestamp.

**Validates: Requirements 3.6**

---

### Property 7: Retry logic exhausts exactly N attempts before alerting

*For any* sequence of transfer outcomes (success or failure) of length ≤ `REMOTE_RETRY_COUNT`, the retry controller SHALL attempt the transfer exactly as many times as there are failures before the first success (or `REMOTE_RETRY_COUNT` times if all fail), and SHALL trigger an alert if and only if all attempts fail.

**Validates: Requirements 3.4**

---

### Property 8: Alert messages always contain required fields

*For any* alert event (backup type, UTC timestamp, failure reason), the formatted alert message SHALL contain a non-empty backup type string, a valid ISO 8601 UTC timestamp, and a non-empty failure reason string, and SHALL NOT contain any value that appears in the configured credentials.

**Validates: Requirements 7.1, 9.2**

---

### Property 9: Daily summary aggregation is correct over any 24-hour window

*For any* set of manifest entries with varying timestamps and integrity values, the daily summary aggregation function SHALL count as "successful" exactly those entries whose `integrity` is `"valid"` and whose timestamp falls within the preceding 24-hour window, and SHALL count as "failed" exactly those entries whose `integrity` is `"invalid"` within the same window.

**Validates: Requirements 4.4, 7.3**

---

### Property 10: Stale backup detection uses correct time comparison

*For any* UTC timestamp representing the most recent successful backup and any current UTC time, the stale-backup detection function SHALL return `True` if and only if the elapsed time exceeds 12 hours, and SHALL return `False` otherwise.

**Validates: Requirements 7.4**

---

### Property 11: Remote transfer method dispatch is exhaustive

*For any* string value of `REMOTE_METHOD`, the dispatch function SHALL route to the `rclone` handler if the value is `"rclone"`, to the `s3` handler if the value is `"s3"`, to the `rsync` handler if the value is `"rsync"`, and SHALL return an error for any other value.

**Validates: Requirements 3.2**


---

## Error Handling

### Failure Modes and Responses

| Failure | Response | Blocks backup? | Blocks deploy? |
|---|---|---|---|
| `backup.conf` missing or wrong permissions | Log + alert, abort entire run | Yes | Yes |
| Required credential missing | Log + alert, abort entire run | Yes | Yes |
| `/home/deploy/backups/` not writable | Log + alert, abort entire run | Yes | Yes |
| `pg_dump` non-zero exit | Log + alert, exit 1, skip deletion | Yes | Yes |
| `pg_restore --list` non-zero exit | Set integrity=invalid, log + alert, continue | No | No |
| Remote transfer failure (transient) | Retry up to 3×, 5-min delay; alert after all retries | No | No |
| Remote transfer failure (auth error) | Immediate log + alert, no retry | No | No |
| Remote size mismatch | Treat as failed transfer, apply retry logic | No | No |
| Redis unreachable | Log + alert, return 1 from redis-backup.sh, continue PostgreSQL backup | No | No |
| Redis BGSAVE timeout (>300s) | Log + alert, abort RDB copy, no stale file copied | No | No |
| RDB copy failure | Log + alert, do NOT delete existing Redis backups | No | No |
| WAL archive command failure | Log + alert, exit 1 (PostgreSQL retries) | N/A | No |
| WAL archive directory full | Log + alert, exit 1 | N/A | No |
| Alert delivery failure | Log the delivery failure (no recursive alert) | No | No |
| Manifest lookup failure in restore.sh | Print error, abort without touching DB | N/A | N/A |
| Checksum mismatch in restore.sh | Print both checksums, abort without touching DB | N/A | N/A |
| Safety backup failure in restore.sh | Abort without touching DB | N/A | N/A |
| `flask db upgrade` failure after restore | Print error, exit 1 (DB is restored, migrations failed) | N/A | N/A |

### Credential Safety in Logs

All log and alert functions receive pre-formatted strings. Credential values (keys, passwords, webhook URLs) are sourced from `backup.conf` into shell variables but are never interpolated into log messages. The `send_alert` function receives only the subject and body strings constructed by the caller, which must not include credential variable expansions.

### Partial Failure Isolation

The PostgreSQL backup and Redis backup are independent. A Redis failure logs and alerts but does not prevent the PostgreSQL dump from completing or the remote transfer from proceeding. This ensures the primary data protection layer is never blocked by the secondary one.

---

## Testing Strategy

### Dual Testing Approach

The backup system uses two complementary test layers:

1. **Property-based tests** (Hypothesis) — test the pure Python helper functions in `backup_lib.py` that implement the core logic: filename generation, manifest serialization/parsing, checksum comparison, retention filtering, remote path generation, retry decision logic, alert formatting, and summary aggregation.

2. **Example-based unit tests** (pytest) — test specific error paths, integration points, and edge cases that are not amenable to property-based testing (e.g., "when pg_dump exits non-zero, alert is sent").

3. **Smoke tests** — verify infrastructure configuration: cron entries exist, scripts are executable, `backup.conf` has correct permissions, `postgresql.conf` contains required WAL settings.

### Property-Based Test Configuration

- **Library:** Hypothesis (already used in the project — see `backend/.hypothesis/`)
- **Minimum iterations:** 100 per property (Hypothesis default `max_examples=100`)
- **Location:** `backend/tests/test_backup_properties.py`
- **Tag format:** `# Feature: database-backup-redundancy, Property N: <property_text>`

Each correctness property maps to exactly one `@given`-decorated test function.

### Example Test File Structure

```python
# backend/tests/test_backup_properties.py
from hypothesis import given, settings
from hypothesis import strategies as st
import pytest
from backup_lib import (
    generate_backup_filename,
    parse_backup_filename,
    serialize_manifest_entry,
    parse_manifest_entry,
    filter_by_retention,
    compare_checksums,
    lookup_manifest_entry,
    generate_remote_path,
    retry_controller,
    format_alert_message,
    aggregate_daily_summary,
    is_backup_stale,
    dispatch_transfer_method,
)

# Feature: database-backup-redundancy, Property 1: Backup filename generation is correctly formatted
@given(
    timestamp=st.datetimes(timezones=st.just(timezone.utc)),
    backup_type=st.sampled_from(["scheduled", "pre-deploy"])
)
@settings(max_examples=100)
def test_filename_generation_round_trip(timestamp, backup_type):
    filename = generate_backup_filename(timestamp, backup_type)
    parsed_ts, parsed_type = parse_backup_filename(filename)
    assert parsed_ts == timestamp.replace(microsecond=0)
    assert parsed_type == backup_type
    assert filename.endswith(".dump")

# Feature: database-backup-redundancy, Property 2: Manifest entry round-trip fidelity
@given(entry=manifest_entry_strategy())
@settings(max_examples=100)
def test_manifest_round_trip(entry):
    line = serialize_manifest_entry(entry)
    parsed = parse_manifest_entry(line)
    assert parsed == entry

# ... (one test per property)
```

### Unit Test Coverage (Example-Based)

Key example tests to write alongside the property tests:

- `pg_dump` non-zero exit → log entry written, alert sent, exit code 1
- `backup.conf` permissions `644` → backup aborts before any operation
- Missing `ALERT_EMAIL` credential → backup aborts with log entry
- Redis unreachable → PostgreSQL backup continues, Redis error logged
- Remote transfer auth failure → no retry, immediate alert
- `restore.sh` with unknown filename → aborts, DB unchanged
- `restore.sh` with checksum mismatch → aborts, prints both checksums
- `restore.sh` safety backup failure → aborts, DB unchanged
- `flask db upgrade` failure after restore → exit 1, error printed

### Smoke Tests

Verify on the VPS after installation:
- `crontab -u deploy -l` contains entries for 02:00, 10:00, 18:00, 00:30, and Sunday 01:00
- `/home/deploy/backup.sh` is executable by `deploy`
- `/home/deploy/restore.sh` has permissions `750` owned by `deploy:deploy`
- `/home/deploy/backup.conf` has permissions `600` owned by `deploy:deploy`
- `postgresql.conf` contains `archive_mode = on` and `archive_command`
- `rclone listremotes` shows the configured B2 remote

### Integration Tests

Run against a test PostgreSQL instance:
- Full backup → verify dump file created, manifest entry written, integrity `valid`
- Full backup → rclone transfer → verify remote file exists and size matches
- Full backup → restore → verify database contents match original
- WAL archive → verify segment appears in `/home/deploy/wal-archive/`


---

## Runbook Reference

The full operational runbook is deployed to `/home/deploy/BACKUP_RUNBOOK.md` on the VPS. It covers:

- Backup schedule and locations (local and remote)
- How to list available backups: `grep '"integrity": "valid"' /home/deploy/backups/backup_manifest.log | tail -20`
- How to invoke `restore.sh <filename>`
- How to perform a PITR restore using `pg_basebackup` + WAL replay
- How to verify database health after restore: `flask db current`, row counts, application health endpoint
- RTO/RPO targets per layer:
  - Local snapshot: RPO ≤ 8 hours, RTO ≤ 30 minutes
  - Remote backup: RPO ≤ 8 hours, RTO ≤ 2 hours
  - WAL/PITR: RPO ≤ 5 minutes, RTO ≤ 1 hour
- Disaster recovery checklist (VPS completely lost): provision server → install dependencies → `rclone copy` latest remote backup → run `restore.sh` → verify → resume services

---

## Design Decisions

**Why `pg_dump --format=custom` instead of plain SQL?**
Custom format is compressed, supports parallel restore with `pg_restore -j`, and enables selective table restore. It is the standard choice for production PostgreSQL backups.

**Why `backup_lib.py` as a Python helper module?**
Shell scripts are difficult to unit-test and property-test. Extracting the pure logic (filename generation, manifest parsing, checksum comparison, etc.) into a Python module allows Hypothesis to exercise it with hundreds of generated inputs. The shell scripts remain thin orchestrators that call `python3 backup_lib.py <subcommand>` for these operations.

**Why NDJSON for the manifest?**
NDJSON (one JSON object per line) is append-only, human-readable, and trivially parseable with `grep` + `python3 -c 'import json,sys; ...'` or `jq`. It avoids the need to rewrite the entire file on each backup run, which would risk corruption if the process is interrupted.

**Why not Docker for Redis?**
The project explicitly avoids Docker. Redis runs via WSL Ubuntu on the VPS. The `redis-backup.sh` script uses `wsl -d Ubuntu -- redis-cli` to communicate with it and copies the RDB file from the WSL filesystem.

**Why block the deploy on pre-deploy backup failure?**
A failed pre-deploy backup means there is no guaranteed restore point before the schema migration runs. Allowing the deploy to proceed without a backup would violate the core safety guarantee. The operator can override by manually running `backup.sh` and then re-triggering the deploy.

**Why retry remote transfers but not `pg_dump`?**
Remote transfers fail transiently (network blips, B2 rate limits). `pg_dump` failures indicate a local problem (PostgreSQL down, disk full, permissions) that retrying immediately will not fix. Retrying `pg_dump` would delay alerting without improving outcomes.
