from app.extensions import db
from app.models import Announcement, Notification, ReportCategory, Role, SystemSetting, User

from .conftest import login

ADMIN_PAGES = ["/admin/", "/admin/reports", "/admin/users", "/admin/teams", "/admin/categories", "/admin/sections",
               "/admin/announcements", "/admin/messages", "/admin/analytics", "/admin/settings", "/admin/audit",
               "/admin/employees"]


def test_anonymous_redirected_from_admin(client):
    for p in ADMIN_PAGES:
        r = client.get(p)
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"], p


def test_public_user_forbidden(client, users):
    login(client, "0921000001")
    for p in ADMIN_PAGES:
        assert client.get(p).status_code == 403, p


def test_employee_limited(client, users):
    login(client, "0921000002")
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/reports").status_code == 200
    for p in ("/admin/users", "/admin/settings", "/admin/audit", "/admin/categories", "/admin/analytics"):
        assert client.get(p).status_code == 403, p


def test_supervisor_vs_admin(client, users):
    login(client, "0921000003")
    assert client.get("/admin/analytics").status_code == 200
    assert client.get("/admin/announcements").status_code == 200
    assert client.get("/admin/settings").status_code == 403
    assert client.get("/admin/users/new").status_code == 403


def test_admin_pages_render(client, users):
    login(client, "root@example.ly")
    for p in ADMIN_PAGES + ["/admin/reports/1", "/admin/users/new", "/admin/teams/new", "/admin/categories/new",
                            "/admin/sections/new", "/admin/announcements/new"]:
        assert client.get(p).status_code == 200, p


def test_admin_cannot_grant_superadmin(client, users):
    login(client, "admin@example.ly")
    super_role = db.session.execute(db.select(Role).filter_by(code="superadmin")).scalar_one()
    client.post("/admin/users/new", data={"full_name": "Escalate", "phone": "0927777777", "locale": "ar",
                                              "password": "Passw0rd1", "roles": [super_role.id], "active": "y"})
    u = db.session.execute(db.select(User).filter_by(phone="0927777777")).scalar_one_or_none()
    assert u is None or not u.has_role("superadmin")  # invalid choice → rejected


def test_admin_create_employee_and_deactivate(client, users):
    login(client, "admin@example.ly")
    emp_role = db.session.execute(db.select(Role).filter_by(code="employee")).scalar_one()
    client.post("/admin/users/new", data={"full_name": "New Tech", "phone": "0928888888", "locale": "en",
                                          "password": "Passw0rd1", "roles": [emp_role.id], "active": "y"})
    u = db.session.execute(db.select(User).filter_by(phone="0928888888")).scalar_one()
    assert u.is_staff
    client.post(f"/admin/users/{u.id}/toggle")
    db.session.refresh(u)
    assert not u.active


def test_category_bilingual_crud(client, users):
    login(client, "admin@example.ly")
    r = client.post("/admin/categories/new", data={"code": "fog", "name_ar": "ضباب", "name_en": "Fog",
                                                   "icon": "bi-cloud-fog", "sort_order": 50, "is_active": "y",
                                                   "default_team_id": 0})
    assert r.status_code == 302
    c = db.session.execute(db.select(ReportCategory).filter_by(code="fog")).scalar_one()
    assert c.tr("name", "ar") == "ضباب" and c.tr("name", "en") == "Fog"


def test_settings_update_and_audit(client, users):
    login(client, "admin@example.ly")
    client.post("/admin/settings", data={"nearby_radius_km": "35", "site_open_for_reports": "on"})
    row = db.session.execute(db.select(SystemSetting).filter_by(key="nearby_radius_km")).scalar_one()
    assert row.value == "35"
    row = db.session.execute(db.select(SystemSetting).filter_by(key="allow_guest_reports")).scalar_one()
    assert row.value == "false"  # unchecked switch


def test_announcement_publish_notifies(client, users):
    login(client, "0921000003")
    r = client.post("/admin/announcements/new", data={
        "kind": "weather", "title_ar": "ضباب كثيف", "title_en": "Dense fog", "body_ar": "بين كم 150 و170",
        "body_en": "Between km 150 and 170", "km_from": "150", "km_to": "170", "road_section_id": 0,
        "is_published": "y", "send_notification": "y"})
    assert r.status_code == 302
    a = db.session.execute(db.select(Announcement)).scalar_one()
    assert a.notified_at is not None
    n = db.session.execute(db.select(Notification).filter_by(user_id=users["public"].id, kind="weather")).scalar_one()
    assert n.title_ar == "ضباب كثيف" and n.title_en == "Dense fog"
    assert client.get("/alerts").status_code == 200
