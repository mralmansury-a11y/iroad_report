# دليل النشر على خادم Ubuntu 24.04 القائم

> المبدأ: **عزل كامل**. لا يُعاد تثبيت MariaDB أو Nginx، ولا يُعدَّل `nginx.conf` أو أي موقع آخر،
> ولا تُمسّ قواعد بيانات أو شهادات أو خدمات Nextcloud / Roundcube / Postfix / PostfixAdmin.

| العنصر | القيمة المخصّصة للمشروع |
|---|---|
| مستخدم النظام | `irsroad` (بلا Shell) |
| الكود | `/opt/irs-road/releases/<timestamp>` والرابط `/opt/irs-road/app` |
| البيئة الافتراضية | `/opt/irs-road/venv` |
| الإعدادات والأسرار | `/etc/irs-road/irs-road.env` (640 root:irsroad) |
| البيانات (الصور) | `/var/lib/irs-road/uploads` |
| السجلات | `/var/log/irs-road/` |
| المقبس | `/run/irs-road/gunicorn.sock` |
| خدمة systemd | `irs-road.service` + `irs-road-backup.timer` |
| موقع Nginx | `/etc/nginx/sites-available/irs-road.conf` |
| قاعدة البيانات / المستخدم | `irs_road` / `irs_app`@localhost (+ `irs_backup`) |

## 1. الفحص المسبق (قراءة فقط)
```bash
unzip irs-road-*.zip -d ~/irs-road-release && cd ~/irs-road-release/roadsite
sudo bash deploy/scripts/preflight_inspect.sh road.example.ly | tee ~/preflight.txt
```
تحقّق من: عدم استخدام النطاق في Nginx، عدم وجود `/opt/irs-road`، حالة MariaDB، المساحة، وجود certbot.

## 2. قاعدة البيانات
```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32     # كلمة مرور irs_app
sudo cp deploy/sql/create_database.sql /root/irs_db.sql && sudo nano /root/irs_db.sql   # ضع كلمات المرور
sudo mariadb < /root/irs_db.sql && sudo shred -u /root/irs_db.sql
sudo mariadb -e "SHOW GRANTS FOR 'irs_app'@'localhost'"
```

## 3. تثبيت التطبيق
```bash
sudo bash deploy/scripts/install.sh ~/irs-road-*.zip road.example.ly
sudo nano /etc/irs-road/irs-road.env       # DATABASE_URL, MAIL_*, VAPID_* (SECRET_KEY مولّد تلقائياً)
```

## 4. مفاتيح Web Push
```bash
sudo -u irsroad bash -c 'set -a; . /etc/irs-road/irs-road.env; cd /opt/irs-road/app; /opt/irs-road/venv/bin/flask vapid-keys'
# انسخ السطرين إلى /etc/irs-road/irs-road.env
```

## 5. الترحيلات والبيانات المرجعية والمسؤول
```bash
R='set -a; . /etc/irs-road/irs-road.env; cd /opt/irs-road/app; PATH=/opt/irs-road/venv/bin:$PATH'
sudo -u irsroad bash -c "$R; flask db upgrade && flask seed"
sudo -u irsroad bash -c "$R; flask create-admin --name 'مدير النظام' --email it@example.ly --role superadmin"
```
> لا تستخدم `flask seed --demo` في الإنتاج. حمّل القواطع والنقاط المرجعية الرسمية من **لوحة التحكم ← القواطع**.

## 6. Gunicorn + systemd
```bash
sudo cp /opt/irs-road/app/deploy/systemd/irs-road.service /opt/irs-road/app/deploy/systemd/irs-road-backup.* /etc/systemd/system/
sudo cp /opt/irs-road/app/deploy/logrotate/irs-road /etc/logrotate.d/irs-road
sudo systemctl daemon-reload
sudo systemctl enable --now irs-road
sudo systemctl status irs-road --no-pager
curl -s --unix-socket /run/irs-road/gunicorn.sock http://localhost/healthz    # {"ok": true}
```

## 7. Nginx + HTTPS (Let's Encrypt)
```bash
sudo mkdir -p /var/www/letsencrypt
sed 's/road.example.ly/YOUR.DOMAIN/g' /opt/irs-road/app/deploy/nginx/irs-road-http-only.conf | sudo tee /etc/nginx/sites-available/irs-road.conf
sudo ln -s /etc/nginx/sites-available/irs-road.conf /etc/nginx/sites-enabled/irs-road.conf
sudo nginx -t && sudo systemctl reload nginx                      # لا تعيد التحميل إن فشل الفحص
sudo certbot certonly --webroot -w /var/www/letsencrypt -d YOUR.DOMAIN   # شهادة جديدة لهذا النطاق فقط
sed 's/road.example.ly/YOUR.DOMAIN/g' /opt/irs-road/app/deploy/nginx/irs-road.conf | sudo tee /etc/nginx/sites-available/irs-road.conf
sudo nginx -t && sudo systemctl reload nginx
```
* إن لم يوجد `/etc/letsencrypt/options-ssl-nginx.conf` احذف سطري `include` و`ssl_dhparam`.
* التجديد يتم عبر مؤقّت certbot القائم؛ أضف إعادة التحميل إن لزم:
  `--deploy-hook "systemctl reload nginx"` (دون تعديل الخطافات الموجودة).

## 8. التحقق من التشغيل الفعلي
```bash
curl -I https://YOUR.DOMAIN/                       # 200 + CSP + HSTS
curl -s https://YOUR.DOMAIN/manifest.webmanifest | head
curl -sI https://YOUR.DOMAIN/sw.js | grep -i service-worker-allowed
sudo tail -f /var/log/irs-road/gunicorn-error.log /var/log/nginx/irs-road.error.log
```
ثم: تسجيل الدخول للوحة التحكم، إرسال بلاغ تجريبي بصورة، تغيير حالته، تثبيت التطبيق على هاتف، تفعيل الإشعارات، اختبار وضع الطيران.

## 9. التحديث والتراجع
```bash
sudo bash /opt/irs-road/app/deploy/scripts/update.sh ~/irs-road-new.zip   # نسخة احتياطية → إصدار جديد → ترحيل → فحص صحة → تراجع آلي عند الفشل
# تراجع يدوي إلى إصدار سابق:
ls -1dt /opt/irs-road/releases/*
sudo ln -sfn /opt/irs-road/releases/<previous> /opt/irs-road/app && sudo systemctl restart irs-road
# إن تضمّن الإصدار ترحيلاً: sudo -u irsroad bash -c "$R; flask db downgrade <revision>" أو استعادة النسخة (BACKUP_RESTORE.md)
```

## 10. استكشاف الأخطاء
| العَرَض | الفحص |
|---|---|
| 502 Bad Gateway | `systemctl status irs-road`؛ صلاحية المقبس (www-data ضمن مجموعة irsroad: `id www-data`) |
| الخدمة لا تبدأ | `journalctl -u irs-road -n 100`؛ غالباً `DATABASE_URL`/`SECRET_KEY` |
| `Access denied` لقاعدة البيانات | `SHOW GRANTS`؛ ترميز كلمة المرور في URL (`%40` بدل `@`) |
| الصور لا تُرفع | `client_max_body_size`؛ ملكية `/var/lib/irs-road/uploads`؛ `MAX_IMAGE_MB` |
| الصفحات القديمة تظهر بعد التحديث | يظهر شريط «يتوفر إصدار جديد»؛ أو من أدوات المطوّر: Application ← Service Workers ← Update |
| لا تصل الإشعارات | مفاتيح VAPID، HTTPS، إذن المتصفح، `push_subscriptions.failure_count` |
| لا تصل رسائل الاستعادة | إعداد MAIL_*؛ `journalctl -u postfix` |
| النص الإنجليزي يظهر بالعربية | `python scripts/build_translations.py` ثم إعادة التشغيل |
