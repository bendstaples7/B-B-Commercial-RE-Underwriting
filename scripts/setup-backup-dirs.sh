#!/usr/bin/env bash
# setup-backup-dirs.sh
# Run once on the VPS after deploying /home/deploy/backup.conf.
# Creates required directories and sets correct permissions on backup.conf.
# Must be run as root or a user with sudo privileges.

set -euo pipefail

CONF_FILE="/home/deploy/backup.conf"

echo "==> Creating required backup directories"
mkdir -p /home/deploy/backups \
         /home/deploy/wal-archive \
         /home/deploy/logs \
         /home/deploy/backups/base

echo "    Created: /home/deploy/backups"
echo "    Created: /home/deploy/wal-archive"
echo "    Created: /home/deploy/logs"
echo "    Created: /home/deploy/backups/base"

echo ""
echo "==> Setting ownership on backup directories"
chown -R deploy:deploy /home/deploy/backups \
                       /home/deploy/wal-archive \
                       /home/deploy/logs

echo "    Ownership set to deploy:deploy"

echo ""
echo "==> Setting permissions on backup directories"
chmod 700 /home/deploy/backups
chmod 700 /home/deploy/backups/base
chmod 700 /home/deploy/wal-archive
chmod 750 /home/deploy/logs

# wal-archive must be writable by the postgres OS user (runs wal-archive.sh)
chown deploy:postgres /home/deploy/wal-archive
chmod 770 /home/deploy/wal-archive
echo "    wal-archive: deploy:postgres 770 (writable by postgres for WAL archiving)"

echo ""
echo "    NOTE: After deploying wal-archive.sh, run:"
echo "      chmod 755 /home/deploy/wal-archive.sh"
echo "      (postgres OS user must be able to execute it via archive_command)"

echo ""
echo "==> Setting permissions on $CONF_FILE"
if [[ ! -f "$CONF_FILE" ]]; then
    echo "ERROR: $CONF_FILE does not exist."
    echo "       Copy scripts/backup.conf.example to $CONF_FILE and fill in real values first."
    exit 1
fi

chmod 600 "$CONF_FILE"
chown deploy:deploy "$CONF_FILE"

echo ""
echo "==> Verifying $CONF_FILE permissions"
STAT_OUTPUT=$(stat -c "%a %U:%G" "$CONF_FILE")
EXPECTED="600 deploy:deploy"

if [[ "$STAT_OUTPUT" == "$EXPECTED" ]]; then
    echo "    OK: $CONF_FILE — $STAT_OUTPUT"
else
    echo "ERROR: Expected '$EXPECTED' but got '$STAT_OUTPUT'"
    echo "       Check that this script is run as root or with sudo."
    exit 1
fi

echo ""
echo "==> Setup complete. All directories created and backup.conf secured."
echo ""
echo "    Next steps:"
echo "    1. Edit $CONF_FILE with real values (rclone bucket, alert email, etc.)"
echo "    2. Configure rclone: rclone config"
echo "    3. Configure msmtp: /etc/msmtprc or ~/.msmtprc"
echo "    4. Install cron entries: crontab -u deploy -e"
