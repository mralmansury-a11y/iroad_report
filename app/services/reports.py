"""Report business logic: creation, workflow transitions, assignment, notes, points.

Route handlers stay thin and call these functions; the same functions back the
HTML views and the JSON API (so future mobile apps reuse identical rules).
"""
from dataclasses import dataclass
from decimal import Decimal

from flask import url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import (
    EmployeeAssignment, PointsTransaction, Report, ReportAttachment, ReportNote, ReportStatus,
    ReportStatusHistory, Team, TeamMember, User, utcnow,
)
from .audit import audit
from .geo import section_for_km
from .notify import notify
from .settings import get_setting
from .uploads import UploadError, save_image

# Allowed workflow transitions (supervisors / admins)
TRANSITIONS: dict[str, tuple[str, ...]] = {
    ReportStatus.NEW: (ReportStatus.UNDER_REVIEW, ReportStatus.ASSIGNED, ReportStatus.REJECTED),
    ReportStatus.UNDER_REVIEW: (ReportStatus.ASSIGNED, ReportStatus.IN_PROGRESS, ReportStatus.RESOLVED, ReportStatus.REJECTED),
    ReportStatus.ASSIGNED: (ReportStatus.IN_PROGRESS, ReportStatus.UNDER_REVIEW, ReportStatus.REJECTED),
    ReportStatus.IN_PROGRESS: (ReportStatus.RESOLVED, ReportStatus.ASSIGNED),
    ReportStatus.RESOLVED: (ReportStatus.IN_PROGRESS,),       # re-open
    ReportStatus.REJECTED: (ReportStatus.UNDER_REVIEW,),      # re-open
}
# Field employees may only progress work that is assigned to them / their team
EMPLOYEE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ReportStatus.ASSIGNED: (ReportStatus.IN_PROGRESS,),
    ReportStatus.IN_PROGRESS: (ReportStatus.RESOLVED,),
}


class WorkflowError(ValueError):
    pass


def status_by_code(code: str) -> ReportStatus:
    st = db.session.execute(db.select(ReportStatus).filter_by(code=code)).scalar_one_or_none()
    if st is None:
        raise WorkflowError(f"Unknown status {code}")
    return st


# ---------------------------------------------------------------- visibility

def user_team_ids(user: User) -> list[int]:
    return [m.team_id for m in user.team_memberships]


def is_assigned_to(user: User, report: Report) -> bool:
    return report.assigned_user_id == user.id or (
        report.assigned_team_id is not None and report.assigned_team_id in user_team_ids(user)
    )


def can_view_report(user, report: Report) -> bool:
    if user is None or not user.is_authenticated:
        return False
    if report.reporter_id == user.id:
        return True
    if user.can("reports.view_all"):
        return True
    return user.can("reports.view_assigned") and is_assigned_to(user, report)


def staff_reports_query(user: User):
    q = db.select(Report)
    if not user.can("reports.view_all"):
        tids = user_team_ids(user)
        cond = Report.assigned_user_id == user.id
        if tids:
            cond = cond | Report.assigned_team_id.in_(tids)
        q = q.where(cond)
    return q


def allowed_next_statuses(user: User, report: Report) -> list[str]:
    cur = report.status_code
    if user.can("reports.review"):
        return list(TRANSITIONS.get(cur, ()))
    if user.can("reports.update_status") and is_assigned_to(user, report):
        return list(EMPLOYEE_TRANSITIONS.get(cur, ()))
    return []


# ---------------------------------------------------------------- creation

@dataclass
class ReportInput:
    title: str
    category_id: int
    description: str | None = None
    severity: str = "medium"
    km_marker: Decimal | None = None
    road_section_id: int | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    location_source: str = "manual"
    language: str = "ar"
    guest_name: str | None = None
    guest_phone: str | None = None


def create_report(data: ReportInput, reporter: User | None, files=()) -> Report:
    """Create a report inside a single transaction (all-or-nothing, including images)."""
    files = [f for f in (files or []) if f and getattr(f, "filename", "")]
    from flask import current_app
    if len(files) > current_app.config["MAX_IMAGES_PER_REPORT"]:
        raise UploadError(_("You can attach up to %(n)s images.", n=current_app.config["MAX_IMAGES_PER_REPORT"]))

    section_id = data.road_section_id
    if section_id is None and data.km_marker is not None:
        sec = section_for_km(data.km_marker)
        section_id = sec.id if sec else None

    new_status = status_by_code(ReportStatus.NEW)
    stored = []
    try:
        for f in files:
            stored.append(save_image(f))
        report = Report(
            title=data.title.strip(),
            description=(data.description or "").strip() or None,
            language=data.language if data.language in ("ar", "en") else "ar",
            category_id=data.category_id,
            status=new_status,
            severity=data.severity if data.severity in Report.SEVERITIES else "medium",
            km_marker=data.km_marker,
            road_section_id=section_id,
            latitude=data.latitude,
            longitude=data.longitude,
            location_source=data.location_source if data.location_source in ("gps", "manual", "map") else "manual",
            reporter_id=reporter.id if reporter else None,
            guest_name=None if reporter else (data.guest_name or "").strip() or None,
            guest_phone=None if reporter else (data.guest_phone or "").strip() or None,
        )
        db.session.add(report)
        db.session.flush()
        report.reference = f"IR-{report.created_at.year}-{report.id:06d}"
        for s in stored:
            db.session.add(ReportAttachment(
                report_id=report.id, stored_name=s.stored_name, original_name=s.original_name,
                mime_type=s.mime_type, size_bytes=s.size_bytes, width=s.width, height=s.height,
                uploaded_by_id=reporter.id if reporter else None,
            ))
        db.session.add(ReportStatusHistory(report_id=report.id, from_status_id=None, to_status_id=new_status.id,
                                           changed_by_id=reporter.id if reporter else None))
        if reporter:
            ref = report.reference
            notify(reporter, "report_update",
                   lambda: (_("Report received"), _("Your report %(ref)s was received and will be reviewed.", ref=ref)),
                   url=url_for("reports.detail", reference=ref), report=report)
        audit("report.create", "report", report.id, user=reporter, reference=report.reference)
        db.session.commit()
        return report
    except Exception:
        db.session.rollback()
        from .uploads import delete_stored
        for s in stored:
            delete_stored(s.stored_name)
        raise


# ---------------------------------------------------------------- workflow

def change_status(report: Report, actor: User, to_code: str, public_note: str | None = None,
                  internal_note: str | None = None, commit: bool = True) -> ReportStatusHistory:
    if to_code not in allowed_next_statuses(actor, report):
        raise WorkflowError(_("This status change is not allowed."))
    if to_code == ReportStatus.REJECTED and not (public_note or "").strip():
        raise WorkflowError(_("Please give the reporter a reason for rejection."))
    old = report.status
    new = status_by_code(to_code)
    now = utcnow()
    report.status = new
    if report.first_response_at is None and old.code == ReportStatus.NEW:
        report.first_response_at = now
    if to_code == ReportStatus.RESOLVED:
        report.resolved_at = now
        for a in report.assignments:
            if a.is_active:
                a.completed_at = now
                a.is_active = False
    elif old.code == ReportStatus.RESOLVED:
        report.resolved_at = None
    h = ReportStatusHistory(report_id=report.id, from_status_id=old.id, to_status_id=new.id, changed_by_id=actor.id,
                            public_note=(public_note or "").strip() or None,
                            internal_note=(internal_note or "").strip() or None)
    db.session.add(h)

    _award_points(report, to_code)
    _notify_reporter_status(report, to_code, h.public_note)
    audit("report.status", "report", report.id, user=actor, from_=old.code, to=to_code)
    if commit:
        db.session.commit()
    return h


def _notify_reporter_status(report: Report, to_code: str, note: str | None):
    if not report.reporter:
        return
    ref, title = report.reference, report.title
    st = status_by_code(to_code)

    def render():
        if to_code == ReportStatus.UNDER_REVIEW:
            t = _("Your report was accepted")
            b = _('Report "%(title)s" is now under review.', title=title)
        elif to_code == ReportStatus.RESOLVED:
            t = _("Report resolved")
            b = _('Report "%(title)s" has been fixed. Thank you for your contribution.', title=title)
        elif to_code == ReportStatus.REJECTED:
            t = _("Report rejected")
            b = _('Report "%(title)s" was rejected.', title=title)
        else:
            t = _("Report status updated")
            b = _('Report "%(title)s" is now: %(status)s', title=title, status=st.tr("name"))
        if note:
            b = f"{b} — {note}"
        return t, b

    notify(report.reporter, "report_update", render, url=url_for("reports.detail", reference=ref), report=report)


def _award_points(report: Report, to_code: str):
    if not report.reporter_id:
        return
    reason, pts = None, 0
    if to_code == ReportStatus.RESOLVED:
        reason, pts = "resolved", int(get_setting("points_per_resolved", 20) or 0)
    elif to_code == ReportStatus.UNDER_REVIEW:
        reason, pts = "accepted", int(get_setting("points_per_accepted", 0) or 0)
    if not reason or pts <= 0:
        return
    exists = db.session.execute(db.select(PointsTransaction).filter_by(
        user_id=report.reporter_id, report_id=report.id, reason=reason)).scalar_one_or_none()
    if exists:
        return
    db.session.add(PointsTransaction(user_id=report.reporter_id, report_id=report.id, points=pts, reason=reason))
    user = db.session.get(User, report.reporter_id)
    user.points = (user.points or 0) + pts
    report.points_awarded = True
    title = report.title
    notify(user, "points", lambda: (_("New points"),
                                    _('You earned %(n)s points for your report "%(title)s".', n=pts, title=title)),
           url=url_for("main.profile"), report=report)


def assign_report(report: Report, actor: User, team_id: int | None, assignee_id: int | None,
                  note: str | None = None) -> EmployeeAssignment:
    if not actor.can("reports.assign"):
        raise WorkflowError(_("You are not allowed to assign reports."))
    if team_id is None and assignee_id is None:
        raise WorkflowError(_("Choose a team or an employee."))
    team = db.session.get(Team, team_id) if team_id else None
    assignee = db.session.get(User, assignee_id) if assignee_id else None
    if assignee is not None and (not assignee.is_staff or not assignee.is_active):
        raise WorkflowError(_("The selected employee is not an active staff member."))
    if assignee is not None and team is not None:
        if not any(m.team_id == team.id for m in assignee.team_memberships):
            raise WorkflowError(_("The employee is not a member of the selected team."))
    for a in report.assignments:
        if a.is_active:
            a.is_active = False
    a = EmployeeAssignment(report_id=report.id, team_id=team.id if team else None,
                           assignee_id=assignee.id if assignee else None, assigned_by_id=actor.id,
                           note=(note or "").strip() or None)
    db.session.add(a)
    report.assigned_team_id = team.id if team else None
    report.assigned_user_id = assignee.id if assignee else None

    if report.status_code in (ReportStatus.NEW, ReportStatus.UNDER_REVIEW, ReportStatus.IN_PROGRESS):
        old = report.status
        new = status_by_code(ReportStatus.ASSIGNED)
        if report.first_response_at is None:
            report.first_response_at = utcnow()
        report.status = new
        db.session.add(ReportStatusHistory(report_id=report.id, from_status_id=old.id, to_status_id=new.id,
                                           changed_by_id=actor.id, internal_note=a.note))
        _notify_reporter_status(report, ReportStatus.ASSIGNED, None)

    # notify assignee / team members
    recipients = set()
    if assignee:
        recipients.add(assignee)
    elif team:
        recipients.update(m.user for m in team.members if m.user.is_active)
    ref, title = report.reference, report.title
    for u in recipients:
        notify(u, "assignment", lambda: (_("New assignment"),
                                         _('Report %(ref)s "%(title)s" was assigned to you.', ref=ref, title=title)),
               url=url_for("admin.report_detail", report_id=report.id), report=report)
    audit("report.assign", "report", report.id, user=actor, team_id=team_id, assignee_id=assignee_id)
    db.session.commit()
    return a


def add_note(report: Report, actor: User, body: str, is_internal: bool = True) -> ReportNote:
    body = (body or "").strip()
    if not body:
        raise WorkflowError(_("The note is empty."))
    if not actor.can("reports.internal_notes"):
        raise WorkflowError(_("You are not allowed to add notes."))
    n = ReportNote(report_id=report.id, author_id=actor.id, body=body[:5000], is_internal=is_internal)
    db.session.add(n)
    if not is_internal and report.reporter:
        ref, title = report.reference, report.title
        notify(report.reporter, "report_update",
               lambda: (_("New response on your report"), _('The road team replied to "%(title)s".', title=title)),
               url=url_for("reports.detail", reference=ref), report=report)
    audit("report.note", "report", report.id, user=actor, internal=is_internal)
    db.session.commit()
    return n


def team_members_for_select():
    rows = db.session.execute(
        db.select(TeamMember).join(User).where(User.active.is_(True))
    ).scalars().all()
    return rows
