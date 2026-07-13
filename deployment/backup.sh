#!/bin/bash
#
# PartsBin nightly backup: pg_dump + uploads tarball -> /mnt/backup staging
# (synced onward to CITADEL NFS /mnt/DATA/Home/BKUP/PARTSBIN/). 14-day retention.
#
# Cron (root): 15 2 * * * /opt/partsbin/deployment/backup.sh
#
set -euo pipefail

DB_NAME=partsbin
UPLOADS_DIR=/opt/partsbin/uploads
STAGING_DIR=/mnt/backup/partsbin
RETENTION_DAYS=14
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$STAGING_DIR"

# Database dump
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$STAGING_DIR/partsbin-db-$STAMP.sql.gz"

# Uploads tarball
if [[ -d $UPLOADS_DIR ]]; then
    tar -czf "$STAGING_DIR/partsbin-uploads-$STAMP.tar.gz" -C "$(dirname "$UPLOADS_DIR")" uploads
fi

# Retention
find "$STAGING_DIR" -name 'partsbin-*' -mtime +"$RETENTION_DAYS" -delete

echo "Backup complete: $STAGING_DIR/partsbin-{db,uploads}-$STAMP.*"
