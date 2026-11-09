# النسخ الاحتياطي والاستعادة

## ما يُنسخ (يومياً 02:40 عبر `irs-road-backup.timer`)
| العنصر | الملف |
|---|---|
| قاعدة البيانات (dump متّسق `--single-transaction`) | `irs_road.sql.gz` |
| صور البلاغات | `uploads.tar.gz` |
| الإعدادات (env، Nginx vhost، وحدة systemd) | `config.tar.gz` |
| الإصدار الجاري | `release.txt` |
| بصمات التحقق | `SHA256SUMS` |

الموقع: `/var/backups/irs-road/<YYYYMMDD-HHMMSS>/` (700 root) — الاحتفاظ 14 يوماً (`KEEP_DAYS`).

### الإعداد لمرة واحدة
```bash
sudo install -m 600 /dev/null /etc/irs-road/backup.cnf
sudo tee /etc/irs-road/backup.cnf >/dev/null <<'EOF'
[client]
user=irs_backup
password=CHANGE_ME_BACKUP_PASSWORD
EOF
sudo install -m 600 /dev/null /etc/irs-road/admin.cnf    # حساب irs_app (للاستعادة فقط)
sudo systemctl enable --now irs-road-backup.timer
sudo systemctl start irs-road-backup.service && ls /var/backups/irs-road/
```

### نسخة خارج الخادم (موصى به بشدة)
```bash
rsync -a --delete /var/backups/irs-road/ backup@nas.example.ly:/backups/irs-road/
```

## الاستعادة
```bash
sudo bash /opt/irs-road/app/deploy/scripts/restore.sh /var/backups/irs-road/20261108-024000 --db --uploads
# --config لاستعادة ملفات الإعداد أيضاً
```
يتحقق السكربت من البصمات، يطلب تأكيداً كتابياً، يوقف الخدمة، يستعيد، ويعيد ربط الإصدار المسجّل.

## استعادة جزئية / حالات خاصة
* **فشل ترحيل:** `flask db downgrade <rev>`؛ وإن تعذّر: استعادة `--db` من النسخة التي أخذها `update.sh` قبل التحديث.
* **التراجع عن الكود فقط:** `ln -sfn /opt/irs-road/releases/<prev> /opt/irs-road/app && systemctl restart irs-road`.
* **اختبار الاستعادة:** شهرياً على قاعدة `irs_road_restoretest` منفصلة للتأكد من صلاحية النسخ.
