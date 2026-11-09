from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import get_timezone
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy import or_

from ..extensions import db
from ..models import (
    Announcement, AuditLog, ContactMessage, Report, ReportAttachment, ReportCategory, ReportStatus, Role,
    RoadPoint, RoadSection, Team, TeamMember, User, utcnow,
)
from ..services import stats
from ..services.audit import audit
from ..services.mail import send_mail
from ..services.notify import broadcast_push, notify
from ..services.rbac import can_grant_role, permission_required
from ..services.reports import (
    WorkflowError, add_note, allowed_next_statuses, assign_report, can_view_report, change_status,
    staff_reports_query,
)
from ..services.settings import DEFAULT_SETTINGS, get_setting, set_setting
from ..services.uploads import delete_stored
from ..utils.validators import looks_like_email, normalize_phone, to_latin_digits
from . import bp
from .forms import (
    AnnouncementForm, AssignForm, CategoryForm, MessageForm, NoteForm, RoadPointsForm, SectionForm, StatusForm,
    TeamForm, UserForm,
)


def _per_page():
    return current_app.config["ADMIN_PER_PAGE"]


def _page():
    return max(1, request.args.get("page", 1, type=int))


# ============================================================ dashboard
@bp.route("/")
def dashboard():
    if current_user.can("reports.view_all"):
        counts = stats.status_counts()
    else:
        q = staff_reports_query(current_user).subquery()
        rows = db.session.execute(
            db.select(ReportStatus.code, db.func.count(q.c.id)).select_from(q)
            .join(ReportStatus, ReportStatus.id == q.c.status_id).group_by(ReportStatus.code)).all()
        counts = {c: 0 for c in ReportStatus.ALL}
        counts.update(dict(rows))
        counts["total"] = sum(counts[c] for c in ReportStatus.ALL)
    recent = db.session.execute(staff_reports_query(current_user).order_by(Report.created_at.desc()).limit(8)).scalars().all()
    unassigned_high = []
    if current_user.can("reports.assign"):
        unassigned_high = db.session.execute(
            db.select(Report).join(ReportStatus).where(
                ReportStatus.code.in_([ReportStatus.NEW, ReportStatus.UNDER_REVIEW]), Report.severity == "high")
            .order_by(Report.created_at).limit(5)).scalars().all()
    new_messages = 0
    if current_user.can("messages.manage"):
        new_messages = db.session.execute(db.select(db.func.count(ContactMessage.id)).filter_by(status="new")).scalar_one()
    return render_template("admin/dashboard.html", counts=counts, recent=recent, unassigned_high=unassigned_high,
                           avg_response=stats.avg_response_hours(), avg_resolution=stats.avg_resolution_hours(),
                           new_messages=new_messages)


# ============================================================ reports
def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else None
    except ValueError:
        return None


def _dec(s):
    try:
        return Decimal(to_latin_digits(s)) if s not in (None, "") else None
    except InvalidOperation:
        return None


@bp.route("/reports")
@permission_required("reports.view_assigned", "reports.view_all", any_of=True)
def reports():
    a = request.args
    q = staff_reports_query(current_user)
    if a.get("q"):
        term = f"%{a['q'].strip()}%"
        q = q.where(or_(Report.reference.ilike(term), Report.title.ilike(term), Report.description.ilike(term)))
    if a.get("status") in ReportStatus.ALL:
        q = q.where(Report.status.has(code=a["status"]))
    if a.get("category", type=int):
        q = q.where(Report.category_id == a.get("category", type=int))
    if a.get("section", type=int):
        q = q.where(Report.road_section_id == a.get("section", type=int))
    if a.get("severity") in Report.SEVERITIES:
        q = q.where(Report.severity == a["severity"])
    if _dec(a.get("km_from")) is not None:
        q = q.where(Report.km_marker >= _dec(a.get("km_from")))
    if _dec(a.get("km_to")) is not None:
        q = q.where(Report.km_marker <= _dec(a.get("km_to")))
    if _parse_date(a.get("from")):
        q = q.where(Report.created_at >= _parse_date(a.get("from")))
    if _parse_date(a.get("to")):
        q = q.where(Report.created_at < _parse_date(a.get("to")) + timedelta(days=1))
    if a.get("mine") == "1":
        q = q.where(Report.assigned_user_id == current_user.id)
    order = Report.created_at.asc() if a.get("sort") == "oldest" else Report.created_at.desc()
    pagination = db.paginate(q.order_by(order), page=_page(), per_page=_per_page(), error_out=False)
    cats = db.session.execute(db.select(ReportCategory).order_by(ReportCategory.sort_order)).scalars().all()
    secs = db.session.execute(db.select(RoadSection).order_by(RoadSection.sort_order)).scalars().all()
    sts = db.session.execute(db.select(ReportStatus).order_by(ReportStatus.sort_order)).scalars().all()
    return render_template("admin/reports.html", pagination=pagination, categories=cats, sections=secs, statuses=sts)


def _get_report_or_404(report_id) -> Report:
    r = db.session.get(Report, report_id)
    if r is None or not can_view_report(current_user, r):
        abort(404)
    return r


def _assign_form(report: Report):
    form = AssignForm(prefix="as")
    teams = db.session.execute(db.select(Team).filter_by(is_active=True)).scalars().all()
    form.team_id.choices = [(0, "—")] + [(t.id, t.tr("name")) for t in teams]
    staff = [u for u in db.session.execute(db.select(User).filter_by(active=True).order_by(User.full_name)).scalars() if u.is_staff]
    form.assignee_id.choices = [(0, "—")] + [(u.id, u.full_name) for u in staff]
    if request.method == "GET":
        form.team_id.data = report.assigned_team_id or (report.category.default_team_id or 0)
        form.assignee_id.data = report.assigned_user_id or 0
    return form


def _status_form(report: Report):
    form = StatusForm(prefix="st")
    nxt = allowed_next_statuses(current_user, report)
    sts = {s.code: s for s in db.session.execute(db.select(ReportStatus)).scalars()}
    form.to_status.choices = [(c, sts[c].tr("name")) for c in nxt if c in sts]
    return form


@bp.route("/reports/<int:report_id>")
@permission_required("reports.view_assigned", "reports.view_all", any_of=True)
def report_detail(report_id):
    r = _get_report_or_404(report_id)
    return render_template("admin/report_detail.html", report=r, status_form=_status_form(r),
                           assign_form=_assign_form(r), note_form=NoteForm(prefix="nt"))


@bp.route("/reports/<int:report_id>/status", methods=["POST"])
@permission_required("reports.update_status")
def report_status(report_id):
    r = _get_report_or_404(report_id)
    form = _status_form(r)
    if form.validate_on_submit():
        try:
            change_status(r, current_user, form.to_status.data, form.public_note.data, form.internal_note.data)
            flash(_("Status updated."), "success")
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    else:
        flash(_("This status change is not allowed."), "danger")
    return redirect(url_for("admin.report_detail", report_id=r.id))


@bp.route("/reports/<int:report_id>/assign", methods=["POST"])
@permission_required("reports.assign")
def report_assign(report_id):
    r = _get_report_or_404(report_id)
    form = _assign_form(r)
    if form.validate_on_submit():
        try:
            assign_report(r, current_user, form.team_id.data or None, form.assignee_id.data or None, form.note.data)
            flash(_("Report assigned."), "success")
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("admin.report_detail", report_id=r.id))


@bp.route("/reports/<int:report_id>/note", methods=["POST"])
@permission_required("reports.internal_notes")
def report_note(report_id):
    r = _get_report_or_404(report_id)
    form = NoteForm(prefix="nt")
    if form.validate_on_submit():
        is_public = form.visibility.data == "public"
        if is_public and not current_user.can("reports.review") and not current_user.can("reports.update_status"):
            abort(403)
        try:
            add_note(r, current_user, form.body.data, is_internal=not is_public)
            flash(_("Note added."), "success")
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("admin.report_detail", report_id=r.id) + "#notes")


@bp.route("/attachments/<int:att_id>/delete", methods=["POST"])
@permission_required("reports.review")
def attachment_delete(att_id):
    att = db.session.get(ReportAttachment, att_id)
    if att is None:
        abort(404)
    rid = att.report_id
    name = att.stored_name
    db.session.delete(att)
    audit("attachment.delete", "report", rid, stored=name)
    db.session.commit()
    delete_stored(name)
    flash(_("Image deleted."), "success")
    return redirect(url_for("admin.report_detail", report_id=rid))


# ============================================================ users & employees
def _role_choices():
    roles = db.session.execute(db.select(Role).order_by(Role.level)).scalars().all()
    return [(r.id, r.label(current_user.locale)) for r in roles if can_grant_role(current_user, r)]


def _team_choices():
    return [(t.id, t.tr("name")) for t in db.session.execute(db.select(Team).order_by(Team.code)).scalars()]


@bp.route("/users")
@permission_required("users.view")
def users():
    q = db.select(User).order_by(User.created_at.desc())
    term = request.args.get("q", "").strip()
    if term:
        like = f"%{term}%"
        q = q.where(or_(User.full_name.ilike(like), User.phone.ilike(like), User.email.ilike(like)))
    role = request.args.get("role")
    if role:
        q = q.where(User.roles.any(Role.code == role))
    if request.args.get("state") == "inactive":
        q = q.where(User.active.is_(False))
    pagination = db.paginate(q, page=_page(), per_page=_per_page(), error_out=False)
    roles = db.session.execute(db.select(Role).order_by(Role.level)).scalars().all()
    return render_template("admin/users.html", pagination=pagination, roles=roles)


def _save_user(form: UserForm, user: User | None):
    phone = normalize_phone(form.phone.data) if form.phone.data else None
    email = (form.email.data or "").strip().lower() or None
    if email and not looks_like_email(email):
        form.email.errors.append(_("Enter a valid e-mail address."))
        return None
    if not (phone or email):
        form.phone.errors.append(_("Enter a phone number or an e-mail address."))
        return None
    uid = user.id if user else -1
    if phone and db.session.execute(db.select(User.id).where(User.phone == phone, User.id != uid)).first():
        form.phone.errors.append(_("This phone number is already registered."))
        return None
    if email and db.session.execute(db.select(User.id).where(db.func.lower(User.email) == email, User.id != uid)).first():
        form.email.errors.append(_("This e-mail is already registered."))
        return None
    if user is None and not form.password.data:
        form.password.errors.append(_("A password is required for new accounts."))
        return None
    creating = user is None
    if creating:
        user = User()
        db.session.add(user)
    user.full_name = form.full_name.data.strip()
    user.phone, user.email = phone, email
    user.job_title = (form.job_title.data or "").strip() or None
    user.locale = form.locale.data
    if form.password.data:
        user.set_password(form.password.data)
    if user.id != current_user.id:
        user.active = bool(form.active.data)
    # roles: keep roles the actor cannot manage, replace the manageable ones
    grantable = {rid for rid, _l in _role_choices()}
    kept = [r for r in user.roles if r.id not in grantable]
    chosen = db.session.execute(db.select(Role).where(Role.id.in_([i for i in form.roles.data if i in grantable]))).scalars().all()
    if user.id == current_user.id:
        kept = list(user.roles)  # cannot change own roles
        chosen = []
    new_roles = list({r.id: r for r in kept + list(chosen)}.values())
    if not new_roles:
        new_roles = [db.session.execute(db.select(Role).filter_by(code=Role.PUBLIC)).scalar_one()]
    user.roles = new_roles
    # team membership (staff only)
    if current_user.can("employees.manage"):
        wanted = set(form.teams.data or [])
        current = {m.team_id: m for m in user.team_memberships}
        for tid, m in list(current.items()):
            if tid not in wanted:
                user.team_memberships.remove(m)
        for tid in wanted - set(current):
            user.team_memberships.append(TeamMember(team_id=tid))
    db.session.flush()
    audit("user.create" if creating else "user.update", "user", user.id,
          roles=[r.code for r in user.roles], active=user.active)
    db.session.commit()
    return user


@bp.route("/users/new", methods=["GET", "POST"])
@permission_required("users.manage")
def user_new():
    form = UserForm()
    form.roles.choices, form.teams.choices = _role_choices(), _team_choices()
    if form.validate_on_submit():
        u = _save_user(form, None)
        if u:
            flash(_("User created."), "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, user=None)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@permission_required("users.manage")
def user_edit(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.role_level >= current_user.role_level and user.id != current_user.id and not current_user.has_role("superadmin"):
        abort(403)
    form = UserForm(obj=user)
    form.roles.choices, form.teams.choices = _role_choices(), _team_choices()
    if request.method == "GET":
        form.roles.data = [r.id for r in user.roles]
        form.teams.data = [m.team_id for m in user.team_memberships]
        form.active.data = user.active
    if form.validate_on_submit():
        if _save_user(form, user):
            flash(_("Changes saved."), "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, user=user)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@permission_required("users.manage")
def user_toggle(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id or (user.role_level >= current_user.role_level and not current_user.has_role("superadmin")):
        abort(403)
    user.active = not user.active
    audit("user.activate" if user.active else "user.deactivate", "user", user.id)
    db.session.commit()
    flash(_("Account activated.") if user.active else _("Account deactivated."), "success")
    return redirect(request.referrer or url_for("admin.users"))


@bp.route("/employees")
@permission_required("employees.manage", "reports.assign", any_of=True)
def employees():
    staff = [u for u in db.session.execute(db.select(User).order_by(User.full_name)).scalars() if u.is_staff]
    workload = {w["user"].id: w for w in stats.employee_workload()}
    teams = db.session.execute(db.select(Team).order_by(Team.code)).scalars().all()
    return render_template("admin/employees.html", staff=staff, workload=workload, teams=teams)


# ============================================================ teams
@bp.route("/teams", methods=["GET"])
@permission_required("teams.manage")
def teams():
    rows = db.session.execute(db.select(Team).order_by(Team.code)).scalars().all()
    return render_template("admin/teams.html", teams=rows)


def _save_translated(obj, form, extra_fields=("description",)):
    obj.code = form.code.data.strip()
    obj.is_active = bool(form.is_active.data)
    for loc in ("ar", "en"):
        fields = {"name": getattr(form, f"name_{loc}").data.strip()}
        for f in extra_fields:
            if hasattr(form, f"{f}_{loc}"):
                fields[f] = (getattr(form, f"{f}_{loc}").data or "").strip() or None
        obj.set_translation(loc, **fields)


def _fill_translated(form, obj, extra_fields=("description",)):
    form.code.data = obj.code
    form.is_active.data = obj.is_active
    for loc in ("ar", "en"):
        t = obj._translation_for(loc)
        getattr(form, f"name_{loc}").data = t.name if t else ""
        for f in extra_fields:
            if hasattr(form, f"{f}_{loc}"):
                getattr(form, f"{f}_{loc}").data = getattr(t, f, "") if t else ""


def _code_taken(model, code, obj_id):
    return db.session.execute(db.select(model.id).where(model.code == code, model.id != (obj_id or -1))).first()


@bp.route("/teams/new", methods=["GET", "POST"])
@bp.route("/teams/<int:team_id>", methods=["GET", "POST"])
@permission_required("teams.manage")
def team_form(team_id=None):
    team = db.session.get(Team, team_id) if team_id else None
    if team_id and team is None:
        abort(404)
    form = TeamForm()
    if request.method == "GET" and team:
        _fill_translated(form, team)
    if form.validate_on_submit():
        if _code_taken(Team, form.code.data.strip(), team.id if team else None):
            form.code.errors.append(_("This code is already used."))
        else:
            if team is None:
                team = Team()
                db.session.add(team)
            _save_translated(team, form)
            db.session.flush()
            audit("team.save", "team", team.id)
            db.session.commit()
            flash(_("Changes saved."), "success")
            return redirect(url_for("admin.teams"))
    return render_template("admin/simple_form.html", form=form, obj=team, title=_("Team"),
                           back=url_for("admin.teams"), members=team.members if team else None)


# ============================================================ categories
@bp.route("/categories")
@permission_required("categories.manage")
def categories():
    rows = db.session.execute(db.select(ReportCategory).order_by(ReportCategory.sort_order)).scalars().all()
    return render_template("admin/categories.html", categories=rows)


@bp.route("/categories/new", methods=["GET", "POST"])
@bp.route("/categories/<int:cat_id>", methods=["GET", "POST"])
@permission_required("categories.manage")
def category_form(cat_id=None):
    cat = db.session.get(ReportCategory, cat_id) if cat_id else None
    if cat_id and cat is None:
        abort(404)
    form = CategoryForm()
    form.default_team_id.choices = [(0, "—")] + _team_choices()
    if request.method == "GET" and cat:
        _fill_translated(form, cat)
        form.icon.data, form.sort_order.data = cat.icon, cat.sort_order
        form.default_team_id.data = cat.default_team_id or 0
    if form.validate_on_submit():
        if _code_taken(ReportCategory, form.code.data.strip(), cat.id if cat else None):
            form.code.errors.append(_("This code is already used."))
        else:
            if cat is None:
                cat = ReportCategory()
                db.session.add(cat)
            _save_translated(cat, form, ())
            cat.icon = form.icon.data.strip() if form.icon.data.strip().startswith("bi-") else "bi-exclamation-triangle"
            cat.sort_order = form.sort_order.data or 0
            cat.default_team_id = form.default_team_id.data or None
            db.session.flush()
            audit("category.save", "category", cat.id)
            db.session.commit()
            flash(_("Changes saved."), "success")
            return redirect(url_for("admin.categories"))
    return render_template("admin/simple_form.html", form=form, obj=cat, title=_("Category"),
                           back=url_for("admin.categories"))


# ============================================================ road sections
@bp.route("/sections", methods=["GET", "POST"])
@permission_required("sections.manage")
def sections():
    rows = db.session.execute(db.select(RoadSection).order_by(RoadSection.sort_order, RoadSection.km_start)).scalars().all()
    pts_form = RoadPointsForm(prefix="rp")
    if pts_form.validate_on_submit():
        if not current_user.can("settings.manage"):
            abort(403)
        parsed, errors = [], []
        for i, line in enumerate(pts_form.csv.data.splitlines(), 1):
            line = to_latin_digits(line).strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace(";", ",").split(",")]
            try:
                km, lat, lng = Decimal(parts[0]), Decimal(parts[1]), Decimal(parts[2])
                if not (-90 <= lat <= 90 and -180 <= lng <= 180 and km >= 0):
                    raise ValueError
                parsed.append((km, lat, lng, parts[3][:120] if len(parts) > 3 else None))
            except Exception:
                errors.append(i)
        if errors:
            flash(_("Invalid lines: %(lines)s", lines=", ".join(map(str, errors[:20]))), "danger")
        else:
            if pts_form.replace.data:
                db.session.execute(db.delete(RoadPoint))
            for km, lat, lng, label in parsed:
                existing = db.session.execute(db.select(RoadPoint).filter_by(km=km)).scalar_one_or_none()
                p = existing or RoadPoint(km=km)
                p.latitude, p.longitude, p.label = lat, lng, label
                db.session.add(p)
            audit("road_points.import", "road_points", None, count=len(parsed), replace=bool(pts_form.replace.data))
            db.session.commit()
            flash(_("%(n)s reference points saved.", n=len(parsed)), "success")
            return redirect(url_for("admin.sections"))
    npoints = db.session.execute(db.select(db.func.count(RoadPoint.id))).scalar_one()
    return render_template("admin/sections.html", sections=rows, pts_form=pts_form, npoints=npoints)


@bp.route("/sections/new", methods=["GET", "POST"])
@bp.route("/sections/<int:section_id>", methods=["GET", "POST"])
@permission_required("sections.manage")
def section_form(section_id=None):
    sec = db.session.get(RoadSection, section_id) if section_id else None
    if section_id and sec is None:
        abort(404)
    form = SectionForm()
    if request.method == "GET" and sec:
        _fill_translated(form, sec)
        form.km_start.data, form.km_end.data, form.sort_order.data = sec.km_start, sec.km_end, sec.sort_order
        form.road_status.data, form.visibility_pct.data = sec.road_status, sec.visibility_pct
    if form.validate_on_submit():
        if form.km_end.data < form.km_start.data:
            form.km_end.errors.append(_("End km must be greater than start km."))
        elif _code_taken(RoadSection, form.code.data.strip(), sec.id if sec else None):
            form.code.errors.append(_("This code is already used."))
        else:
            if sec is None:
                sec = RoadSection()
                db.session.add(sec)
            changed_condition = (sec.road_status != form.road_status.data or sec.visibility_pct != form.visibility_pct.data)
            _save_translated(sec, form)
            sec.km_start, sec.km_end, sec.sort_order = form.km_start.data, form.km_end.data, form.sort_order.data or 0
            sec.road_status, sec.visibility_pct = form.road_status.data, form.visibility_pct.data
            if changed_condition:
                sec.condition_updated_at = utcnow()
            db.session.flush()
            audit("section.save", "road_section", sec.id, road_status=sec.road_status, visibility=sec.visibility_pct)
            db.session.commit()
            flash(_("Changes saved."), "success")
            return redirect(url_for("admin.sections"))
    return render_template("admin/simple_form.html", form=form, obj=sec, title=_("Road section"),
                           back=url_for("admin.sections"))


# ============================================================ announcements
@bp.route("/announcements")
@permission_required("announcements.manage")
def announcements():
    q = db.select(Announcement).order_by(Announcement.created_at.desc())
    pagination = db.paginate(q, page=_page(), per_page=_per_page(), error_out=False)
    return render_template("admin/announcements.html", pagination=pagination)


def _deliver_announcement(ann: Announcement) -> int:
    """Create in-app notifications for all active users (respecting preferences) + push to all subscribers."""
    kind = ann.notification_kind
    title = {loc: ann.tr("title", loc) for loc in ("ar", "en")}
    body = {loc: (ann.tr("body", loc) or "")[:300] for loc in ("ar", "en")}
    url = url_for("main.alerts")
    notified = set()
    for u in db.session.execute(db.select(User).filter_by(active=True)).scalars():
        n = notify(u, kind, lambda: (title[_cur()], body[_cur()]), url=url, announcement=ann, push=True)
        if n is not None:
            notified.add(u.id)
    texts = {"title_ar": title["ar"], "title_en": title["en"], "body_ar": body["ar"], "body_en": body["en"]}
    broadcast_push(texts, url, kind, exclude_user_ids=notified)
    ann.notified_at = utcnow()
    return len(notified)


def _cur():
    from flask_babel import get_locale
    return get_locale().language


@bp.route("/announcements/new", methods=["GET", "POST"])
@bp.route("/announcements/<int:ann_id>", methods=["GET", "POST"])
@permission_required("announcements.manage")
def announcement_form(ann_id=None):
    ann = db.session.get(Announcement, ann_id) if ann_id else None
    if ann_id and ann is None:
        abort(404)
    form = AnnouncementForm()
    form.road_section_id.choices = [(0, "—")] + [
        (s.id, s.tr("name")) for s in db.session.execute(db.select(RoadSection).order_by(RoadSection.sort_order)).scalars()]
    if request.method == "GET" and ann:
        form.kind.data = ann.kind
        for loc in ("ar", "en"):
            t = ann._translation_for(loc)
            getattr(form, f"title_{loc}").data = t.title if t else ""
            getattr(form, f"body_{loc}").data = t.body if t else ""
        form.km_from.data, form.km_to.data = ann.km_from, ann.km_to
        form.road_section_id.data = ann.road_section_id or 0
        form.starts_at.data, form.ends_at.data = ann.starts_at, ann.ends_at
        form.is_published.data = ann.is_published
    if form.validate_on_submit():
        if ann is None:
            ann = Announcement(created_by_id=current_user.id)
            db.session.add(ann)
        ann.kind = form.kind.data
        for loc in ("ar", "en"):
            ann.set_translation(loc, title=getattr(form, f"title_{loc}").data.strip(),
                                body=(getattr(form, f"body_{loc}").data or "").strip() or None)
        ann.km_from, ann.km_to = form.km_from.data, form.km_to.data
        ann.road_section_id = form.road_section_id.data or None
        # form datetimes are local (Africa/Tripoli) → store UTC
        ann_tz = get_timezone()

        def to_utc(dt):
            if dt is None:
                return None
            aware = ann_tz.localize(dt) if hasattr(ann_tz, "localize") else dt.replace(tzinfo=ann_tz)
            return aware.astimezone(timezone.utc).replace(tzinfo=None)

        ann.starts_at = to_utc(form.starts_at.data) or ann.starts_at or utcnow()
        ann.ends_at = to_utc(form.ends_at.data)
        ann.is_published = bool(form.is_published.data)
        db.session.flush()
        sent = 0
        if ann.is_published and form.send_notification.data:
            sent = _deliver_announcement(ann)
        audit("announcement.save", "announcement", ann.id, published=ann.is_published, notified=sent)
        db.session.commit()
        flash(_("Changes saved.") + (" " + _("Notified users: %(n)s", n=sent) if sent else ""), "success")
        return redirect(url_for("admin.announcements"))
    return render_template("admin/announcement_form.html", form=form, ann=ann)


# ============================================================ messages
@bp.route("/messages")
@permission_required("messages.manage")
def messages():
    st = request.args.get("status")
    q = db.select(ContactMessage).order_by(ContactMessage.created_at.desc())
    if st in ContactMessage.STATUSES:
        q = q.filter_by(status=st)
    pagination = db.paginate(q, page=_page(), per_page=_per_page(), error_out=False)
    return render_template("admin/messages.html", pagination=pagination)


@bp.route("/messages/<int:msg_id>", methods=["GET", "POST"])
@permission_required("messages.manage")
def message_detail(msg_id):
    msg = db.session.get(ContactMessage, msg_id) or abort(404)
    form = MessageForm(obj=msg)
    if form.validate_on_submit():
        reply_changed = (form.reply.data or "").strip() and (form.reply.data or "").strip() != (msg.reply or "")
        msg.status = form.status.data
        msg.reply = (form.reply.data or "").strip() or None
        msg.handled_by_id, msg.handled_at = current_user.id, utcnow()
        if reply_changed:
            if msg.user:
                text = msg.reply
                notify(msg.user, "admin", lambda: (_("Reply from technical support"), text[:900]),
                       url=url_for("main.support"))
            elif looks_like_email(msg.contact):
                send_mail(msg.contact, _("Reply from technical support"), msg.reply)
        audit("message.update", "contact_message", msg.id, status=msg.status)
        db.session.commit()
        flash(_("Changes saved."), "success")
        return redirect(url_for("admin.messages"))
    return render_template("admin/message_detail.html", msg=msg, form=form)


# ============================================================ analytics
@bp.route("/analytics")
@permission_required("analytics.view")
def analytics():
    months, created, resolved = stats.over_time(12)
    return render_template(
        "admin/analytics.html",
        counts=stats.status_counts(), by_category=stats.by_category(), by_section=stats.by_section(),
        months=months, created=created, resolved=resolved, yearly=stats.yearly_summary(),
        workload=stats.employee_workload(), avg_response=stats.avg_response_hours(),
        avg_resolution=stats.avg_resolution_hours(), min_samples=get_setting("stats_min_samples", 3),
    )


# ============================================================ settings
@bp.route("/settings", methods=["GET", "POST"])
@permission_required("settings.manage")
def settings():
    if request.method == "POST":
        # CSRF is enforced globally by CSRFProtect for every POST
        changed = {}
        for key, (default, typ, _pub, _desc) in DEFAULT_SETTINGS.items():
            if typ == "bool":
                val = "true" if request.form.get(key) == "on" else "false"
            else:
                val = (request.form.get(key) or "").strip()[:500]
                if typ == "int":
                    try:
                        val = str(int(to_latin_digits(val)))
                    except ValueError:
                        flash(_("Invalid value for %(key)s", key=key), "danger")
                        continue
            if str(get_setting(key, default)).lower() != val.lower():
                changed[key] = val
                set_setting(key, val, current_user.id)
        audit("settings.update", "system_settings", None, changed=list(changed))
        db.session.commit()
        flash(_("Changes saved."), "success")
        return redirect(url_for("admin.settings"))
    values = {k: get_setting(k, d[0]) for k, d in DEFAULT_SETTINGS.items()}
    return render_template("admin/settings.html", defs=DEFAULT_SETTINGS, values=values)


# ============================================================ audit
@bp.route("/audit")
@permission_required("audit.view")
def audit_logs():
    q = db.select(AuditLog).order_by(AuditLog.created_at.desc())
    act = request.args.get("action", "").strip()
    if act:
        q = q.where(AuditLog.action.like(f"{act}%"))
    pagination = db.paginate(q, page=_page(), per_page=50, error_out=False)
    return render_template("admin/audit.html", pagination=pagination)
