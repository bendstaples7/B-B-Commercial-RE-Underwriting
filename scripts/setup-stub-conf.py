#!/usr/bin/env python3
"""
setup-stub-conf.py — Create a stub /home/deploy/backup.conf if none exists.

Called by the deploy workflow to ensure backup.sh can run without blocking
the deploy on a freshly provisioned VPS. Operators should replace the stub
with real values to enable full backup functionality.
"""
import os
import shutil

CONF = "/home/deploy/backup.conf"
DIRS = [
    "/home/deploy/backups",
    "/home/deploy/wal-archive",
    "/home/deploy/logs",
    "/home/deploy/backups/base",
]

if not os.path.exists(CONF):
    content = "\n".join([
        "# Auto-generated stub backup.conf - replace with real values.",
        "# See scripts/backup.conf.example for all available options.",
        'PGDATABASE="real_estate_analysis"',
        'PGUSER="app_user"',
        'PGHOST="localhost"',
        'BACKUP_DIR="/home/deploy/backups"',
        'WAL_ARCHIVE_DIR="/home/deploy/wal-archive"',
        'LOG_FILE="/home/deploy/logs/backup.log"',
        'REMOTE_METHOD=""',
        'RCLONE_TARGETS=""',
        'RCLONE_REMOTE=""',
        'RCLONE_BUCKET=""',
        'RCLONE_PATH_PREFIX="backups"',
        'REMOTE_UPLOAD_HOUR_UTC="10"',
        "LOCAL_RETENTION_DAYS=30",
        "REMOTE_RETENTION_DAYS=14",
        "REDIS_RETENTION_DAYS=7",
        "WAL_RETENTION_DAYS=7",
        'ALERT_METHOD="email"',
        'ALERT_EMAIL=""',
        'MSMTP_ACCOUNT="default"',
        'WEBHOOK_URL=""',
        'REDIS_RDB_PATH="/var/lib/redis/dump.rdb"',
        "REDIS_BGSAVE_TIMEOUT=300",
        "REMOTE_CONNECT_TIMEOUT=30",
        "REMOTE_RETRY_COUNT=3",
        "REMOTE_RETRY_DELAY=300",
        'REDIS_CMD_PREFIX=""',
    ]) + "\n"
    with open(CONF, "w") as f:
        f.write(content)
    os.chmod(CONF, 0o600)
    shutil.chown(CONF, user="deploy", group="deploy")
    print("NOTE: Created stub /home/deploy/backup.conf")
else:
    print("NOTE: /home/deploy/backup.conf already exists - skipping stub creation")

for d in DIRS:
    os.makedirs(d, exist_ok=True)
print("NOTE: Backup directories ensured")
