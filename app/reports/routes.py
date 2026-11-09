from decimal import Decimal

from flask import (
    abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for,
)
from flask_babel import get_locale
from flask_babel import gettext as _
from flask_login import current_user

from ..extensions import db, limiter
from ..models import Report, ReportAttachment, ReportCategory, ReportStatus
from ..services.geo import km_from_coordinates, section_for_km
from ..services.reports import ReportInput, can_view_report, create_report
from ..services.settings import get_setting
from ..services.uploads import UploadError, upload_dir
from ..utils.validators import normalize_phone
from . import bp
from .forms import ReportForm, TrackForm

TRACK_KEY = "tracked_reports"


def _tracked() -> list[str]:
    return list(session.get(TRACK_KEY, []))


def _track(ref: str):
    refs = _tracked()
    if ref not in refs:
        refs = (refs + [ref])[-20:]
    session[TRACK_KEY] = refs


def _full_access(report: Report) -> bool:
    if current_user.is_authenticated and can_view_report(current_user, report):
        return True
    return report.reporter_id is None and report.reference in _tracked()


def _wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


@bp.route("/")
def index():
    tab = request.args.get("tab", "all")
    page = max(1, request.args.get("page", 1, type=int))
    q = db.select(Report).order_by(Report.created_at.desc())
    if tab == "mine":
        if not current_user.is_authenticated:
            if not _tracked():
                return redirect(url_for("auth.login", next=request.full_path))
            q = q.where(Report.reference.in_(_tracked()))
        else:
            q = q.where(Report.reporter_id == current_user.id)
    else:
        rejected = db.session.execute(db.select(ReportStatus.id).filter_by(code=ReportStatus.REJECTED)).scalar()
        q = q.where(Report.status_id != rejected)
    status = request.args.get("status")
    if status in ReportStatus.ALL:
        q = q.join(ReportStatus).where(ReportStatus.code == status)
    pagination = db.paginate(q, page=page, per_page=current_app.config["REPORTS_PER_PAGE"], error_out=False)
    return render_template("reports/index.html", pagination=pagination, tab=tab, status=status)


def _categories():
    return db.session.execute(
        db.select(ReportCategory).filter_by(is_active=True).order_by(ReportCategory.sort_order)
    ).scalars().all()


@bp.route("/new", methods=["GET", "POST"])
@limiter.limit("6 per minute; 40 per day", methods=["POST"])
def new():
    allow_guest = bool(get_setting("allow_guest_reports", True))
    if not get_setting("site_open_for_reports", True):
        flash(_("Report submission is temporarily closed."), "warning")
        return redirect(url_for("main.home"))
    if not current_user.is_authenticated and not allow_guest:
        return redirect(url_for("auth.login", next=request.full_path))

    cats = _categories()
    form = ReportForm()
    form.category_id.choices = [(c.id, c.tr("name")) for c in cats]

    if request.method == "POST":
        if form.validate_on_submit():
            is_guest = not current_user.is_authenticated
            if is_guest and not form.guest_phone.data:
                form.guest_phone.errors.append(_("Enter your phone number so you can follow up the report."))
            else:
                cat = db.session.get(ReportCategory, form.category_id.data)
                lang = get_locale().language if get_locale() else "ar"
                title = (form.title.data or "").strip() or cat.tr("name", lang)
                # Kilometre and section are derived on the server from the GPS / map point
                # (never trusted from the client).
                km, _offset = km_from_coordinates(float(form.latitude.data), float(form.longitude.data))
                section = section_for_km(km) if km is not None else None
                data = ReportInput(
                    title=title, category_id=cat.id, description=form.description.data,
                    severity=form.severity.data,
                    km_marker=Decimal(str(km)) if km is not None else None,
                    road_section_id=section.id if section else None,
                    latitude=form.latitude.data, longitude=form.longitude.data,
                    location_source=form.location_source.data or "manual", language=lang,
                    guest_name=form.guest_name.data if is_guest else None,
                    guest_phone=normalize_phone(form.guest_phone.data) if is_guest else None,
                )
                try:
                    report = create_report(data, None if is_guest else current_user,
                                           files=request.files.getlist(form.images.name))
                except UploadError as exc:
                    form.images.errors = [str(exc)]
                else:
                    _track(report.reference)
                    target = url_for("reports.submitted", reference=report.reference)
                    if _wants_json():
                        return jsonify({"ok": True, "reference": report.reference, "redirect": target}), 201
                    return redirect(target)
        if _wants_json():
            errors = {k: [str(e) for e in v] for k, v in form.errors.items()}
            return jsonify({"ok": False, "error": {"code": "validation", "fields": errors}}), 422
    return render_template("reports/new.html", form=form, categories=cats, allow_guest=allow_guest)


@bp.route("/submitted/<reference>")
def submitted(reference):
    report = db.session.execute(db.select(Report).filter_by(reference=reference)).scalar_one_or_none()
    if report is None or not _full_access(report):
        abort(404)
    return render_template("reports/submitted.html", report=report)


@bp.route("/track", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def track():
    form = TrackForm()
    if form.validate_on_submit():
        ref = form.reference.data.strip().upper()
        phone = normalize_phone(form.phone.data)
        report = db.session.execute(db.select(Report).filter_by(reference=ref)).scalar_one_or_none()
        owner_phone = None
        if report is not None:
            owner_phone = report.guest_phone or (report.reporter.phone if report.reporter else None)
        if report is None or not phone or owner_phone != phone:
            flash(_("No report matches this reference number and phone."), "danger")
        else:
            if report.reporter_id is None:
                _track(report.reference)
                return redirect(url_for("reports.detail", reference=report.reference))
            flash(_("This report belongs to a registered account. Log in to follow it."), "info")
            return redirect(url_for("auth.login", next=url_for("reports.detail", reference=report.reference)))
    return render_template("reports/track.html", form=form)


@bp.route("/<reference>")
def detail(reference):
    report = db.session.execute(db.select(Report).filter_by(reference=reference)).scalar_one_or_none()
    if report is None:
        abort(404)
    full = _full_access(report)
    if not full and report.status_code == ReportStatus.REJECTED:
        abort(404)
    public_notes = [n for n in report.notes if not n.is_internal] if full else []
    return render_template("reports/detail.html", report=report, full=full, public_notes=public_notes)


@bp.route("/attachment/<int:att_id>")
def attachment(att_id):
    att = db.session.get(ReportAttachment, att_id)
    if att is None or not _full_access(att.report):
        abort(404)
    resp = send_from_directory(upload_dir(), att.stored_name, mimetype=att.mime_type, max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["Content-Disposition"] = "inline"
    return resp
