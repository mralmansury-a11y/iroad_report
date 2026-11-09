# مخطط قاعدة البيانات (MariaDB)

* المحرك: InnoDB، الترميز `utf8mb4` / `utf8mb4_unicode_ci`، جميع الأوقات UTC.
* الإدارة بالترحيلات حصراً: `migrations/versions/*_initial_schema.py`؛ نسخة DDL مرجعية: `deploy/sql/schema_mariadb.sql`.
* أسماء القيود موحّدة (pk_/fk_/uq_/ix_/ck_) لتسهيل الترحيلات العكسية.

## الجداول (31)

| المجموعة | الجدول | أهم الحقول / القيود |
|---|---|---|
| الهوية | `users` | phone UNIQUE، email UNIQUE، password_hash (scrypt)، locale، home_section_id FK، is_active، points؛ CHECK (phone أو email) |
| | `roles`، `permissions`، `user_roles`، `role_permissions` | RBAC؛ مفاتيح مركّبة |
| | `api_tokens` | token_hash SHA-256 UNIQUE، expires_at، revoked |
| الطريق | `road_sections` + `road_section_translations` | km_start/km_end NUMERIC(7,2) مع CHECK، road_status، visibility_pct (0–100) |
| | `road_points` | km UNIQUE، latitude/longitude NUMERIC(9,6) — نقاط المسح المرجعية |
| البلاغات | `reports` | reference UNIQUE (IR-YYYY-NNNNNN)، category/status FK، severity CHECK، km_marker، lat/lng CHECK، reporter أو بيانات الزائر، الإسناد، first_response_at، resolved_at؛ فهارس مركّبة (status_id, created_at) و(road_section_id, km_marker) |
| | `report_categories` + `report_category_translations` | code UNIQUE، icon، default_team_id |
| | `report_statuses` + `report_status_translations` | new / under_review / assigned / in_progress / resolved / rejected |
| | `report_status_history` | from/to status، changed_by، public_note، internal_note |
| | `report_notes` | is_internal (داخلية / رد رسمي) |
| | `report_attachments` | stored_name عشوائي UNIQUE، mime، الحجم، الأبعاد |
| | `employee_assignments` | team، assignee، assigned_by، is_active، completed_at |
| الفرق | `teams` + `team_translations`، `team_members` | UNIQUE (team_id, user_id) |
| الإشعارات | `notifications` | title/body بالعربية والإنجليزية، is_read؛ فهرس (user_id, is_read) |
| | `notification_preferences` | user_id UNIQUE، 6 تفضيلات |
| | `push_subscriptions` | endpoint_hash UNIQUE، المفاتيح، locale، failure_count |
| | `announcements` + `announcement_translations` | النوع، المدى الكيلومتري، الفترة، النشر، notified_at |
| النظام | `system_settings` | key UNIQUE، value_type، is_public (لا أسرار) |
| | `audit_logs` | الإجراء، الكيان، التفاصيل JSON، IP، المتصفح |
| | `contact_messages` | رسائل الدعم وحالتها والرد |
| | `points_transactions` | UNIQUE (user_id, report_id, reason) يمنع تكرار النقاط |

## استراتيجية المحتوى ثنائي اللغة
* الكيانات القابلة للتهيئة (التصنيفات، القواطع، الحالات، الفرق، الإعلانات) لها جدول `*_translations (parent_id, locale, name…)` بقيد فريد `(parent_id, locale)`؛ الدالة `obj.tr("name")` ترجع لغة الواجهة ثم العربية احتياطاً.
* نص المستخدم (عنوان/وصف البلاغ) يُحفظ بلغته الأصلية مع حقل `reports.language` ولا يُترجم آلياً.
* الإشعارات النظامية تُخزَّن باللغتين لحظة إنشائها.

## الإجراءات
```bash
flask db upgrade            # إنشاء/تحديث المخطط
flask seed                  # بيانات مرجعية (آمنة للتكرار)
flask seed --demo           # بيانات عرض فقط — لا تُستخدم في الإنتاج
flask create-admin --name "..." --email admin@example.ly
flask db migrate -m "..."   # بعد تعديل النماذج (راجِع الملف المولّد قبل الاعتماد)
flask db downgrade -1       # تراجع خطوة واحدة
```
