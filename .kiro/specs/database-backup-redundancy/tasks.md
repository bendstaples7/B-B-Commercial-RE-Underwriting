# Implementation Plan: Database Backup Redundancy

## Overview

Implementation plan for the three-layer backup strategy: local PostgreSQL snapshots, off-site remote transfer, and WAL-based PITR. All scripts run on the Hetzner VPS as the `deploy` user. The Python helper module `backup_lib.py` is the testable core of the system, with property-based tests (Hypothesis) and example-based unit tests in `backend/tests/`.

## Tasks

- [x] 1. Create `backup_lib.py` — Pure Python Helper Module
  - Create `/home/deploy/backup_lib.py` with all pure helper functions: `generate_backup_filename`, `parse_backup_filename`, `serialize_manifest_entry`, `parse_manifest_entry`, `filter_by_retention`, `compare_checksums`, `lookup_manifest_entry`, `generate_remote_path`, `retry_controller`, `format_alert_message`, `aggregate_daily_summary`, `is_backup_stale`, `dispatch_transfer_method`
  - Add a `__main__` CLI interface for shell script integration: `generate-filename`, `lookup-manifest`, `filter-retention`, `generate-remote-path`, `is-stale`, `serialize-manifest`, `compare-checksums`, `aggregate-summary`
  - Ensure the module has no external dependencies beyond the Python 3 standard library
  - _Requirements: 1.2, 1.3, 1.4, 2.4, 3.2, 3.4, 3.6, 4.3, 4.4, 6.4, 7.1, 7.3, 7.4, 8.2, 8.3, 9.2_

- [x] 2. Write property-based tests in `backend/tests/test_backup_properties.py`
  - [x] 2.1 Write Property 1 — Backup filename generation round-trip: `@given(timestamp, backup_type)` asserts `parse_backup_filename(generate_backup_filename(ts, t))` recovers original timestamp and type, filename ends with `.dump` — **Validates: Requirements 1.2, 2.4**
  - [x] 2.2 Write Property 2 — Manifest entry round-trip fidelity: build `manifest_entry_strategy()` covering all 8 fields; assert `parse_manifest_entry(serialize_manifest_entry(entry)) == entry` — **Validates: Requirements 1.3, 4.3**
  - [x] 2.3 Write Property 3 — Retention filter correctness: `@given(files, now, retention_days)` asserts kept files have age < threshold and excluded files have age >= threshold — **Validates: Requirements 1.4, 6.4**
  - [x] 2.4 Write Property 4 — Checksum comparison is symmetric and exact: `@given(s=st.text(alphabet=hex_chars, min_size=64, max_size=64))` asserts identity and case-insensitivity; asserts `False` for any single-character mutation — **Validates: Requirements 8.3**
  - [x] 2.5 Write Property 5 — Manifest lookup returns correct entry: `@given(entries=st.lists(..., min_size=1))` asserts lookup by present filename returns matching entry; absent filename returns `None` — **Validates: Requirements 8.2**
  - [x] 2.6 Write Property 6 — Remote path generation follows date-structured format: `@given(prefix, timestamp, filename)` asserts path matches `<prefix>/YYYY/MM/DD/<filename>` with correct UTC date components — **Validates: Requirements 3.6**
  - [x] 2.7 Write Property 7 — Retry logic exhausts exactly N attempts before alerting: `@given(outcomes, max_retries)` asserts attempts_made equals index of first success + 1 or max_retries if all fail; success iff any outcome is True within max_retries — **Validates: Requirements 3.4**
  - [x] 2.8 Write Property 8 — Alert messages always contain required fields: `@given(backup_type, timestamp, reason, credentials)` asserts message contains all three fields and no credential value appears in output — **Validates: Requirements 7.1, 9.2**
  - [x] 2.9 Write Property 9 — Daily summary aggregation is correct over any 24-hour window: `@given(entries, window_start)` asserts successful count equals valid-integrity entries in window; failed count equals invalid-integrity entries in window — **Validates: Requirements 4.4, 7.3**
  - [x] 2.10 Write Property 10 — Stale backup detection uses correct time comparison: `@given(last_ts, now)` asserts `is_backup_stale` returns `True` iff elapsed seconds > 43200 — **Validates: Requirements 7.4**
  - [x] 2.11 Write Property 11 — Remote transfer method dispatch is exhaustive: `@given(method=st.text())` asserts correct routing for `"rclone"`, `"s3"`, `"rsync"` and `ValueError` for all other values — **Validates: Requirements 3.2**
  - [x] 2.12 Add `@settings(max_examples=100)` to all property tests; tag each with `# Feature: database-backup-redundancy, Property N: <property_text>`
  - [x] 2.13 Run `cd backend && pytest tests/test_backup_properties.py -v` and confirm all 11 properties pass
  - _Requirements: 1.2, 1.3, 1.4, 2.4, 3.2, 3.4, 3.6, 4.3, 4.4, 6.4, 7.1, 7.3, 7.4, 8.2, 8.3, 9.2_


- [x] 3. Write example-based unit tests in `backend/tests/test_backup_lib.py`
  - Test `generate_backup_filename` with a fixed timestamp produces the exact expected string for both `scheduled` and `pre-deploy` types
  - Test `parse_backup_filename` raises `ValueError` on malformed filenames (missing prefix, wrong separator, non-numeric date parts, missing `.dump` extension)
  - Test `filter_by_retention` with an empty file list returns an empty list; with `retention_days=0` returns an empty list
  - Test `compare_checksums` returns `False` when strings differ by exactly one character
  - Test `lookup_manifest_entry` with duplicate filenames returns the first match; with empty manifest returns `None`
  - Test `generate_remote_path` with a midnight UTC timestamp produces correct YYYY/MM/DD path components
  - Test `retry_controller` with all-failing `attempt_fn` and `max_retries=3` returns `(False, 3)`; with success on first attempt returns `(True, 1)`
  - Test `format_alert_message` does not include credential values in output
  - Test `aggregate_daily_summary` with entries exactly on the window boundary (start inclusive, end exclusive)
  - Test `is_backup_stale` returns `False` when elapsed time is exactly 12 hours (boundary — not stale)
  - Test `dispatch_transfer_method` raises `ValueError` for empty string and whitespace-only input
  - Run `cd backend && pytest tests/test_backup_lib.py -v` and confirm all tests pass
  - _Requirements: 1.2, 1.3, 1.4, 3.2, 3.4, 3.6, 4.3, 7.1, 7.4, 8.2, 8.3, 9.2_

- [x] 4. Write `backup.sh` — Main Backup Orchestrator
  - Add shebang `#!/usr/bin/env bash` and `set -euo pipefail`
  - Source `/home/deploy/backup.conf`; verify permissions are `600` owned by `deploy:deploy` via `stat`; log error and exit 1 on failure
  - Validate required config variables (`PGDATABASE`, `BACKUP_DIR`, `LOG_FILE`, `REMOTE_METHOD`, `ALERT_METHOD`); abort without writing credential values to the log
  - Verify `$BACKUP_DIR` exists and is writable; log error, send alert, and exit 1 if not
  - Determine output filename via `python3 /home/deploy/backup_lib.py generate-filename`; use `pre-deploy` type when `--pre-deploy` flag is passed
  - Run `pg_dump -Fc -d "$PGDATABASE" -f "$BACKUP_DIR/$FILENAME"`; on non-zero exit, log with UTC timestamp, send alert, and exit 1
  - Compute SHA-256 checksum via `sha256sum`; run `pg_restore --list` for integrity check; record `valid` or `invalid`
  - Append NDJSON manifest entry via `python3 /home/deploy/backup_lib.py serialize-manifest` with all 8 fields
  - Call `/home/deploy/redis-backup.sh`; log and alert on failure but do NOT exit — PostgreSQL backup continues regardless
  - Transfer dump file via `rclone copy` to `$RCLONE_BUCKET/$RCLONE_PATH_PREFIX/YYYY/MM/DD/$FILENAME`; verify remote file size matches local size
  - Implement retry loop: up to `$REMOTE_RETRY_COUNT` attempts with `$REMOTE_RETRY_DELAY` seconds between; alert after all retries exhausted
  - If all steps succeeded, delete local backups older than `$LOCAL_RETENTION_DAYS` days; skip deletion on any failure
  - Delete remote backups older than `$REMOTE_RETENTION_DAYS` days via `rclone delete --min-age`
  - Log completion with UTC timestamp; set permissions `chmod 750 /home/deploy/backup.sh`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 7.1, 7.2, 7.5, 7.6, 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 5. Write `redis-backup.sh` — Redis RDB Snapshot
  - Add shebang `#!/usr/bin/env bash` and `set -euo pipefail`; source `/home/deploy/backup.conf`
  - Ping Redis via `wsl -d Ubuntu -- redis-cli ping`; on failure, log error, send alert, and `return 1` (non-blocking)
  - Record pre-BGSAVE `LASTSAVE` value; send `wsl -d Ubuntu -- redis-cli BGSAVE`
  - Poll `wsl -d Ubuntu -- redis-cli LASTSAVE` every 5 seconds; exit loop when value changes from pre-BGSAVE value
  - If poll loop exceeds `$REDIS_BGSAVE_TIMEOUT` seconds, log error, send alert, and `return 1` without copying any file
  - Copy `$REDIS_RDB_PATH` from WSL to `$BACKUP_DIR/redis_YYYY-MM-DD_HH-MM-SS.rdb`; on copy failure, log error, send alert, and `return 1` without deleting existing Redis backups
  - Delete Redis backup files matching `redis_*.rdb` older than `$REDIS_RETENTION_DAYS` days
  - Include shared `send_alert()` function; set permissions `chmod 750 /home/deploy/redis-backup.sh`
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.5_


- [x] 6. Write `wal-archive.sh` — WAL Segment Archiver
  - Add shebang `#!/usr/bin/env bash` (no `set -e` — PostgreSQL requires explicit exit codes)
  - Accept two positional arguments: `$1` = full path to WAL segment (`%p`), `$2` = WAL segment filename (`%f`)
  - Source `/home/deploy/backup.conf` to read `WAL_ARCHIVE_DIR`, `LOG_FILE`, `ALERT_METHOD`, `ALERT_EMAIL`, `WEBHOOK_URL`
  - Check free space in `$WAL_ARCHIVE_DIR` via `df`; if below 500 MB threshold, log error, send alert, and exit 1
  - Copy `$1` to `$WAL_ARCHIVE_DIR/$2` using `cp --preserve`; exit 0 on success
  - On copy failure, log segment filename and exit code to `$LOG_FILE`, send alert, and exit 1 (PostgreSQL will retry)
  - Include `send_alert()` function inline; set permissions `chmod 755 /home/deploy/wal-archive.sh` (readable by `postgres` user)
  - _Requirements: 5.1, 5.2, 5.6, 5.7, 7.1, 7.5_

- [x] 7. Write `pg-basebackup.sh` — Weekly Base Backup
  - Add shebang `#!/usr/bin/env bash` and `set -euo pipefail`; source `/home/deploy/backup.conf`
  - Generate timestamped output directory: `$BACKUP_DIR/base/base_YYYY-MM-DD_HH-MM-SS`
  - Run `pg_basebackup -D "$OUTPUT_DIR" -Fp -Xs -P -U deploy`; on non-zero exit, log error, send alert, and exit 1
  - Log completion with UTC timestamp and output directory path to `$LOG_FILE`
  - Check age of most recent base backup in `$BACKUP_DIR/base/`; if older than 7 days, send stale-base-backup alert
  - Purge WAL segments in `$WAL_ARCHIVE_DIR` older than `$WAL_RETENTION_DAYS` days via `find -mtime +N`
  - Set permissions `chmod 750 /home/deploy/pg-basebackup.sh`
  - _Requirements: 5.3, 5.4, 5.5, 7.1, 7.5_

- [x] 8. Write `daily-summary.sh` — Daily Status Report
  - Add shebang `#!/usr/bin/env bash` and `set -euo pipefail`; source `/home/deploy/backup.conf`
  - Compute `WINDOW_START` as 24 hours before current UTC time
  - Call `python3 /home/deploy/backup_lib.py aggregate-summary "$MANIFEST_FILE" "$WINDOW_START" "$WINDOW_END"` to get successful and failed counts
  - Compute total storage used in `$BACKUP_DIR` in megabytes via `du -sm`
  - Find UTC timestamp of most recent successful backup (last manifest entry with `"integrity": "valid"`)
  - If most recent successful backup is older than 12 hours, include stale-backup warning in summary body
  - Format and send summary via `send_alert` with subject `"Daily Backup Summary — YYYY-MM-DD"`
  - Log summary generation completion to `$LOG_FILE`; set permissions `chmod 750 /home/deploy/daily-summary.sh`
  - _Requirements: 4.4, 7.3, 7.4, 7.5_

- [x] 9. Write `restore.sh` — Database Restore Script
  - Add shebang `#!/usr/bin/env bash` and `set -euo pipefail`; accept one positional argument `<backup_filename>`; print usage and exit 1 if not provided
  - Print timestamped "script start" to stdout: `[YYYY-MM-DDTHH:MM:SSZ] restore.sh starting — target: <filename>`
  - Source `/home/deploy/backup.conf`; look up `<backup_filename>` in manifest via `python3 /home/deploy/backup_lib.py lookup-manifest`; abort with error if not found
  - Print `[timestamp] manifest lookup complete`
  - Compute SHA-256 via `sha256sum`; compare to manifest value via `python3 /home/deploy/backup_lib.py compare-checksums`; if mismatch, print both expected and computed checksums and exit 1
  - Print `[timestamp] checksum verification passed`
  - Create safety backup `pre_restore_<ISO8601>.dump` via `pg_dump -Fc`; abort with error if pg_dump fails
  - Print `[timestamp] safety backup created: <safety_filename>`
  - Run `pg_restore -d "$PGDATABASE" --clean --if-exists "$BACKUP_DIR/<backup_filename>"`; print `[timestamp] pg_restore complete`
  - Run `flask db upgrade head` from `/home/deploy/app/backend/`; print error and exit 1 on failure
  - Print `[timestamp] flask db upgrade complete — restore finished`
  - Set permissions `chmod 750 /home/deploy/restore.sh` owned by `deploy:deploy`
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_


- [x] 10. Create `/home/deploy/backup.conf` and required directories
  - Create `/home/deploy/backup.conf` with all fields: `PGDATABASE`, `PGUSER`, `BACKUP_DIR`, `WAL_ARCHIVE_DIR`, `LOG_FILE`, `REMOTE_METHOD`, `RCLONE_REMOTE`, `RCLONE_BUCKET`, `RCLONE_PATH_PREFIX`, `LOCAL_RETENTION_DAYS=30`, `REMOTE_RETENTION_DAYS=30`, `REDIS_RETENTION_DAYS=7`, `WAL_RETENTION_DAYS=7`, `ALERT_METHOD`, `ALERT_EMAIL`, `MSMTP_ACCOUNT`, `WEBHOOK_URL`, `REDIS_RDB_PATH`, `REDIS_BGSAVE_TIMEOUT=300`, `REMOTE_CONNECT_TIMEOUT=30`, `REMOTE_RETRY_COUNT=3`, `REMOTE_RETRY_DELAY=300`
  - Set permissions: `chmod 600 /home/deploy/backup.conf && chown deploy:deploy /home/deploy/backup.conf`
  - Create required directories: `mkdir -p /home/deploy/backups /home/deploy/wal-archive /home/deploy/logs /home/deploy/backups/base`
  - Verify `stat -c "%a %U:%G" /home/deploy/backup.conf` outputs `600 deploy:deploy`
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 11. Apply PostgreSQL configuration changes for WAL archiving and passwordless auth
  - Add to `/etc/postgresql/<version>/main/postgresql.conf`: `wal_level = replica`, `archive_mode = on`, `archive_command = '/home/deploy/wal-archive.sh %p %f'`, `archive_timeout = 300`
  - Reload PostgreSQL: `sudo systemctl reload postgresql`
  - Configure passwordless access: add peer auth entry to `pg_hba.conf` (`local real_estate_analysis deploy peer`) OR create `/home/deploy/.pgpass` with permissions `600`
  - Verify `pg_dump -Fc -d real_estate_analysis -f /tmp/test_auth.dump` succeeds as `deploy` user without password prompt; remove test file
  - Verify WAL archiving is active: `psql -c "SHOW archive_mode;"` returns `on`; confirm a segment appears in `/home/deploy/wal-archive/` after `SELECT pg_switch_wal()`
  - _Requirements: 1.7, 5.1, 5.2_

- [x] 12. Set up cron schedule for the `deploy` user
  - Add 5 cron entries via `crontab -u deploy -e`: `0 2 * * *` (backup.sh), `0 10 * * *` (backup.sh), `0 18 * * *` (backup.sh), `0 1 * * 0` (pg-basebackup.sh), `30 0 * * *` (daily-summary.sh) — all redirecting stdout and stderr to `/home/deploy/logs/backup.log`
  - Verify all 5 entries are installed: `crontab -u deploy -l`
  - Confirm `MAILTO` is set or suppressed in the crontab header to avoid duplicate email delivery
  - _Requirements: 1.1, 2.1, 5.3, 7.3_

- [x] 13. Integrate pre-deploy backup hook into `scripts/deploy.sh`
  - Read `scripts/deploy.sh` to identify the correct insertion point (after pre-deploy health checks, before `git checkout`)
  - Insert pre-deploy backup block before the first deployment step: call `backup.sh --pre-deploy`; block deploy on failure with `exit 1`
  - Renumber any existing step labels to maintain sequential ordering
  - Verify syntax: `bash -n scripts/deploy.sh`
  - Confirm `backup.sh --pre-deploy` appears before `git checkout` and `flask db upgrade` in the script
  - _Requirements: 2.2, 2.3, 2.4_

- [x] 14. Write `/home/deploy/BACKUP_RUNBOOK.md`
  - Write **Backup Schedule** section: all 5 cron jobs with UTC times and descriptions
  - Write **Backup Locations** section: local path, WAL archive path, remote path structure
  - Write **Listing Available Backups** section with exact `grep` command against `backup_manifest.log`
  - Write **Restore from Local Snapshot** section: step-by-step `restore.sh <filename>` invocation with example output
  - Write **Point-In-Time Recovery (PITR)** section: stop PostgreSQL, restore base backup, configure `restore_command` and `recovery_target_time`, start PostgreSQL, verify
  - Write **RTO/RPO Targets** table: local snapshot (RPO ≤ 8h, RTO ≤ 30min), remote backup (RPO ≤ 8h, RTO ≤ 2h), WAL/PITR (RPO ≤ 5min, RTO ≤ 1h)
  - Write **Verifying Database Health After Restore** section: `flask db current`, row count queries for `leads`, `analysis_sessions`, `comparable_sales`, application health endpoint
  - Write **Disaster Recovery Checklist (VPS Completely Lost)** section: 11-step numbered checklist from provisioning through confirming application health
  - Write **Alert Troubleshooting** section: testing `msmtp` manually, testing webhook with `curl`, locating alert delivery failures in `backup.log`
  - Set permissions `chmod 644 /home/deploy/BACKUP_RUNBOOK.md`
  - _Requirements: 10.1, 10.2, 10.3_

- [x] 15. Smoke test verification checklist
  - Verify cron entries: `crontab -u deploy -l` shows all 5 entries (02:00, 10:00, 18:00, 00:30, Sunday 01:00)
  - Verify all 6 scripts are executable by `deploy`: `test -x` for backup.sh, restore.sh, redis-backup.sh, wal-archive.sh, pg-basebackup.sh, daily-summary.sh
  - Verify `restore.sh` permissions: `stat -c "%a %U:%G" /home/deploy/restore.sh` outputs `750 deploy:deploy`
  - Verify `backup.conf` permissions: `stat -c "%a %U:%G" /home/deploy/backup.conf` outputs `600 deploy:deploy`
  - Verify WAL archiving: `psql -c "SHOW archive_mode;"` returns `on`; `SHOW archive_command` returns `wal-archive.sh` path
  - Verify rclone remote: `rclone listremotes` shows configured B2 (or other) remote
  - Run end-to-end backup: `/home/deploy/backup.sh` as `deploy`; confirm dump file, manifest entry with `"integrity": "valid"`, Redis RDB file, remote file in B2, no errors in `backup.log`
  - Verify pre-deploy hook: `bash -n scripts/deploy.sh` passes; `backup.sh --pre-deploy` appears before `git checkout`
  - Verify Python tests pass: `cd backend && pytest tests/test_backup_properties.py tests/test_backup_lib.py -v`
  - Verify `backup_lib.py` CLI: `python3 /home/deploy/backup_lib.py generate-filename scheduled` outputs correct filename format
  - _Requirements: 1.1, 1.2, 1.7, 2.2, 5.1, 5.2, 8.7, 9.3, 9.4_


## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["10", "11"],
      "description": "Foundation: backup.conf, directories, and PostgreSQL WAL configuration — prerequisites for all scripts"
    },
    {
      "wave": 2,
      "tasks": ["1"],
      "description": "backup_lib.py pure Python helper module — core logic used by all scripts and tests"
    },
    {
      "wave": 3,
      "tasks": ["2", "3"],
      "description": "Property-based tests and unit tests — validate backup_lib.py before scripts depend on it"
    },
    {
      "wave": 4,
      "tasks": ["5", "6", "7", "8", "9"],
      "description": "Individual scripts: redis-backup.sh, wal-archive.sh, pg-basebackup.sh, daily-summary.sh, restore.sh — can be implemented in parallel"
    },
    {
      "wave": 5,
      "tasks": ["4"],
      "description": "backup.sh main orchestrator — depends on redis-backup.sh (task 5) and backup_lib.py (task 1)"
    },
    {
      "wave": 6,
      "tasks": ["12", "13"],
      "description": "Cron schedule and deploy.sh pre-deploy hook — integrate after backup.sh is verified"
    },
    {
      "wave": 7,
      "tasks": ["14"],
      "description": "BACKUP_RUNBOOK.md — document after all scripts are complete"
    },
    {
      "wave": 8,
      "tasks": ["15"],
      "description": "Smoke test verification checklist — final end-to-end validation on the VPS"
    }
  ]
}
```

## Notes

- All scripts run as the `deploy` Linux user on the Hetzner VPS. No Docker is used anywhere in this system.
- Redis runs via WSL Ubuntu. All Redis commands use `wsl -d Ubuntu -- redis-cli`. The RDB file is at `/var/lib/redis/dump.rdb` inside WSL (configurable via `REDIS_RDB_PATH` in `backup.conf`).
- `backup_lib.py` must be placed at `/home/deploy/backup_lib.py` on the VPS. For local development and testing, the test files in `backend/tests/` import it by adding `/home/deploy` to `sys.path` or by symlinking/copying the file to a location on `PYTHONPATH`.
- The `wal-archive.sh` script is invoked by the `postgres` OS user (via PostgreSQL's `archive_command`), not the `deploy` user. It must be world-readable (`chmod 755`) and must not rely on `deploy`-only resources.
- Property-based tests use Hypothesis, which is already a project dependency (see `backend/.hypothesis/`). No new test dependencies are required.
- The `retry_controller` function in `backup_lib.py` accepts a callable `attempt_fn` but does NOT call `time.sleep` — the delay between retries is the shell script's responsibility. This keeps the Python function pure and testable without mocking time.
- Credential values must never appear in log files or alert messages. The `format_alert_message` function enforces this by accepting a `credentials` list and asserting none of those values appear in the output.
- The manifest file (`backup_manifest.log`) is append-only NDJSON. Never rewrite the entire file — always append a new line per backup run.
