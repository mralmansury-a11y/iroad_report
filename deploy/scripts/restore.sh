#!/usr/bin/env bash
# Restore a backup folder produced by backup.sh.
#   sudo bash deploy/scripts/restore.sh /var/backups/irs-road/20261108-024000 [--db] [--uploads] [--config]
set -euo pipefail
D="${1:?backup dir}"; shift || true
[ -f "$D/SHA256SUMS" ] && ( cd "$D" && sha256sum -c SHA256SUMS )
read -r -p "This will OVERWRITE current data from $D. Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || exit 1
systemctl stop irs-road
for a in "$@"; do
  case "$a" in
    --db)      gunzip -c "$D/irs_road.sql.gz" | mariadb --defaults-extra-file=/etc/irs-road/admin.cnf irs_road ;;
    --uploads) mv /var/lib/irs-road/uploads "/var/lib/irs-road/uploads.before-restore.$(date +%s)"
               tar -C /var/lib/irs-road -xzf "$D/uploads.tar.gz"; chown -R irsroad:irsroad /var/lib/irs-road/uploads ;;
    --config)  tar -C / -xzf "$D/config.tar.gz" ;;
  esac
done
if [ -f "$D/release.txt" ] && [ -d "$(cat "$D/release.txt")" ]; then ln -sfn "$(cat "$D/release.txt")" /opt/irs-road/app; fi
systemctl start irs-road
nginx -t && systemctl reload nginx
echo "restore finished"
