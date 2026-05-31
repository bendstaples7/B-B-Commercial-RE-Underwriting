# Requirements Document

## Introduction

This feature implements multiple redundant backup layers for the B and B Real Estate Analyzer platform to ensure no data is ever lost. The platform runs on a Hetzner VPS with a PostgreSQL database containing leads, interactions/audit trails, scoring weights, users, analysis sessions, comparable sales, and marketing lists. Redis is used as a Celery task queue broker. The backup strategy provides three independent layers of protection: automated local snapshots on the VPS, automated off-site transfers to remote storage, and continuous WAL-based point-in-time recovery capability. Monitoring and alerting ensure backup failures are detected immediately.

## Glossary

- **Backup_System**: The collection of scripts, schedules, and services that create, transfer, verify, and restore database backups.
- **Local_Backup**: A compressed PostgreSQL dump stored on the VPS filesystem in a dedicated backup directory.
- **Remote_Backup**: A copy of a local backup transferred to an off-site storage destination (e.g., Backblaze B2, AWS S3, or SFTP remote host).
- **WAL**: Write-Ahead Log — PostgreSQL's transaction log, used for point-in-time recovery (PITR).
- **PITR**: Point-In-Time Recovery — the ability to restore the database to any specific moment in time using a base backup plus WAL segments.
- **Retention_Policy**: The rules governing how long backups are kept before deletion.
- **Backup_Manifest**: A metadata file recording the backup filename, timestamp, size, and SHA-256 checksum.
- **Restore_Script**: A script that automates the process of restoring the database from a backup file.
- **Health_Check**: A verification step that confirms a backup completed successfully and the resulting file is valid.
- **Redis_Backup**: A snapshot of the Redis RDB file capturing the current Celery task queue state.
- **Deploy_User**: The `deploy` Linux user that owns the application and runs backup scripts on the VPS.
- **Backup_Dir**: The local directory `/home/deploy/backups/` used to store local backup files.
- **Offsite_Dir**: The remote storage bucket or path where remote backups are stored.

---

## Requirements

### Requirement 1: Automated Local PostgreSQL Backups (REFINED)

**User Story:** As a platform operator, I want automated local database backups created on a regular schedule, so that I have a recent copy of all data available on the VPS without manual intervention.

#### Acceptance Criteria

1. THE Backup_System SHALL create a compressed PostgreSQL dump of the `real_estate_analysis` database using `pg_dump --format=custom` via a cron job or systemd timer scheduled to run at least once daily, starting at 02:00 UTC.
2. WHEN a local backup completes successfully, THE Backup_System SHALL store the dump file in `/home/deploy/backups/` with a filename that includes the UTC timestamp in the format `backup_YYYY-MM-DD_HH-MM-SS.dump`.
3. WHEN a local backup completes successfully, THE Backup_System SHALL write an entry to `/home/deploy/backups/backup_manifest.log` recording the filename, UTC timestamp, size in bytes of the dump file as stored on disk, and SHA-256 checksum of the dump file.
4. WHEN the current backup run completes successfully, THE Backup_System SHALL delete local backup files in `/home/deploy/backups/` older than 30 days; IF the current backup run fails, THEN THE Backup_System SHALL skip deletion to preserve the most recent available backups.
5. IF a `pg_dump` command exits with a non-zero status, THEN THE Backup_System SHALL log the error with a UTC timestamp to `/home/deploy/logs/backup.log` and send an alert to the operator email address configured in the backup environment.
6. IF `/home/deploy/backups/` does not exist or is not writable by the `deploy` user at the start of a backup run, THEN THE Backup_System SHALL log the error to `/home/deploy/logs/backup.log` and send an alert without attempting the `pg_dump` command.
7. THE Backup_System SHALL run backups as the `deploy` user without requiring interactive password entry (using `.pgpass` or equivalent peer authentication).

---

### Requirement 2: Multiple Daily Backup Frequency (REFINED)

**User Story:** As a platform operator, I want backups taken multiple times per day, so that the maximum data loss window is limited to a few hours rather than a full day.

#### Acceptance Criteria

1. THE Backup_System SHALL create local PostgreSQL backups at a minimum of 3 times per day (at 02:00, 10:00, and 18:00 UTC) to limit the maximum data loss window to 8 hours or less.
2. WHEN the deploy workflow is invoked, THE Backup_System SHALL trigger a PRE_DEPLOY backup no more than 5 minutes before the first deployment step begins.
3. WHEN the deploy workflow triggers a pre-deploy backup, THE Backup_System SHALL write the dump file to `/home/deploy/backups/` before the deployment step begins; IF the backup does not complete successfully, THEN the deployment SHALL be blocked and the deploy script SHALL exit with a non-zero status.
4. THE Backup_System SHALL label pre-deploy backups with the filename pattern `backup_pre-deploy_YYYY-MM-DD_HH-MM-SS.dump`.
5. IF a scheduled backup run fails to produce a valid dump file in `/home/deploy/backups/`, THEN THE Backup_System SHALL log the failure with a UTC timestamp to `/home/deploy/logs/backup.log` and send an alert to the configured notification channel.

---

### Requirement 3: Off-Site Remote Backup Transfer (REFINED)

**User Story:** As a platform operator, I want backups automatically copied to a remote off-site location, so that data is protected even if the VPS itself is lost, corrupted, or destroyed.

#### Acceptance Criteria

1. WHEN a local backup completes successfully, THE Backup_System SHALL transfer a copy of the dump file to the configured Offsite_Dir within 1 hour of the local backup completing.
2. THE Backup_System SHALL support at least one of the following remote transfer methods: Backblaze B2 via `rclone`, AWS S3 via `aws s3 cp`, or SFTP via `rsync` over SSH — configurable via an environment variable; IF the configured transfer method is missing or invalid, THEN THE Backup_System SHALL log the error and send an alert without attempting the transfer.
3. WHEN a remote transfer completes, THE Backup_System SHALL verify the remote file size matches the local file size; IF the sizes do not match, THEN THE Backup_System SHALL treat the transfer as failed and apply the retry logic defined in criterion 4.
4. IF a remote transfer fails due to a transient error (e.g., network timeout, temporary unavailability), THEN THE Backup_System SHALL retry the transfer up to 3 times with a 5-minute delay between attempts, log each failure, and send an alert after all retries are exhausted; IF the failure is non-retryable (e.g., authentication error, invalid credentials), THEN THE Backup_System SHALL log the failure and send an immediate alert without retrying.
5. THE Backup_System SHALL retain remote backups for a minimum of 30 days, independent of the local retention policy.
6. THE Backup_System SHALL store remote backups in a directory structure organized by date (e.g., `YYYY/MM/DD/backup_YYYY-MM-DD_HH-MM-SS.dump`).
7. WHEN a remote transfer completes successfully, THE Backup_System SHALL delete remote backup files in Offsite_Dir older than 30 days.

---

### Requirement 4: Backup Integrity Verification (REFINED)

**User Story:** As a platform operator, I want each backup verified after creation, so that I can be confident a backup is actually restorable before I need it in an emergency.

#### Acceptance Criteria

1. WHEN a local backup file is created, THE Backup_System SHALL verify the dump file is valid by running `pg_restore --list` against it and confirming the command exits with status 0.
2. WHEN backup integrity verification fails, THE Backup_System SHALL set the integrity field in the Backup_Manifest entry for that file to "invalid", write a log entry to `/home/deploy/logs/backup.log` containing the filename, UTC timestamp, and the exit code returned by `pg_restore --list`, and send an alert via the configured notification channel.
3. WHEN a backup integrity check completes (pass or fail), THE Backup_System SHALL record the result ("valid" or "invalid") in the Backup_Manifest entry for that backup file.
4. WHEN a daily summary is generated, THE Backup_System SHALL include the count of successful and failed integrity checks for the preceding 24-hour period.

---

### Requirement 5: Point-In-Time Recovery (WAL Archiving) (REFINED)

**User Story:** As a platform operator, I want continuous WAL archiving enabled, so that I can recover the database to any point in time and minimize data loss to minutes rather than hours.

#### Acceptance Criteria

1. THE Backup_System SHALL configure PostgreSQL WAL archiving (`archive_mode = on`, `archive_command`) to copy completed WAL segment files to a designated WAL archive directory on the VPS.
2. WHEN a WAL segment is archived successfully, THE Backup_System SHALL confirm the archive command exits with status 0 before PostgreSQL recycles the segment.
3. THE Backup_System SHALL take a full base backup using `pg_basebackup` at least once per week on a scheduled day and time.
4. WHEN the most recent base backup is older than 7 days, THE Backup_System SHALL send an alert via the configured notification channel identifying the timestamp of the most recent base backup.
5. THE Backup_System SHALL retain WAL segments from the most recent base backup to the present in the WAL archive directory, and SHALL purge WAL segments older than 7 days that are no longer needed to recover from any retained base backup.
6. IF the WAL archive command fails for any segment, THEN THE Backup_System SHALL write a log entry to `/home/deploy/logs/backup.log` identifying the failed segment name and the exit code, and SHALL send an alert via the configured notification channel within 5 minutes of the failure.
7. IF the WAL archive directory has insufficient free space to store a new WAL segment, THEN THE Backup_System SHALL log the error to `/home/deploy/logs/backup.log` and send an alert via the configured notification channel.

---

### Requirement 6: Redis Backup (REFINED)

**User Story:** As a platform operator, I want the Redis task queue state backed up, so that in-flight Celery tasks are not permanently lost after a server failure.

#### Acceptance Criteria

1. THE Backup_System SHALL produce at least one successful Redis RDB snapshot copy in the configured Backup_Dir every 24 hours.
2. WHEN a Redis backup is initiated, THE Backup_System SHALL send a `BGSAVE` command to the Redis instance and wait up to 300 seconds for the save to complete before copying the `dump.rdb` file.
3. IF the `BGSAVE` command does not complete within 300 seconds, THEN THE Backup_System SHALL abort the Redis backup, write an error entry to `/home/deploy/logs/backup.log`, and send an alert via the configured notification channel without copying any stale RDB file.
4. THE Backup_System SHALL delete Redis backup files in the configured Backup_Dir that are older than 7 days after each successful Redis backup.
5. IF the Redis instance is not reachable when a backup is attempted, THEN THE Backup_System SHALL write an error entry to `/home/deploy/logs/backup.log` and send an alert via the configured notification channel, but SHALL NOT block or fail the PostgreSQL backup process.
6. IF copying the `dump.rdb` file to the configured Backup_Dir fails, THEN THE Backup_System SHALL write an error entry to `/home/deploy/logs/backup.log`, send an alert via the configured notification channel, and SHALL NOT delete any existing Redis backup files.

---

### Requirement 7: Backup Monitoring and Alerting (REFINED)

**User Story:** As a platform operator, I want immediate notification when any backup step fails, so that I can intervene before the backup gap grows large enough to risk data loss.

#### Acceptance Criteria

1. WHEN any of the following events occur — a `pg_dump` failure, a remote transfer failure after all retries are exhausted, a backup integrity check failure, a WAL archive failure, or a Redis backup failure — THE Backup_System SHALL send an alert notification that includes the backup type, the UTC timestamp of the failure, and a description of the failure reason.
2. THE Backup_System SHALL support at least one notification channel configurable via environment variable: email via `sendmail`/`msmtp`, or HTTP webhook (e.g., Slack, Discord, or a custom endpoint).
3. THE Backup_System SHALL generate a daily backup status summary and deliver it via the configured notification channel within 60 minutes of 00:00 UTC, reporting the count of successful backups, failed backups, total storage used in `/home/deploy/backups/` in megabytes, and the UTC timestamp of the most recent successful backup.
4. WHEN the most recent successful backup is older than 12 hours, THE Backup_System SHALL send a stale-backup alert via the configured notification channel that includes the UTC timestamp of the most recent successful backup and the number of hours elapsed since that backup.
5. THE Backup_System SHALL log all backup events (start, success, failure, transfer, verification) with UTC timestamps to `/home/deploy/logs/backup.log`.
6. IF the configured notification channel is unreachable or returns an error when an alert is sent, THEN THE Backup_System SHALL write an entry to `/home/deploy/logs/backup.log` recording the failed delivery attempt, the UTC timestamp, and the error returned by the notification channel.

---

### Requirement 8: Automated Restore Script (REFINED)

**User Story:** As a platform operator, I want a tested restore script, so that I can recover the database quickly and confidently during an incident without having to figure out the restore procedure under pressure.

#### Acceptance Criteria

1. WHEN the Restore_Script is invoked with a backup filename argument, THE Restore_Script SHALL restore the specified dump to the `real_estate_analysis` database using `pg_restore`.
2. WHEN invoked, THE Restore_Script SHALL look up the specified backup filename in the Backup_Manifest located in the same directory as the backup file; IF the Backup_Manifest is absent, unparseable, or does not contain an entry for the specified file, THEN THE Restore_Script SHALL abort and print an error message without modifying the database.
3. IF the SHA-256 checksum of the specified backup file does not match the value recorded in the Backup_Manifest, THEN THE Restore_Script SHALL abort and print an error message that includes both the expected checksum from the manifest and the computed checksum of the file, without modifying the database.
4. WHEN checksum verification passes, THE Restore_Script SHALL create a safety backup of the current database state named `pre_restore_<ISO8601_timestamp>.dump` before overwriting it with the restore target; IF the safety backup fails, THEN THE Restore_Script SHALL abort without modifying the database.
5. WHEN the `pg_restore` command completes, THE Restore_Script SHALL run `flask db upgrade head`; IF `flask db upgrade head` exits with a non-zero status, THEN THE Restore_Script SHALL print an error message and exit with a non-zero status.
6. WHILE the Restore_Script is executing, THE Restore_Script SHALL print a timestamped progress log entry to stdout for each of the following steps: script start, manifest lookup, checksum verification, safety backup creation, pg_restore execution, and flask db upgrade.
7. THE Restore_Script SHALL be located at `/home/deploy/restore.sh` with permissions `750` owned by `deploy:deploy`.

---

### Requirement 9: Backup Configuration and Secrets Management (REFINED)

**User Story:** As a platform operator, I want all backup credentials and configuration stored securely, so that remote storage access keys are not exposed in scripts or logs.

#### Acceptance Criteria

1. THE Backup_System SHALL read credentials (remote storage access keys, notification webhook URLs, SMTP passwords) from environment variables first, falling back to a dedicated secrets file; IF a required credential is absent from both sources, THEN THE Backup_System SHALL log an error to `/home/deploy/logs/backup.log` and abort the backup run without attempting any backup operation.
2. THE Backup_System SHALL never write credential values to `/home/deploy/logs/backup.log` or any other log file.
3. THE Backup_System SHALL store the remote storage configuration (provider, bucket name, path prefix) in a dedicated config file at `/home/deploy/backup.conf` with permissions `600`.
4. THE Backup_System SHALL verify that the secrets file has permissions `600` and is owned by `deploy:deploy` at the start of each backup run; IF the permissions or ownership are incorrect, THEN THE Backup_System SHALL log an error and abort the backup run.
5. WHERE a remote storage provider is configured, THE Backup_System SHALL validate that the remote storage connection is reachable within a 30-second timeout during the first backup run after configuration; IF the connection check succeeds, THE Backup_System SHALL log the result to `/home/deploy/logs/backup.log`; IF the connection check fails or times out, THE Backup_System SHALL log the failure without including credential values and abort the backup run.

---

### Requirement 10: Backup Documentation and Runbook (REFINED)

**User Story:** As a platform operator, I want a runbook documenting the backup and restore procedures, so that any operator can execute a recovery without prior knowledge of the system.

#### Acceptance Criteria

1. THE Backup_System SHALL include a runbook file at `/home/deploy/BACKUP_RUNBOOK.md` documenting: the backup schedule, the location of local and remote backups, how to list available backups, how to invoke the Restore_Script, how to perform a PITR restore, and how to verify database health after a restore completes.
2. THE Backup_System runbook SHALL document the expected RTO and RPO for each backup layer expressed as concrete time ranges: local snapshot (RPO ≤ 8 hours, RTO ≤ 30 minutes), remote backup (RPO ≤ 8 hours, RTO ≤ 2 hours), and WAL/PITR (RPO ≤ 5 minutes, RTO ≤ 1 hour).
3. THE Backup_System runbook SHALL include a step-by-step disaster recovery checklist for the scenario where the VPS is completely lost, covering: provisioning a new server, installing dependencies, downloading the most recent remote backup, running the Restore_Script, verifying data integrity, and resuming application services.
