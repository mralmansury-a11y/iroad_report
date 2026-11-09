import json
import os

from flask import (
    abort, current_app, flash, jsonify, make_response, redirect, render_template, request,
    session, url_for,
)
from flask_babel import force_locale
from flask_babel import gettext as _
from flask_login import current_user, login_required

from ..extensions import csrf, db, limiter
from ..models import Announcement, ContactMessage, Report, RoadSection, User, utcnow
from ..services.audit import audit
from ..services.notify import get_prefs
from ..services.stats import user_contribution
from ..utils import safe_referrer
from ..utils.validators import looks_like_email, normalize_phone
from . import bp
from .forms import ContactForm, NotificationPrefsForm, PasswordForm, ProfileForm


def active_sections():
    return db.session.execute(
        db.select(RoadSection).filter_by(is_active=True).order_by(RoadSection.sort_order, RoadSection.km_start)
    ).scalars().all()


def active_announcements(limit=5):
    now = utcnow()
    return db.session.execute(
        db.select(Announcement).where(
            Announcement.is_published.is_(True), Announcement.starts_at <= now,
            (Announcement.ends_at.is_(None)) | (Announcement.ends_at >= now),
        ).order_by(Announcement.starts_at.desc()).limit(limit)
    ).scalars().all()


@bp.route("/")
def home():
    latest = db.session.execute(
        db.select(Report).order_by(Report.created_at.desc()).limit(3)
    ).scalars().all()
    return render_template("public/home.html", latest=latest, sections=active_sections(),
                           announcements=active_announcements(3))


@bp.route("/lang/<code>")
def set_language(code):
    if code not in current_app.config["LANGUAGES"]:
        abort(404)
    session["lang"] = code
    if current_user.is_authenticated and current_user.locale != code:
        current_user.locale = code
        db.session.commit()
    resp = redirect(safe_referrer(url_for("main.home")))
    resp.set_cookie("lang", code, max_age=31536000, samesite="Lax", secure=request.is_secure)
    return resp


@bp.route("/settings/language")
def language():
    return render_template("public/language.html")


@bp.route("/profile")
@login_required
def profile():
    return render_template("public/profile.html", contrib=user_contribution(current_user))


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    form = ProfileForm(obj=current_user)
    form.home_section_id.choices = [(0, "—")] + [(s.id, s.tr("name")) for s in active_sections()]
    pw_form = PasswordForm(prefix="pw")
    if request.method == "GET":
        form.home_section_id.data = current_user.home_section_id or 0
    if request.form.get("action") == "password":
        if pw_form.validate_on_submit():
            if not current_user.check_password(pw_form.current.data):
                pw_form.current.errors.append(_("Current password is incorrect."))
            else:
                current_user.set_password(pw_form.password.data)
                audit("user.password_change", "user", current_user.id)
                db.session.commit()
                flash(_("Password changed."), "success")
                return redirect(url_for("main.profile"))
    elif form.validate_on_submit():
        phone = normalize_phone(form.phone.data) if form.phone.data else None
        email = (form.email.data or "").strip().lower() or None
        if email and not looks_like_email(email):
            form.email.errors.append(_("Enter a valid e-mail address."))
        elif not (phone or email):
            form.phone.errors.append(_("Enter a phone number or an e-mail address."))
        elif phone and db.session.execute(db.select(User.id).where(User.phone == phone, User.id != current_user.id)).first():
            form.phone.errors.append(_("This phone number is already registered."))
        elif email and db.session.execute(db.select(User.id).where(db.func.lower(User.email) == email, User.id != current_user.id)).first():
            form.email.errors.append(_("This e-mail is already registered."))
        else:
            current_user.full_name = form.full_name.data.strip()
            current_user.phone = phone
            current_user.email = email
            current_user.home_section_id = form.home_section_id.data or None
            audit("user.profile_update", "user", current_user.id)
            db.session.commit()
            flash(_("Changes saved."), "success")
            return redirect(url_for("main.profile"))
    return render_template("public/profile_edit.html", form=form, pw_form=pw_form)


@bp.route("/settings/notifications", methods=["GET", "POST"])
@login_required
def notification_settings():
    pref = get_prefs(current_user)
    db.session.flush()
    form = NotificationPrefsForm(obj=pref)
    if form.validate_on_submit():
        form.populate_obj(pref)
        db.session.commit()
        flash(_("Changes saved."), "success")
        return redirect(url_for("main.notification_settings"))
    return render_template("public/notification_settings.html", form=form)


@bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.route("/about")
def about():
    return render_template("public/about.html")


@bp.route("/install")
def install():
    return render_template("public/install.html")


@bp.route("/support", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per day", methods=["POST"])
def support():
    form = ContactForm()
    if request.method == "GET" and current_user.is_authenticated:
        form.name.data = current_user.full_name
        form.contact.data = current_user.phone or current_user.email
    if form.validate_on_submit():
        msg = ContactMessage(user_id=current_user.id if current_user.is_authenticated else None,
                             name=form.name.data.strip(), contact=form.contact.data.strip(), body=form.body.data.strip())
        db.session.add(msg)
        db.session.commit()
        flash(_("Your message was sent. The support team will contact you."), "success")
        return redirect(url_for("main.support"))
    return render_template("public/support.html", form=form)


@bp.route("/map")
def road_map():
    return render_template("public/map.html", sections=active_sections())


@bp.route("/alerts")
def alerts():
    return render_template("public/alerts.html", announcements=active_announcements(50))


@bp.route("/offline")
def offline():
    return render_template("public/offline.html", unread_count=0)


# ------------------------------------------------------------ PWA endpoints
@bp.route("/manifest.webmanifest")
def manifest():
    lang = request.args.get("lang") if request.args.get("lang") in ("ar", "en") else "ar"
    with force_locale(lang):
        name = _("International Road Libya")
        short = _("Intl. Road")
        desc = _("Report road problems and follow the status of the International Road in Libya.")
        shortcuts = [
            {"name": _("Report a road problem"), "short_name": _("New report"), "url": "/reports/new?source=pwa",
             "icons": [{"src": url_for("static", filename="icons/icon-96.png"), "sizes": "96x96"}]},
            {"name": _("My reports"), "url": "/reports/?tab=mine&source=pwa",
             "icons": [{"src": url_for("static", filename="icons/icon-96.png"), "sizes": "96x96"}]},
            {"name": _("Notifications"), "url": "/notifications/?source=pwa",
             "icons": [{"src": url_for("static", filename="icons/icon-96.png"), "sizes": "96x96"}]},
        ]
    icons = [{"src": url_for("static", filename=f"icons/icon-{s}.png"), "sizes": f"{s}x{s}", "type": "image/png",
              "purpose": "any"} for s in (72, 96, 128, 144, 152, 192, 384, 512)]
    icons += [{"src": url_for("static", filename=f"icons/maskable-{s}.png"), "sizes": f"{s}x{s}", "type": "image/png",
               "purpose": "maskable"} for s in (192, 512)]
    data = {
        "id": "/",
        "name": name,
        "short_name": short,
        "description": desc,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "start_url": f"/?source=pwa&lang={lang}",
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "portrait-primary",
        "theme_color": "#34668e",
        "background_color": "#181b19",
        "categories": ["navigation", "utilities", "government"],
        "icons": icons,
        "shortcuts": shortcuts,
    }
    resp = make_response(json.dumps(data, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


_SW_CACHE: dict = {}


def _static_fingerprint() -> str:
    """Hash of every static file (path, size, mtime) → cache version changes automatically on deploy."""
    import hashlib
    import os
    h = hashlib.sha256()
    for root, _dirs, files in sorted(os.walk(current_app.static_folder)):
        for f in sorted(files):
            fp = os.path.join(root, f)
            st = os.stat(fp)
            h.update(f"{fp}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:12]


@bp.route("/sw.js")
def service_worker():
    if "body" not in _SW_CACHE or current_app.debug:
        with open(os.path.join(current_app.static_folder, "js", "sw.js"), encoding="utf-8") as fh:
            _SW_CACHE["body"] = fh.read().replace("__SW_VERSION__", _static_fingerprint())
    resp = make_response(_SW_CACHE["body"])
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/healthz")
@csrf.exempt
def healthz():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 503
