#!/usr/bin/env bash
# Zero-surprise update with automatic pre-update backup and instant rollback path.
#   sudo bash deploy/scripts/update.sh /path/to/new-release.zip
set -euo pipefail
ZIP="${1:?release zip}"
BASE=/opt/irs-road; APP=$BASE/app; VENV=$BASE/venv; ETC=/etc/irs-road
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

PREV=$(readlink -f "$APP")
echo ">> Backup before update"; /opt/irs-road/app/deploy/scripts/backup.sh

TMP=$(mktemp -d); unzip -q "$ZIP" -d "$TMP"
SRC=$(find "$TMP" -maxdepth 2 -name wsgi.py -printf '%h\n' | head -1)
REL="$BASE/releases/$(date +%Y%m%d%H%M%S)"; cp -a "$SRC" "$REL"; rm -rf "$TMP"
install -d -o irsroad -g irsroad -m 750 "$REL/instance"
chown -R irsroad:irsroad "$REL"; chmod -R g+rX,o-rwx "$REL"

"$VENV/bin/pip" install -r "$REL/requirements.txt" >/dev/null

echo ">> Migrations"
sudo -u irsroad bash -c "set -a; . $ETC/irs-road.env; cd $REL; $VENV/bin/flask db upgrade && $VENV/bin/flask seed"

ln -sfn "$REL" "$APP"
systemctl reload irs-road || systemctl restart irs-road
sleep 2
if curl -fsS --unix-socket /run/irs-road/gunicorn.sock http://localhost/healthz >/dev/null; then
  echo ">> Update OK → $REL (previous: $PREV)"
  ls -1dt $BASE/releases/* | tail -n +6 | xargs -r rm -rf   # keep 5 releases
else
  echo "!! Health check failed — rolling back code to $PREV"
  ln -sfn "$PREV" "$APP"; systemctl restart irs-road
  echo "!! If the migration changed the schema, restore the DB dump taken above (docs/BACKUP_RESTORE.md)."
  exit 1
fi
