# ربط النظام بخادم البريد الحالي (Postfix + PostfixAdmin — mail.iroad.ly)

## ما يرسله النظام بالبريد
| الرسالة | متى | اللغة |
|---|---|---|
| رابط إعادة تعيين كلمة المرور (صالح 60 دقيقة) | «نسيت كلمة المرور» | لغة حساب المستخدم |
| إشعار أمني «تم تغيير كلمة المرور» | بعد الاستعادة أو التغيير من الملف الشخصي | لغة الحساب |
| رد الدعم الفني | عند رد الموظف على رسالة تواصل تحمل بريداً إلكترونياً (المستخدم المسجّل يستلم الرد كإشعار داخل التطبيق) | العربية |
| رسالة اختبار | `flask send-test-mail` | ثنائية |

كل رسالة: نص عادي + HTML بهوية الإدارة، مع ترويسات `Date` و`Message-ID` و`Auto-Submitted` و`Reply-To`.

## الطريقة الموصى بها: صندوق مخصص + منفذ الإرسال 587 (STARTTLS + مصادقة)

### 1) الصندوق في PostfixAdmin
* الصندوق **`noreply@iroad.ly` موجود ومفعّل** على خادم الإدارة، ومسموح له الإرسال باسمه (`sender_login.cf`).
* (اختياري) لاستقبال ردود المواطنين في صندوق آخر ضع عنوانه في `MAIL_REPLY_TO`.

### 2) التحقق من خدمة submission على الخادم (قراءة فقط)
```bash
ss -ltnp | grep -E ':587|:465'            # يجب أن يظهر master (Postfix)
postconf -M submission/inet                # مُفعّلة في master.cf
postconf -n | grep -E 'smtpd_sasl_auth_enable|smtpd_tls_cert_file|smtpd_sender_login_maps'
```
* إن كان `smtpd_sender_login_maps` مفعلاً (الإعداد المعتاد مع PostfixAdmin) فيجب أن يكون **`MAIL_FROM` = `MAIL_USERNAME`** (أو Alias يملكه الصندوق)، وإلا يُرفض الإرسال برسالة `553 Sender address rejected: not owned by user`.

### 3) ملف البيئة `/etc/irs-road/irs-road.env`
```ini
MAIL_SERVER=mail.iroad.ly
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=noreply@iroad.ly
MAIL_PASSWORD=كلمة_مرور_الصندوق
MAIL_FROM=noreply@iroad.ly
MAIL_FROM_NAME="الطريق الدولي ليبيا - International Road Libya"
MAIL_REPLY_TO=
MAIL_VERIFY_TLS=true
APP_BASE_URL=https://iroad.ly
```
* اسم `MAIL_SERVER` يجب أن يطابق اسم شهادة TLS للبريد (`mail.iroad.ly`) — لا تستخدم عنوان IP أو `localhost` مع `MAIL_USE_TLS=true` وإلا يفشل التحقق من الشهادة (مقصود أمنياً).
* إن كان `mail.iroad.ly` يُحلّ من داخل الخادم إلى العنوان العام ولا يعمل الاتصال (NAT hairpin)، أضف في `/etc/hosts`: `127.0.1.1 mail.iroad.ly` — الشهادة تبقى صالحة لأن الاسم نفسه.
* المنفذ 465 بديلاً: `MAIL_PORT=465`، `MAIL_USE_SSL=true`، `MAIL_USE_TLS=false`.

### 4) إعادة التشغيل والاختبار
```bash
sudo systemctl restart irs-road
R='set -a; . /etc/irs-road/irs-road.env; cd /opt/irs-road/app; PATH=/opt/irs-road/venv/bin:$PATH'
sudo -u irsroad bash -c "$R; flask send-test-mail your.name@iroad.ly"
sudo tail -n 30 /var/log/mail.log            # أو: journalctl -u postfix -n 50
```
ثم اختبر «نسيت كلمة المرور» من الموقع بحساب له بريد إلكتروني.

## البديل: الترحيل المحلي عبر Postfix (دون كلمة مرور)
مناسب لأن التطبيق على نفس الخادم:
```ini
MAIL_SERVER=localhost
MAIL_PORT=25
MAIL_USE_TLS=false
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=noreply@iroad.ly
```
تحقق: `postconf mynetworks` يتضمن `127.0.0.0/8`. العيوب: لا مصادقة (أي عملية محلية يمكنها الإرسال)، ولا يعمل إن نُقل التطبيق لخادم آخر. لذلك الطريقة الأولى أفضل.

## حالة خادم iroad.ly (فحص 2026-11-09)
| البند | الحالة |
|---|---|
| submission 587 (STARTTLS إلزامي، Dovecot SASL، `reject_authenticated_sender_login_mismatch`) | ✔ |
| شهادة `mail.iroad.ly` (CN/SAN مطابق) — تنتهي 26/12/2026، مؤقّت certbot فعّال | ✔ |
| `noreply@iroad.ly` مفعّل ومسموح الإرسال باسمه | ✔ |
| SPF `v=spf1 ip4:102.203.201.143 ~all` | ✔ |
| DKIM (OpenDKIM، المحدِّد `s2026`، المفتاح منشور في DNS) | ✔ |
| DMARC `p=none` | ✔ (يمكن رفعه لاحقاً إلى `quarantine`) |
| PTR للعنوان 102.203.201.143 = `102.203.201.143.your-server.ly` | ✘ يُطلب من مزوّد الاستضافة جعله `mail.iroad.ly` |

## قابلية التسليم (حتى لا تذهب الرسائل إلى Spam)
افحص قبل التعديل — لا تستبدل سجلات قائمة:
```bash
dig +short TXT iroad.ly                 # SPF: يجب أن يتضمن عنوان الخادم أو mx  (مثال: v=spf1 mx a -all)
dig +short TXT default._domainkey.iroad.ly   # DKIM (حسب المحدِّد المستخدم في opendkim/rspamd)
dig +short TXT _dmarc.iroad.ly          # DMARC (مثال: v=DMARC1; p=quarantine; rua=mailto:dmarc@iroad.ly)
dig +short -x <IP_الخادم>              # PTR يجب أن يعود mail.iroad.ly
postconf smtpd_milters non_smtpd_milters     # وجود opendkim/rspamd للتوقيع
```
بما أن الإرسال يتم عبر خادم البريد نفسه وبعنوان `@iroad.ly`، فإن SPF و DKIM القائمين ينطبقان تلقائياً.

## استكشاف الأخطاء
| الرسالة في سجل التطبيق | السبب / الحل |
|---|---|
| `SMTP authentication failed` / `535` | كلمة مرور الصندوق أو اسم المستخدم (يكون البريد كاملاً) |
| `Sender refused` / `553 not owned by user` | `MAIL_FROM` لا يطابق الصندوق المُصادَق |
| `CERTIFICATE_VERIFY_FAILED` | `MAIL_SERVER` لا يطابق اسم الشهادة، أو الشهادة منتهية |
| `timed out` / `Connection refused` | المنفذ 587 غير مفعّل، جدار ناري، أو مشكلة hairpin (انظر `/etc/hosts`) |
| `MAIL_SERVER not configured` | المتغيرات غير موجودة في ملف البيئة أو لم تُعد تشغيل الخدمة |

التطبيق لا يتوقف أبداً بسبب فشل البريد: يُسجَّل الخطأ في `/var/log/irs-road/app.log` وتستمر العملية، ورسالة «نسيت كلمة المرور» موحّدة لمنع كشف الحسابات.
