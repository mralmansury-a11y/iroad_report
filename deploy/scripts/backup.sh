#!/usr/bin/env bash
# Nightly backup: MariaDB dump + uploaded photos + configuration. Keeps 14 days.
# Credentials for the dump come from /etc/irs-road/backup.cnf (chmod 600):
#   [client]
#   user=irs_backup
#   password=...
set -euo pipefail
DEST=/var/backups/irs-road; KEEP_DAYS=${KEEP_DAYS:-14}
TS=$(date +%Y%m%d-%H%M%S); D="$DEST/$TS"
umask 077; mkdir -p "$D"

mariadb-dump --defaults-extra-file=/etc/irs-road/backup.cnf --single-transaction --quick --routines \
  --default-character-set=utf8mb4 irs_road | gzip -9 > "$D/irs_road.sql.gz"
tar -C /var/lib/irs-road -czf "$D/uploads.tar.gz" uploads
tar -C / -czf "$D/config.tar.gz" etc/irs-road etc/nginx/sites-available/irs-road.conf etc/systemd/system/irs-road.service 2>/dev/null || true
readlink -f /opt/irs-road/app > "$D/release.txt"
( cd "$D" && sha256sum ./* > SHA256SUMS )

find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "backup ok: $D"
# Copy off-server as well (e.g. rsync to the agency NAS / Nextcloud) — see docs/BACKUP_RESTORE.md
