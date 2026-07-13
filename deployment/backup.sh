#!/bin/bash
#
# PartsBin nightly backup: pg_dump + uploads tarball written directly to the
# CITADEL BKUP NFS mount (nas.internal:/mnt/DATA/Home/BKUP on /mnt/nfs/backup),
# same pattern as GarmentGallery2. 14-day retention.
#
# Cron (root): 15 2 * * * /opt/partsbin/deployment/backup.sh
#
set -euo pipefail

DB_NAME=partsbin
UPLOADS_DIR=/opt/partsbin/uploads
STAGING_DIR=/mnt/nfs/backup/PartsBin

ls /mnt/nfs/backup >/dev/null 2>&1 || true   # trigger systemd automount
if ! mountpoint -q /mnt/nfs/backup; then
    echo "ERROR: /mnt/nfs/backup (CITADEL BKUP NFS) not mounted; skipping backup" >&2
    exit 1
fi
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
