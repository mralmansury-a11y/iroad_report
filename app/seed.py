"""Initial (reference) data and optional demonstration data.

`flask seed`          → roles, permissions, statuses, categories, teams, settings (idempotent, safe in production)
`flask seed --demo`   → ALSO loads demonstration road sections / km points / sample reports.
                         Demo data is clearly labelled and MUST NOT be used in production: the km
                         reference points are illustrative and must be replaced by the official survey.
"""
import random
from datetime import timedelta
from decimal import Decimal

from .extensions import db
from .models import (
    Permission, Report, ReportCategory, ReportStatus, ReportStatusHistory, Role, RoadPoint, RoadSection,
    SystemSetting, Team, User, utcnow,
)
from .services.rbac import PERMISSIONS, ROLE_DEFS
from .services.settings import DEFAULT_SETTINGS

STATUSES = [
    # code, order, tone, final, ar, en
    ("new", 1, "new", False, "جديد", "New"),
    ("under_review", 2, "review", False, "قيد المراجعة", "Under review"),
    ("assigned", 3, "assigned", False, "تم الإسناد", "Assigned"),
    ("in_progress", 4, "progress", False, "قيد التنفيذ", "In progress"),
    ("resolved", 5, "done", True, "تم الإصلاح", "Resolved"),
    ("rejected", 6, "rejected", True, "مرفوض", "Rejected"),
]

TEAMS = [
    ("maintenance", "فريق الصيانة", "Maintenance"),
    ("inspection", "فريق التفتيش على الطريق", "Road Inspection"),
    ("lighting", "فريق الإنارة", "Lighting"),
    ("emergency", "فريق الاستجابة للطوارئ", "Emergency Response"),
    ("operations", "فريق التشغيل", "Operations"),
]

# Categories follow the Figma report screen (نوع العطل) + the specification list.
CATEGORIES = [
    # code, icon, order, default team, ar, en
    ("pothole", "bi-cone-striped", 1, "maintenance", "حفرة بالطريق", "Pothole"),
    ("lighting", "bi-lightbulb", 2, "lighting", "إنارة معطلة", "Street lighting problem"),
    ("accident", "bi-car-front", 3, "emergency", "حادث مروري", "Traffic accident"),
    ("crack", "bi-bricks", 4, "maintenance", "تصدع بالرصف", "Pavement crack"),
    ("animals", "bi-exclamation-octagon", 5, "operations", "حيوانات على الطريق", "Animals on the road"),
    ("obstruction", "bi-sign-stop", 6, "operations", "عائق على الطريق", "Road obstruction"),
    ("damage", "bi-cone", 7, "maintenance", "تلف بالطريق", "Road damage"),
    ("drainage", "bi-droplet-half", 8, "maintenance", "مشكلة تصريف مياه", "Drainage problem"),
    ("signage", "bi-signpost-split", 9, "inspection", "علامات مرورية غير واضحة", "Unclear road signs"),
    ("sand", "bi-wind", 10, "operations", "رمال متراكمة على الطريق", "Sand accumulation"),
    ("other", "bi-three-dots", 99, "inspection", "أخرى", "Other"),
]


def seed_reference():
    # permissions
    perms = {}
    for code, desc in PERMISSIONS.items():
        p = db.session.execute(db.select(Permission).filter_by(code=code)).scalar_one_or_none() or Permission(code=code)
        p.description = desc
        db.session.add(p)
        perms[code] = p
    # roles
    for code, (level, ar, en, plist) in ROLE_DEFS.items():
        r = db.session.execute(db.select(Role).filter_by(code=code)).scalar_one_or_none() or Role(code=code)
        r.level, r.name_ar, r.name_en = level, ar, en
        r.permissions = [perms[c] for c in plist]
        db.session.add(r)
    # statuses
    for code, order, tone, final, ar, en in STATUSES:
        s = db.session.execute(db.select(ReportStatus).filter_by(code=code)).scalar_one_or_none() or ReportStatus(code=code)
        s.sort_order, s.tone, s.is_final = order, tone, final
        db.session.add(s)
        s.set_translation("ar", name=ar)
        s.set_translation("en", name=en)
    # teams
    teams = {}
    for code, ar, en in TEAMS:
        t = db.session.execute(db.select(Team).filter_by(code=code)).scalar_one_or_none()
        if t is None:
            t = Team(code=code)
            db.session.add(t)
            t.set_translation("ar", name=ar)
            t.set_translation("en", name=en)
        teams[code] = t
    db.session.flush()
    # categories
    for code, icon, order, team, ar, en in CATEGORIES:
        c = db.session.execute(db.select(ReportCategory).filter_by(code=code)).scalar_one_or_none()
        if c is None:
            c = ReportCategory(code=code, icon=icon, sort_order=order, default_team_id=teams[team].id)
            db.session.add(c)
            c.set_translation("ar", name=ar)
            c.set_translation("en", name=en)
    # settings
    for key, (val, typ, pub, desc) in DEFAULT_SETTINGS.items():
        if db.session.execute(db.select(SystemSetting).filter_by(key=key)).scalar_one_or_none() is None:
            db.session.add(SystemSetting(key=key, value=val, value_type=typ, is_public=pub, description=desc))
    db.session.commit()


# ---------------------------------------------------------------- DEMO ONLY
DEMO_SECTIONS = [
    # code, km_start, km_end, ar, en
    ("S01", 0, 60, "قاطع 1 (تجريبي)", "Section 1 (demo)"),
    ("S02", 60, 130, "قاطع 2 (تجريبي)", "Section 2 (demo)"),
    ("S03", 130, 190, "قاطع 3 (تجريبي)", "Section 3 (demo)"),
    ("SRT", 190, 250, "قاطع سرت", "Sirte section"),
    ("S05", 250, 320, "قاطع 5 (تجريبي)", "Section 5 (demo)"),
    ("S06", 320, 400, "القاطع 6 (تجريبي)", "Section 6 (demo)"),
]

# ILLUSTRATIVE ONLY: rough coastal-road path between Misrata and Ras Lanuf.
# km values are NOT official markers — replace via Admin → Road sections → Reference points.
DEMO_POINTS = [
    (0, 32.3170, 15.0950), (50, 31.9900, 15.3200), (100, 31.6000, 15.6400), (150, 31.3600, 16.0600),
    (214, 31.2050, 16.5880), (260, 31.0800, 17.0200), (320, 30.8200, 17.6500), (400, 30.5200, 18.4200),
]

DEMO_REPORTS = [
    ("pothole", "حفرة عميقة قرب القاطع 6", "high", 214, 0.2, "new"),
    ("lighting", "عمود إنارة مطفأ", "medium", 198, 1, "under_review"),
    ("crack", "تصدع في حارة الشاحنات", "medium", 176, 24, "resolved"),
    ("signage", "علامات مرورية غير واضحة", "low", 160, 48, "assigned"),
    ("animals", "حيوانات على الطريق ليلاً", "high", 145, 72, "in_progress"),
    ("sand", "رمال متراكمة على الرصيف", "medium", 130, 168, "resolved"),
]


def seed_demo():
    for code, a, b, ar, en in DEMO_SECTIONS:
        if db.session.execute(db.select(RoadSection).filter_by(code=code)).scalar_one_or_none() is None:
            s = RoadSection(code=code, km_start=a, km_end=b, sort_order=a, road_status="open")
            db.session.add(s)
            s.set_translation("ar", name=ar)
            s.set_translation("en", name=en)
    for km, lat, lng in DEMO_POINTS:
        if db.session.execute(db.select(RoadPoint).filter_by(km=km)).scalar_one_or_none() is None:
            db.session.add(RoadPoint(km=km, latitude=Decimal(str(lat)), longitude=Decimal(str(lng)), label="demo"))
    db.session.flush()

    if db.session.execute(db.select(Report.id)).first() is None:
        demo_user = db.session.execute(db.select(User).filter_by(phone="0910000001")).scalar_one_or_none()
        if demo_user is None:
            demo_user = User(full_name="مستخدم تجريبي", phone="0910000001", locale="ar")
            demo_user.set_password("Demo12345")
            demo_user.roles.append(db.session.execute(db.select(Role).filter_by(code="public")).scalar_one())
            db.session.add(demo_user)
            db.session.flush()
        sts = {s.code: s for s in db.session.execute(db.select(ReportStatus)).scalars()}
        from .services.geo import coordinates_from_km, section_for_km
        now = utcnow()
        for cat_code, title, sev, km, hours_ago, st in DEMO_REPORTS:
            cat = db.session.execute(db.select(ReportCategory).filter_by(code=cat_code)).scalar_one()
            created = now - timedelta(hours=hours_ago)
            coords = coordinates_from_km(km)
            r = Report(title=title, category=cat, severity=sev, km_marker=km, status=sts[st], language="ar",
                       reporter=demo_user, created_at=created, updated_at=created,
                       road_section=section_for_km(km), location_source="manual",
                       latitude=Decimal(f"{coords[0]:.6f}") if coords else None,
                       longitude=Decimal(f"{coords[1]:.6f}") if coords else None,
                       description="بيانات تجريبية لأغراض العرض فقط.")
            db.session.add(r)
            db.session.flush()
            r.reference = f"IR-{created.year}-{r.id:06d}"
            db.session.add(ReportStatusHistory(report_id=r.id, to_status_id=sts["new"].id, created_at=created))
            if st != "new":
                r.first_response_at = created + timedelta(minutes=random.randint(30, 240))
                db.session.add(ReportStatusHistory(report_id=r.id, from_status_id=sts["new"].id,
                                                   to_status_id=sts[st].id, created_at=r.first_response_at))
            if st == "resolved":
                r.resolved_at = created + timedelta(hours=random.randint(6, 40))
    db.session.commit()
