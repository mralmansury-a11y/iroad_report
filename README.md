# الطريق الدولي ليبيا — International Road Services – Libya

منصة رسمية ثنائية اللغة (عربي/إنجليزي) لإبلاغ مستخدمي الطريق الدولي عن الأعطال ومتابعتها، وإدارة معالجتها من قِبل
إدارة خدمات الطريق الدولي — الجهاز الوطني للتنمية. موقع متجاوب + تطبيق ويب تقدّمي (PWA) قابل للتثبيت + لوحة تحكم إدارية.

**التقنيات:** Python 3 · Flask (Application Factory + Blueprints) · MariaDB · SQLAlchemy/Alembic · Flask-Login/WTF/Babel/Limiter ·
Bootstrap 5 (RTL/LTR) · Vanilla JS · Leaflet/OpenStreetMap · Chart.js · Web Push (VAPID) · Gunicorn · Nginx · systemd.

## المحتويات
| المستند | الموضوع |
|---|---|
| [docs/01_PHASE1_FIGMA_ANALYSIS.md](docs/01_PHASE1_FIGMA_ANALYSIS.md) | تحليل Figma، الشاشات، الهوية البصرية، الحدود |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | المعمارية، الوحدات، الأدوار، سير العمل، API |
| [docs/DATABASE.md](docs/DATABASE.md) | مخطط MariaDB والترحيلات |
| [docs/LOCALIZATION.md](docs/LOCALIZATION.md) | العربية/الإنجليزية و RTL/LTR |
| [docs/PWA.md](docs/PWA.md) | Manifest، Service Worker، العمل دون اتصال، الإشعارات |
| [docs/SECURITY.md](docs/SECURITY.md) | ضوابط الأمان |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | النشر على Ubuntu 24.04 القائم + استكشاف الأخطاء |
| [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) | النسخ الاحتياطي والاستعادة والتراجع |
| [docs/EMAIL.md](docs/EMAIL.md) | الربط بخادم البريد mail.iroad.ly (Postfix/PostfixAdmin) |
| [docs/TESTING_REPORT.md](docs/TESTING_REPORT.md) | تقرير الاختبارات |

## التشغيل المحلي (للتطوير)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # اضبط FLASK_CONFIG=development و DATABASE_URL لقاعدة MariaDB محلية
# قاعدة MariaDB محلية:  sudo mariadb < deploy/sql/create_database.sql   (بعد تعديل كلمة المرور)
flask db upgrade
flask seed --demo               # بيانات مرجعية + بيانات عرض (للتطوير فقط)
flask create-admin --name "Admin" --email admin@example.ly
flask --debug run               # http://127.0.0.1:5000  (الـ PWA يعمل على localhost)
```

### على Windows (سياسات أمان تمنع `flask.exe` أو `Activate.ps1`)
لا حاجة لتفعيل البيئة؛ استدعِ Python البيئة مباشرة وشغّل Flask كوحدة:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m flask db upgrade
.\.venv\Scripts\python.exe -m flask seed --demo
.\.venv\Scripts\python.exe -m flask --debug run
```
أو من VS Code: اختر المفسّر `.venv\Scripts\python.exe` ثم **F5** (الإعداد جاهز في `.vscode/launch.json`).
ملف `.env` المحلي: `FLASK_CONFIG=development`، `SECRET_KEY=...`، `DATABASE_URL=sqlite:///dev.db` (أو MariaDB). اترك `INSTANCE_PATH` و`UPLOAD_FOLDER` و`LOG_DIR` دون ضبط.

## الأوامر
| الأمر | الوظيفة |
|---|---|
| `flask db upgrade` / `flask db migrate -m "…"` / `flask db downgrade -1` | إدارة الترحيلات |
| `flask seed` | الأدوار، الصلاحيات، الحالات، التصنيفات، الفرق، الإعدادات (آمن للتكرار) |
| `flask seed --demo` | بيانات عرض **غير رسمية** (قواطع ونقاط ونماذج بلاغات) — ليست للإنتاج |
| `flask create-admin [--role superadmin|admin|supervisor|employee]` | إنشاء/ترقية حساب إداري (كلمة المرور تُطلب تفاعلياً) |
| `flask vapid-keys` | توليد مفاتيح Web Push |
| `flask cleanup-push` | حذف اشتراكات Push التالفة |
| `flask send-test-mail you@iroad.ly` | اختبار الربط بخادم البريد |
| `python scripts/build_translations.py` | استخراج النصوص وتحديث/ترجمة كتالوجات ar/en والتحقق من الاكتمال |
| `python scripts/build_icons.py logo.png` | توليد أيقونات التطبيق من الشعار الرسمي عالي الدقة |
| `pytest -q` | تشغيل الاختبارات (57) |

## الإعداد
كل الإعدادات الحساسة في متغيرات البيئة (`.env.example` موثّق بالكامل). الإعدادات التشغيلية (نطاق «البلاغات القريبة»، النقاط،
أرقام الدعم، السماح ببلاغ الزائر، مركز الخريطة…) تُدار من **لوحة التحكم ← إعدادات النظام**.

## اللغات
العربية افتراضية؛ زر التبديل في الترويسة وصفحة «اللغة»؛ يُحفظ الاختيار للزائر (كوكي) وفي حساب المستخدم. التفاصيل في
`docs/LOCALIZATION.md`. لإضافة/تعديل نص: `_("English text")` ← `python scripts/build_translations.py` ← ترجمة في `translations/ar/LC_MESSAGES/messages.po`.

## صيانة الـ PWA
* بصمة ذاكرة الـ Service Worker تتغيّر تلقائياً مع أي تعديل في `app/static` — لا حاجة لرفع رقم إصدار يدوياً.
* بعد النشر يرى المستخدم «يتوفر إصدار جديد ← تحديث».
* لا تُضِف مسارات خاصة إلى `PUBLIC_PAGES` في `sw.js`؛ أي صفحة شخصية يجب أن تُرسل `Cache-Control: no-store`.

## النشر والتحديث
راجع `docs/DEPLOYMENT.md`: `preflight_inspect.sh` (قراءة فقط) ← `install.sh` ← الترحيلات ← systemd ← Nginx + Let's Encrypt.
التحديث: `update.sh new.zip` (نسخة احتياطية ← إصدار جديد ← ترحيل ← فحص صحة ← تراجع آلي عند الفشل).

## ملاحظات مهمة قبل التشغيل الرسمي
1. **الشعارات:** الحالية مقتطعة من لقطة Figma (منخفضة الدقة). صدّر الشعارين الرسميين وشغّل `scripts/build_icons.py`.
2. **بيانات الطريق:** القواطع والنقاط المرجعية في `--demo` توضيحية. حمّل نقاط المسح الرسمية (كم، خط العرض، خط الطول) من لوحة التحكم.
3. **بلاطات الخرائط:** خادم OSM العام مناسب لحركة محدودة فقط وفق سياسة الاستخدام؛ للحمل العالي استخدم خادم بلاطات خاصاً (`MAP_TILE_URL`).
4. لم يُختبر النشر على خادم الإنتاج الفعلي بعد — يتم ذلك وفق القسم 8 من دليل النشر.
