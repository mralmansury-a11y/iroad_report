"""Operational statistics computed from real database records.

When there is not enough data an indicator returns None and the UI shows "—"
instead of a misleading number.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func

from ..extensions import db
from ..models import (
    EmployeeAssignment, Report, ReportCategory, ReportStatus, RoadSection, User, utcnow,
)
from .settings import get_setting


def _avg_hours(pairs) -> float | None:
    vals = [(b - a).total_seconds() / 3600 for a, b in pairs if a and b and b >= a]
    if len(vals) < int(get_setting("stats_min_samples", 3) or 3):
        return None
    return sum(vals) / len(vals)


def avg_response_hours(days: int = 30) -> float | None:
    since = utcnow() - timedelta(days=days)
    rows = db.session.execute(
        db.select(Report.created_at, Report.first_response_at)
        .where(Report.created_at >= since, Report.first_response_at.is_not(None))
    ).all()
    return _avg_hours(rows)


def avg_resolution_hours(days: int = 90) -> float | None:
    since = utcnow() - timedelta(days=days)
    rows = db.session.execute(
        db.select(Report.created_at, Report.resolved_at)
        .where(Report.created_at >= since, Report.resolved_at.is_not(None))
    ).all()
    return _avg_hours(rows)


def open_status_ids() -> list[int]:
    return list(db.session.execute(
        db.select(ReportStatus.id).where(ReportStatus.code.in_(ReportStatus.OPEN))).scalars())


def nearby_open_count(km: float | None, radius: float | None = None) -> int | None:
    if km is None:
        return None
    radius = radius or float(get_setting("nearby_radius_km", 20) or 20)
    return db.session.execute(
        db.select(func.count(Report.id)).where(
            Report.status_id.in_(open_status_ids()),
            Report.km_marker.between(km - radius, km + radius),
        )
    ).scalar_one()


def nearby_markers(km: float | None, radius: float | None = None, limit: int = 12):
    if km is None:
        return []
    radius = radius or float(get_setting("nearby_radius_km", 20) or 20)
    rows = db.session.execute(
        db.select(Report).where(
            Report.status_id.in_(open_status_ids()),
            Report.km_marker.between(km - radius, km + radius),
        ).order_by(Report.created_at.desc()).limit(limit)
    ).scalars().all()
    return [{"km": r.km_float(), "severity": r.severity, "status": r.status_code, "title": r.title} for r in rows]


def home_metrics(km: float | None, section: RoadSection | None) -> dict:
    return {
        "km": km,
        "section": section.tr("name") if section else None,
        "road_status": section.road_status if section else None,
        "visibility_pct": section.visibility_pct if section else None,
        "nearby_count": nearby_open_count(km),
        "avg_response_hours": avg_response_hours(),
        "radius_km": int(get_setting("nearby_radius_km", 20) or 20),
    }


def status_counts() -> dict[str, int]:
    rows = db.session.execute(
        db.select(ReportStatus.code, func.count(Report.id))
        .select_from(ReportStatus).outerjoin(Report, Report.status_id == ReportStatus.id)
        .group_by(ReportStatus.code)
    ).all()
    out = {code: 0 for code in ReportStatus.ALL}
    out.update({c: n for c, n in rows})
    out["total"] = sum(out[c] for c in ReportStatus.ALL)
    return out


def by_category():
    rows = db.session.execute(
        db.select(ReportCategory, func.count(Report.id))
        .outerjoin(Report, Report.category_id == ReportCategory.id)
        .group_by(ReportCategory.id).order_by(func.count(Report.id).desc())
    ).all()
    return [(c.tr("name"), n) for c, n in rows]


def by_section():
    rows = db.session.execute(
        db.select(RoadSection, func.count(Report.id))
        .outerjoin(Report, Report.road_section_id == RoadSection.id)
        .group_by(RoadSection.id).order_by(RoadSection.sort_order)
    ).all()
    return [(s.tr("name"), n) for s, n in rows]


def over_time(months: int = 12):
    """Monthly counts for the last `months` months (computed in Python for DB portability)."""
    now = utcnow()
    y, m = now.year, now.month - (months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    start = now.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
    created = db.session.execute(db.select(Report.created_at).where(Report.created_at >= start)).scalars().all()
    resolved = db.session.execute(db.select(Report.resolved_at).where(Report.resolved_at >= start)).scalars().all()
    keys = []
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    c1 = Counter(d.strftime("%Y-%m") for d in created)
    c2 = Counter(d.strftime("%Y-%m") for d in resolved if d)
    return keys, [c1.get(k, 0) for k in keys], [c2.get(k, 0) for k in keys]


def yearly_summary():
    rows = db.session.execute(db.select(Report.created_at, Report.resolved_at)).all()
    out = defaultdict(lambda: {"created": 0, "resolved": 0})
    for c, r in rows:
        out[c.year]["created"] += 1
        if r:
            out[r.year]["resolved"] += 1
    return dict(sorted(out.items(), reverse=True))


def employee_workload():
    active = dict(db.session.execute(
        db.select(EmployeeAssignment.assignee_id, func.count(EmployeeAssignment.id))
        .where(EmployeeAssignment.is_active.is_(True), EmployeeAssignment.assignee_id.is_not(None))
        .group_by(EmployeeAssignment.assignee_id)).all())
    done = dict(db.session.execute(
        db.select(EmployeeAssignment.assignee_id, func.count(EmployeeAssignment.id))
        .where(EmployeeAssignment.completed_at.is_not(None), EmployeeAssignment.assignee_id.is_not(None))
        .group_by(EmployeeAssignment.assignee_id)).all())
    ids = set(active) | set(done)
    if not ids:
        return []
    users = db.session.execute(db.select(User).where(User.id.in_(ids))).scalars().all()
    return sorted(
        [{"user": u, "active": active.get(u.id, 0), "done": done.get(u.id, 0)} for u in users],
        key=lambda r: -r["active"],
    )


def user_contribution(user: User) -> dict:
    sent = db.session.execute(db.select(func.count(Report.id)).where(Report.reporter_id == user.id)).scalar_one()
    accepted = db.session.execute(
        db.select(func.count(Report.id)).join(ReportStatus)
        .where(Report.reporter_id == user.id,
               ReportStatus.code.notin_([ReportStatus.NEW, ReportStatus.REJECTED]))
    ).scalar_one()
    return {"sent": sent, "accepted": accepted, "points": user.points or 0}
