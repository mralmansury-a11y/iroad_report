#!/usr/bin/env bash
# First installation on an EXISTING Ubuntu 24.04 server (isolated; does not touch other apps).
# Prerequisites: preflight_inspect.sh reviewed, DNS for the domain points to the server,
# MariaDB database/user created with deploy/sql/create_database.sql.
#
#   sudo bash deploy/scripts/install.sh /path/to/irs-road-release.zip road.example.ly
set -euo pipefail
ZIP="${1:?release zip}"; DOMAIN="${2:?domain}"
BASE=/opt/irs-road; APP=$BASE/app; VENV=$BASE/venv
ETC=/etc/irs-road; DATA=/var/lib/irs-road; LOGS=/var/log/irs-road

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
for p in "$APP" /etc/systemd/system/irs-road.service /etc/nginx/sites-available/irs-road.conf; do
  [ -e "$p" ] && { echo "!! $p already exists — use update.sh instead."; exit 1; }
done

apt-get install -y --no-install-recommends python3-venv python3-dev unzip libjpeg-turbo8 >/dev/null

id irsroad >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin irsroad
usermod -aG irsroad www-data   # lets nginx read the socket and static files (group only)

install -d -o irsroad -g irsroad -m 750 "$BASE" "$DATA" "$DATA/uploads" "$DATA/instance" "$LOGS"
install -d -o root -g irsroad -m 750 "$ETC"
install -d -o root -g root -m 700 /var/backups/irs-road

TMP=$(mktemp -d); unzip -q "$ZIP" -d "$TMP"
SRC=$(find "$TMP" -maxdepth 2 -name wsgi.py -printf '%h\n' | head -1)
mkdir -p "$BASE/releases"; REL="$BASE/releases/$(date +%Y%m%d%H%M%S)"
cp -a "$SRC" "$REL"; ln -sfn "$REL" "$APP"
install -d -o irsroad -g irsroad -m 750 "$REL/instance"
chown -R irsroad:irsroad "$REL"; chmod -R g+rX,o-rwx "$REL"; rm -rf "$TMP"

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null
"$VENV/bin/pip" install -r "$APP/requirements.txt"
chown -R irsroad:irsroad "$VENV"

if [ ! -f "$ETC/irs-road.env" ]; then
  install -o root -g irsroad -m 640 "$APP/.env.example" "$ETC/irs-road.env"
  SK=$(python3 -c "import secrets;print(secrets.token_hex(48))")
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SK|" "$ETC/irs-road.env"
  echo ">> Edit $ETC/irs-road.env (DATABASE_URL, VAPID keys, MAIL_*) then re-run the remaining steps below."
fi

echo ">> Next steps (manual, reviewed):"
cat <<EOF
  1) nano $ETC/irs-road.env                         # database URL, mail, VAPID
  2) sudo -u irsroad bash -c 'set -a; . $ETC/irs-road.env; cd $APP; $VENV/bin/flask vapid-keys'   # paste into env
  3) sudo -u irsroad bash -c 'set -a; . $ETC/irs-road.env; cd $APP; $VENV/bin/flask db upgrade && $VENV/bin/flask seed'
  4) sudo -u irsroad bash -c 'set -a; . $ETC/irs-road.env; cd $APP; $VENV/bin/flask create-admin --name "..." --email admin@... '
  5) cp $APP/deploy/systemd/irs-road*.service $APP/deploy/systemd/irs-road-backup.timer /etc/systemd/system/
     systemctl daemon-reload && systemctl enable --now irs-road && systemctl enable --now irs-road-backup.timer
  6) sed "s/road.example.ly/$DOMAIN/g" $APP/deploy/nginx/irs-road.conf > /etc/nginx/sites-available/irs-road.conf
     (first issue the certificate — see docs/DEPLOYMENT.md §7) then:
     ln -s /etc/nginx/sites-available/irs-road.conf /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
  7) curl -fsS https://$DOMAIN/healthz
EOF
