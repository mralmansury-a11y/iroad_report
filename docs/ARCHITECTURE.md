# المعمارية التقنية (Architecture)

## 1. نظرة عامة

منصة واحدة (Monolith منظّم) تخدم تجربتين بنفس الخادم وقاعدة البيانات:

```
 المتصفح / PWA المثبّت
      │ HTTPS
 ┌────▼─────────────── Nginx (vhost مستقل irs-road) ──────────────┐
 │  /static/* ← ملفات ثابتة مباشرة      /uploads/* ← 404 دائماً     │
 │  بقية المسارات ← unix:/run/irs-road/gunicorn.sock               │
 └────┬────────────────────────────────────────────────────────────┘
      │
 ┌────▼──── Gunicorn (systemd: irs-road.service, user irsroad) ────┐
 │  Flask Application Factory                                      │
 │  ├─ main          الرئيسية، الحساب، اللغة، الدعم، الخريطة، PWA   │
 │  ├─ auth          الدخول، التسجيل، الخروج، استعادة كلمة المرور   │
 │  ├─ reports       الإبلاغ، القائمة، التفاصيل، المتابعة، المرفقات │
 │  ├─ notifications التنبيهات داخل التطبيق                         │
 │  ├─ admin         لوحة التحكم (RBAC)                             │
 │  └─ api/v1        JSON للواجهة وللتطبيقات المستقبلية             │
 │  services/  ← منطق الأعمال (مستقل عن المسارات)                   │
 └────┬───────────────────────────────┬────────────────────────────┘
      │ SQLAlchemy (PyMySQL)          │ pywebpush (VAPID)
 ┌────▼────── MariaDB irs_road ──┐    └─► خدمات Push للمتصفحات
 └───────────────────────────────┘
 /var/lib/irs-road/uploads  ← الصور (خارج جذر الويب)
```

## 2. هيكل المشروع

```
roadsite/
├── app/
│   ├── __init__.py         ← Application Factory، الأمان، الأخطاء، اختيار اللغة
│   ├── extensions.py       ← db, migrate, login, csrf, babel, limiter
│   ├── models/             ← base, user, road, report, team, notification, system
│   ├── services/           ← reports (سير العمل)، stats، geo، notify، uploads، rbac، settings، audit، mail
│   ├── auth/ main/ reports/ notifications/ admin/ api/   ← Blueprints
│   ├── utils/              ← i18n (تنسيق محلي)، validators، safe redirects
│   ├── templates/          ← base, _macros, public/, auth/, reports/, notifications/, admin/, errors/
│   ├── static/             ← css/app.css، js/ (app, home, report-form, map, admin, analytics, sw)، vendor/، fonts/، icons/
│   ├── seed.py  cli.py
├── translations/ar|en/LC_MESSAGES/messages.po|.mo
├── migrations/             ← Alembic (Flask-Migrate)
├── tests/                  ← pytest (47 اختباراً)
├── deploy/                 ← gunicorn، systemd، nginx، sql، scripts، logrotate
├── docs/  scripts/  config.py  wsgi.py  requirements.txt  .env.example
```

## 3. قرارات معمارية رئيسية

| القرار | البديل | سبب الاختيار |
|---|---|---|
| Server-rendered Jinja + Vanilla JS + Bootstrap 5 | SPA (React/Vue) | التزاماً بالمواصفات؛ أداء أفضل على شبكات ضعيفة؛ SEO؛ صيانة أبسط |
| طبقة `services/` منفصلة | منطق داخل المسارات | نفس القواعد تخدم HTML و API والتطبيقات المستقبلية |
| جداول ترجمة لكل كيان قابل للتهيئة | أعمدة `name_ar/name_en` | قابلية إضافة لغات دون تعديل المخطط؛ مطابق لاشتراط المواصفات |
| نصوص الإشعارات تُولَّد بالعربية والإنجليزية لحظة الإنشاء | توليدها عند العرض | تثبيت النص التاريخي، وإرسال Push بلغة كل مشترك |
| تحويل GPS→كم عبر نقاط مرجعية مساحية (`road_points`) | خدمة خارجية | لا اعتماد خارجي؛ دقة يتحكم بها المالك؛ لا اختلاق مواقع |
| Unix socket لـ Gunicorn | منفذ TCP | لا تعارض مع تطبيقات الخادم القائمة |
| الصور تُعاد ترميزها وتُخزَّن خارج `static` | تخزين مباشر | إزالة EXIF/GPS، تحييد الملفات المزدوجة، منع التنفيذ |
| CSP صارمة بلا سكربتات مضمّنة | السماح بـ inline | تقليل سطح XSS |

## 4. الأدوار والصلاحيات (RBAC)

| الصلاحية | مستخدم | موظف | مشرف | مسؤول | مسؤول أعلى |
|---|:-:|:-:|:-:|:-:|:-:|
| الإبلاغ ومتابعة بلاغاته | ✔ | ✔ | ✔ | ✔ | ✔ |
| `reports.view_assigned` عرض المسند إليه/لفريقه | | ✔ | ✔ | ✔ | ✔ |
| `reports.update_status` (الموظف: مسند إليه فقط، قيد التنفيذ ← تم الإصلاح) | | ✔ | ✔ | ✔ | ✔ |
| `reports.internal_notes` | | ✔ | ✔ | ✔ | ✔ |
| `reports.view_all` / `reports.review` / `reports.assign` | | | ✔ | ✔ | ✔ |
| `analytics.view`، `announcements.manage`، `messages.manage`، `sections.manage`، `users.view` | | | ✔ | ✔ | ✔ |
| `users.manage`، `employees.manage`، `teams.manage`، `categories.manage`، `settings.manage`، `audit.view` | | | | ✔ | ✔ |
| `roles.manage` (منح أدوار الإدارة العليا) | | | | | ✔ |

قاعدة إضافية: لا يمنح أي مستخدم دوراً بمستوى يساوي مستواه أو يعلوه، ولا يعدّل أدوار نفسه.

## 5. سير عمل البلاغ

```
           ┌──────────► مرفوض (سبب إلزامي يظهر للمُبلِّغ) ──► قيد المراجعة (إعادة فتح)
 جديد ──► قيد المراجعة ──► تم الإسناد ──► قيد التنفيذ ──► تم الإصلاح ──► قيد التنفيذ (إعادة فتح)
   └──────────► تم الإسناد (الإسناد المباشر)
```
* كل انتقال يُسجّل في `report_status_history` (من، إلى، بواسطة، الوقت، ملاحظة عامة، ملاحظة داخلية).
* أول خروج من «جديد» يضبط `first_response_at` (لحساب متوسط الاستجابة)، و«تم الإصلاح» يضبط `resolved_at`.
* نقاط المساهمة تُمنح مرة واحدة (قيد فريد `user_id + report_id + reason`).
* الإشعار للمُبلِّغ عند كل تغيير، وللموظف/الفريق عند الإسناد.

## 6. واجهة API (v1)

غلاف موحّد: `{"ok": true, "data": …}` أو `{"ok": false, "error": {"code", "message", "fields"?}}`.

| الطريقة | المسار | الوصف | المصادقة |
|---|---|---|---|
| GET | `/api/v1/meta` | التصنيفات، القواطع، الحالات، الخطورة (بلغة الطلب) | عام |
| GET | `/api/v1/locate?lat&lng` | تحويل GPS إلى كم وقاطع | عام (محدود المعدل) |
| GET | `/api/v1/home?km|lat,lng` | مؤشرات الرئيسية | عام |
| GET | `/api/v1/road` | مسار الطريق والقواطع وإعدادات الخريطة | عام |
| GET | `/api/v1/reports` · `/reports/map` · `/reports/<ref>` | القوائم والتفاصيل (الحقول الخاصة لمن يملك الصلاحية فقط) | عام/مالك |
| POST | `/api/v1/reports` | إنشاء بلاغ (multipart) | جلسة أو Bearer أو زائر |
| GET/POST | `/api/v1/notifications` · `/notifications/read` | التنبيهات | مستخدم |
| GET/POST | `/api/v1/push/key` · `/push/subscribe` · `/push/unsubscribe` | Web Push | جلسة/زائر |
| POST/DELETE | `/api/v1/auth/token` | إصدار/إلغاء رمز Bearer للتطبيقات الأصلية | — |
| GET | `/api/v1/me` · `/api/v1/csrf` | المستخدم الحالي / رمز CSRF جديد | — |

طلبات الجلسة غير الآمنة تتطلب ترويسة `X-CSRFToken`؛ طلب يحمل Bearer يُصادَق بالرمز فقط ولا يستخدم أي جلسة.
