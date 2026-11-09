from decimal import Decimal, InvalidOperation

from flask import current_app, jsonify, request, session, url_for
from flask_babel import get_locale
from flask_babel import gettext as _
from flask_login import current_user

from ..extensions import db, limiter
from ..models import (
    ApiToken, Notification, PushSubscription, Report, ReportCategory, ReportStatus, RoadSection, utcnow,
)
from ..services.geo import km_from_coordinates, road_polyline, section_for_km
from ..services.reports import ReportInput, WorkflowError, can_view_report, create_report
from ..services.settings import get_setting
from ..services.stats import home_metrics, nearby_markers
from ..services.uploads import UploadError
from ..utils.i18n import fmt_hours, fmt_km, reltime, road_status_label, severity_label
from ..utils.validators import looks_like_email, normalize_phone, to_latin_digits
from . import bp


def ok(data=None, status=200):
    return jsonify({"ok": True, "data": data}), status


def err(code, message, status=400, **extra):
    e = {"code": code, "message": message}
    e.update(extra)
    return jsonify({"ok": False, "error": e}), status


def _float(name):
    v = request.args.get(name) or request.form.get(name)
    if v in (None, ""):
        return None
    try:
        return float(to_latin_digits(v))
    except ValueError:
        return None


def _lang():
    loc = get_locale()
    return loc.language if loc else "ar"


def report_public(r: Report) -> dict:
    return {
        "reference": r.reference,
        "title": r.title,
        "category": {"code": r.category.code, "name": r.category.tr("name"), "icon": r.category.icon},
        "status": {"code": r.status_code, "name": r.status.tr("name"), "tone": r.status.tone},
        "severity": {"code": r.severity, "name": severity_label(r.severity)},
        "km": r.km_float(),
        "km_label": fmt_km(r.km_float()),
        "section": r.road_section.tr("name") if r.road_section else None,
        "created_at": r.created_at.isoformat() + "Z",
        "created_rel": reltime(r.created_at),
        "url": url_for("reports.detail", reference=r.reference),
    }


@bp.get("/csrf")
def csrf_token_refresh():
    """Fresh CSRF token for pages restored from the offline cache."""
    from flask_wtf.csrf import generate_csrf
    return ok({"token": generate_csrf()})


# ------------------------------------------------------------ reference data
@bp.get("/meta")
def meta():
    cats = db.session.execute(db.select(ReportCategory).filter_by(is_active=True).order_by(ReportCategory.sort_order)).scalars()
    secs = db.session.execute(db.select(RoadSection).filter_by(is_active=True).order_by(RoadSection.sort_order)).scalars()
    sts = db.session.execute(db.select(ReportStatus).order_by(ReportStatus.sort_order)).scalars()
    return ok({
        "locale": _lang(),
        "categories": [{"id": c.id, "code": c.code, "name": c.tr("name"), "icon": c.icon} for c in cats],
        "sections": [{"id": s.id, "code": s.code, "name": s.tr("name"), "km_start": float(s.km_start),
                      "km_end": float(s.km_end), "road_status": s.road_status} for s in secs],
        "statuses": [{"code": s.code, "name": s.tr("name"), "tone": s.tone} for s in sts],
        "severities": [{"code": c, "name": severity_label(c)} for c in Report.SEVERITIES],
    })


@bp.get("/locate")
@limiter.limit("60 per minute")
def locate():
    lat, lng = _float("lat"), _float("lng")
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return err("invalid_coordinates", _("Invalid coordinates."), 422)
    km, offset = km_from_coordinates(lat, lng)
    if km is None:
        return ok({"km": None, "offset_km": offset, "on_road": False})
    sec = section_for_km(km)
    return ok({"km": km, "km_label": fmt_km(km), "offset_km": offset, "on_road": True,
               "section": {"id": sec.id, "name": sec.tr("name")} if sec else None})


@bp.get("/home")
def home_data():
    km = _float("km")
    lat, lng = _float("lat"), _float("lng")
    source = "manual" if km is not None else None
    if km is None and lat is not None and lng is not None:
        km, _off = km_from_coordinates(lat, lng)
        source = "gps" if km is not None else None
    section = section_for_km(km)
    sid = request.args.get("section", type=int)
    if section is None and sid:
        section = db.session.get(RoadSection, sid)
    m = home_metrics(km, section)
    return ok({
        **m,
        "source": source,
        "km_label": fmt_km(km) if km is not None else None,
        "road_status_label": road_status_label(m["road_status"]),
        "avg_response_label": fmt_hours(m["avg_response_hours"]),
        "markers": nearby_markers(km),
    })


@bp.get("/road")
def road():
    secs = db.session.execute(db.select(RoadSection).filter_by(is_active=True).order_by(RoadSection.sort_order)).scalars()
    return ok({
        "polyline": road_polyline(),
        "sections": [{"id": s.id, "name": s.tr("name"), "km_start": float(s.km_start), "km_end": float(s.km_end),
                      "road_status": s.road_status, "road_status_label": road_status_label(s.road_status)} for s in secs],
        "map": {"lat": float(get_setting("default_map_lat", "31.2") or 31.2),
                "lng": float(get_setting("default_map_lng", "16.6") or 16.6),
                "zoom": int(get_setting("default_map_zoom", 8) or 8),
                "tiles": current_app.config["MAP_TILE_URL"], "attribution": current_app.config["MAP_ATTRIBUTION"]},
    })


# ------------------------------------------------------------ reports
@bp.get("/reports")
def list_reports():
    page = max(1, request.args.get("page", 1, type=int))
    per = min(50, max(1, request.args.get("per_page", 20, type=int)))
    q = db.select(Report).order_by(Report.created_at.desc())
    if request.args.get("mine") == "1":
        if not current_user.is_authenticated:
            return err("unauthorized", _("Login required."), 401)
        q = q.where(Report.reporter_id == current_user.id)
    else:
        q = q.join(ReportStatus).where(ReportStatus.code != ReportStatus.REJECTED)
    st = request.args.get("status")
    if st in ReportStatus.ALL:
        q = q.where(Report.status.has(code=st))
    p = db.paginate(q, page=page, per_page=per, error_out=False)
    return ok({"items": [report_public(r) for r in p.items], "page": p.page, "pages": p.pages, "total": p.total})


@bp.get("/reports/map")
def reports_map():
    q = (db.select(Report).join(ReportStatus)
         .where(ReportStatus.code.in_(ReportStatus.OPEN), Report.latitude.is_not(None))
         .order_by(Report.created_at.desc()).limit(500))
    items = []
    for r in db.session.execute(q).scalars():
        d = report_public(r)
        d["lat"], d["lng"] = float(r.latitude), float(r.longitude)
        items.append(d)
    return ok({"items": items})


@bp.get("/reports/<reference>")
def get_report(reference):
    r = db.session.execute(db.select(Report).filter_by(reference=reference)).scalar_one_or_none()
    if r is None:
        return err("not_found", _("Not found."), 404)
    data = report_public(r)
    tracked = r.reporter_id is None and reference in session.get("tracked_reports", [])
    if (current_user.is_authenticated and can_view_report(current_user, r)) or tracked:
        data.update({
            "description": r.description,
            "latitude": float(r.latitude) if r.latitude is not None else None,
            "longitude": float(r.longitude) if r.longitude is not None else None,
            "attachments": [url_for("reports.attachment", att_id=a.id) for a in r.attachments],
            "history": [{"status": h.to_status.code, "name": h.to_status.tr("name"),
                         "note": h.public_note, "at": h.created_at.isoformat() + "Z"} for h in r.history],
            "responses": [{"body": n.body, "at": n.created_at.isoformat() + "Z"} for n in r.notes if not n.is_internal],
        })
    elif r.status_code == ReportStatus.REJECTED:
        return err("not_found", _("Not found."), 404)
    return ok(data)


@bp.post("/reports")
@limiter.limit("6 per minute; 40 per day")
def create():
    if not get_setting("site_open_for_reports", True):
        return err("closed", _("Report submission is temporarily closed."), 503)
    user = current_user if current_user.is_authenticated else None
    if user is None and not get_setting("allow_guest_reports", True):
        return err("unauthorized", _("Login required."), 401)
    f = request.form
    fields = {}
    cat = db.session.get(ReportCategory, f.get("category_id", type=int) or 0)
    if cat is None or not cat.is_active:
        fields["category_id"] = [_("Choose the problem type.")]

    def dec(name, places):
        v = f.get(name)
        if not v:
            return None
        try:
            return round(Decimal(to_latin_digits(v)), places)
        except InvalidOperation:
            fields[name] = [_("Invalid value.")]
            return None

    km, lat, lng = dec("km_marker", 1), dec("latitude", 6), dec("longitude", 6)
    sid = f.get("road_section_id", type=int) or None
    if km is None and lat is None and not sid:
        fields["km_marker"] = [_("Specify the location: kilometre, section or GPS.")]
    guest_phone = None
    if user is None:
        guest_phone = normalize_phone(f.get("guest_phone"))
        if not guest_phone:
            fields["guest_phone"] = [_("Enter your phone number so you can follow up the report.")]
    if fields:
        return err("validation", _("Please correct the highlighted fields."), 422, fields=fields)
    title = (f.get("title") or "").strip()[:160] or cat.tr("name", _lang())
    data = ReportInput(title=title, category_id=cat.id, description=(f.get("description") or "")[:3000],
                       severity=f.get("severity", "medium"), km_marker=km, road_section_id=sid, latitude=lat,
                       longitude=lng, location_source=f.get("location_source", "manual"), language=_lang(),
                       guest_name=f.get("guest_name"), guest_phone=guest_phone)
    try:
        r = create_report(data, user, files=request.files.getlist("images"))
    except (UploadError, WorkflowError) as exc:
        return err("validation", str(exc), 422, fields={"images": [str(exc)]})
    if user is None:
        refs = session.get("tracked_reports", [])
        session["tracked_reports"] = (refs + [r.reference])[-20:]
    return ok(report_public(r), 201)


# ------------------------------------------------------------ notifications
@bp.get("/notifications")
def notifications():
    if not current_user.is_authenticated:
        return err("unauthorized", _("Login required."), 401)
    rows = db.session.execute(db.select(Notification).filter_by(user_id=current_user.id)
                              .order_by(Notification.created_at.desc()).limit(50)).scalars()
    unread = db.session.execute(db.select(db.func.count(Notification.id))
                                .filter_by(user_id=current_user.id, is_read=False)).scalar_one()
    return ok({"unread": unread, "items": [{
        "id": n.id, "kind": n.kind, "title": n.title(), "body": n.body(), "url": n.url, "is_read": n.is_read,
        "created_at": n.created_at.isoformat() + "Z", "created_rel": reltime(n.created_at)} for n in rows]})


@bp.post("/notifications/read")
def notifications_read():
    if not current_user.is_authenticated:
        return err("unauthorized", _("Login required."), 401)
    ids = (request.get_json(silent=True) or {}).get("ids")
    q = db.update(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    if isinstance(ids, list) and ids:
        q = q.where(Notification.id.in_([int(i) for i in ids if str(i).isdigit()]))
    db.session.execute(q.values(is_read=True, read_at=utcnow()))
    db.session.commit()
    return ok()


# ------------------------------------------------------------ web push
@bp.get("/push/key")
def push_key():
    key = current_app.config.get("VAPID_PUBLIC_KEY")
    if not key:
        return err("push_disabled", "Push not configured", 503)
    return ok({"publicKey": key})


@bp.post("/push/subscribe")
@limiter.limit("20 per hour")
def push_subscribe():
    body = request.get_json(silent=True) or {}
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint", "")
    keys = sub.get("keys") or {}
    if not endpoint.startswith("https://") or len(endpoint) > 2000 or not keys.get("p256dh") or not keys.get("auth"):
        return err("invalid_subscription", "Invalid subscription", 422)
    h = PushSubscription.hash_endpoint(endpoint)
    row = db.session.execute(db.select(PushSubscription).filter_by(endpoint_hash=h)).scalar_one_or_none()
    if row is None:
        row = PushSubscription(endpoint=endpoint, endpoint_hash=h)
        db.session.add(row)
    row.p256dh, row.auth = keys["p256dh"][:255], keys["auth"][:255]
    row.user_id = current_user.id if current_user.is_authenticated else None
    row.locale = _lang()
    row.user_agent = (request.user_agent.string or "")[:255]
    row.failure_count = 0
    db.session.commit()
    return ok({"subscribed": True}, 201)


@bp.post("/push/unsubscribe")
def push_unsubscribe():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint", "")
    row = db.session.execute(db.select(PushSubscription)
                             .filter_by(endpoint_hash=PushSubscription.hash_endpoint(endpoint))).scalar_one_or_none()
    if row is not None and (row.user_id is None or (current_user.is_authenticated and row.user_id == current_user.id)):
        db.session.delete(row)
        db.session.commit()
    return ok({"subscribed": False})


# ------------------------------------------------------------ token auth (mobile)
@bp.post("/auth/token")
@limiter.limit("10 per minute; 50 per hour")
def issue_token():
    from ..models import User
    body = request.get_json(silent=True) or {}
    ident = (body.get("identifier") or "").strip()
    pw = body.get("password") or ""
    user = None
    if looks_like_email(ident):
        user = db.session.execute(db.select(User).filter(db.func.lower(User.email) == ident.lower())).scalar_one_or_none()
    elif normalize_phone(ident):
        user = db.session.execute(db.select(User).filter_by(phone=normalize_phone(ident))).scalar_one_or_none()
    if user is None or not user.check_password(pw) or not user.is_active:
        return err("invalid_credentials", _("Incorrect login details."), 401)
    tok, raw = ApiToken.issue(user, current_app.config["API_TOKEN_TTL_DAYS"], name=(body.get("device") or "")[:80])
    db.session.commit()
    return ok({"token": raw, "token_type": "Bearer", "expires_at": tok.expires_at.isoformat() + "Z",
               "user": {"id": user.id, "name": user.full_name, "locale": user.locale}}, 201)


@bp.delete("/auth/token")
def revoke_token():
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return err("unauthorized", "Bearer token required", 401)
    tok = db.session.execute(db.select(ApiToken).filter_by(token_hash=ApiToken.hash(auth.split(None, 1)[1].strip()))).scalar_one_or_none()
    if tok:
        tok.revoked = True
        db.session.commit()
    return ok({"revoked": True})


@bp.get("/me")
def me():
    if not current_user.is_authenticated:
        return err("unauthorized", _("Login required."), 401)
    u = current_user
    return ok({"id": u.id, "name": u.full_name, "phone": u.phone, "email": u.email, "locale": u.locale,
               "points": u.points, "roles": [r.code for r in u.roles], "is_staff": u.is_staff})
