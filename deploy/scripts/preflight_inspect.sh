#!/usr/bin/env bash
# READ-ONLY inspection of the existing Ubuntu 24.04 server BEFORE deploying.
# It changes nothing. Review its output, then follow docs/DEPLOYMENT.md.
#   sudo bash deploy/scripts/preflight_inspect.sh road.example.ly | tee preflight.txt
set -u
DOMAIN="${1:-road.example.ly}"
hr(){ printf '\n==== %s ====\n' "$1"; }

hr "OS"; lsb_release -ds 2>/dev/null || cat /etc/os-release | head -3; uname -r
hr "Disk / memory"; df -h / /var /opt 2>/dev/null | sort -u; free -h
hr "Python"; command -v python3 && python3 --version; dpkg -l python3-venv 2>/dev/null | tail -1
hr "Nginx"; nginx -v 2>&1; systemctl is-active nginx
echo "-- enabled sites:"; ls -l /etc/nginx/sites-enabled/ 2>/dev/null
echo "-- server_name usage (conflicts with ${DOMAIN}?):"; grep -RIn "server_name" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null
grep -RIl "${DOMAIN}" /etc/nginx/ 2>/dev/null && echo "!! ${DOMAIN} already referenced in nginx config" || echo "ok: ${DOMAIN} not used yet"
echo "-- nginx -t:"; nginx -t 2>&1 | tail -2
hr "MariaDB"; (mariadb --version || mysql --version) 2>/dev/null; systemctl is-active mariadb 2>/dev/null || systemctl is-active mysql
echo "-- existing databases (names only):"; mariadb -N -e "SHOW DATABASES" 2>/dev/null || echo "(run as root to list)"
mariadb -N -e "SELECT User,Host FROM mysql.user WHERE User LIKE 'irs%'" 2>/dev/null
hr "Gunicorn / systemd units"; systemctl list-units --type=service --no-pager | grep -Ei "gunicorn|irs|nextcloud|php|roundcube|postfix" || true
ls /etc/systemd/system/ | grep -i irs || echo "ok: no irs-road unit yet"
hr "Listening sockets"; ss -ltnp 2>/dev/null | awk 'NR==1||/:80 |:443 |:3306 |:8000 |:5000 /'
hr "Let's Encrypt"; command -v certbot && certbot --version 2>&1; ls /etc/letsencrypt/live/ 2>/dev/null
ls /etc/letsencrypt/renewal-hooks/*/ 2>/dev/null
hr "Postfix (for password-reset mail)"; systemctl is-active postfix 2>/dev/null; postconf -h myhostname 2>/dev/null
hr "Target paths"; for p in /opt/irs-road /etc/irs-road /var/lib/irs-road /var/log/irs-road; do [ -e "$p" ] && echo "EXISTS: $p" || echo "free:   $p"; done
id irsroad 2>/dev/null && echo "user irsroad exists" || echo "user irsroad does not exist yet"
hr "Firewall"; ufw status 2>/dev/null | head -10
echo; echo "Inspection complete — nothing was modified."
