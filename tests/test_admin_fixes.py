"""Admin fixes: pagination on every list, "My assignments", single activity log and note boxes,
auto-verified staff reports, merged dashboard."""
from app.extensions import db
from app.models import AuditLog, Notification, Report, ReportStatus

from .conftest import login
from .test_reports import _new_report


# ------------------------------------------------------------------ pagination (was a 500 on every 2nd+ page)
def test_audit_log_with_several_pages(client, users):
    for i in range(130):
        db.session.add(AuditLog(action="test.x", entity_type="report", entity_id=str(i), details={"i": i}))
    db.session.commit()
    login(client, "admin@example.ly")
    for page in (1, 2, 3):
        r = client.get(f"/admin/audit?page={page}&action=test.")
        assert r.status_code == 200, page
        html = r.get_data(as_text=True)
        assert "السابق" in html or page == 1
        assert "التالي" in html or page == 3
    # the filter is kept in the page links
    assert "action=test." in client.get("/admin/audit?action=test.").get_data(as_text=True)


def test_pager_does_not_break_translations_on_long_report_lists(app, client, users):
    app.config["ADMIN_PER_PAGE"] = 2
    login(client, "admin@example.ly")
    r = client.get("/admin/reports?page=2")
    assert r.status_code == 200 and "التالي" in r.get_data(as_text=True)


# ------------------------------------------------------------------ My assignments
def _assign_to_team(app, users, team_only=True):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    sup = app.test_client()
    login(sup, "0921000003")
    team_id = users["employee"].team_memberships[0].team_id
    data = {"as-team_id": team_id, "as-assignee_id": 0 if team_only else users["employee"].id, "as-note": "INSTR-1"}
    assert sup.post(f"/admin/reports/{rep.id}/assign", data=data).status_code == 302
    return rep, sup


def test_my_assignments_includes_team_assignments(app, users):
    rep, _ = _assign_to_team(app, users, team_only=True)
    emp = app.test_client()
    login(emp, "0921000002")
    html = emp.get("/admin/reports?mine=1").get_data(as_text=True)
    assert rep.reference in html
    assert "المهام المسندة إليّ" in html.split("<h1", 1)[1].split("</h1>", 1)[0]  # page title
    # filtering keeps the page on "My assignments"
    assert 'name="mine" value="1"' in html and "mine=1" in html
    # an employee of another team does not see it
    other = app.test_client()
    login(other, "0921000005")
    assert rep.reference not in other.get("/admin/reports?mine=1").get_data(as_text=True)


# ------------------------------------------------------------------ notes: one box per action, each text once
def test_assignment_instructions_shown_once(app, users):
    rep, sup = _assign_to_team(app, users)
    db.session.refresh(rep)
    assert all(h.internal_note != "INSTR-1" for h in rep.history)  # no copy in the status history
    html = sup.get(f"/admin/reports/{rep.id}").get_data(as_text=True)
    assert html.count("INSTR-1") == 1


def test_legacy_duplicated_instruction_is_hidden(app, users):
    rep, sup = _assign_to_team(app, users)
    db.session.refresh(rep)
    last = rep.history[-1]
    last.internal_note = "INSTR-1"  # how older data stored it
    db.session.commit()
    assert sup.get(f"/admin/reports/{rep.id}").get_data(as_text=True).count("INSTR-1") == 1


def test_report_page_has_one_note_box(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    sup = app.test_client()
    login(sup, "0921000003")
    html = sup.get(f"/admin/reports/{rep.id}").get_data(as_text=True)
    assert html.count("<textarea") == 2  # the note box and the assignment instructions
    assert 'name="nt-body"' in html and 'name="st-note"' not in html and 'name="st-visibility"' not in html
    assert "سجل النشاط" in html


def test_status_list_offers_new_verified_false_only(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    sup = app.test_client()
    login(sup, "0921000003")
    html = sup.get(f"/admin/reports/{rep.id}").get_data(as_text=True)
    options = html.split('name="st-to_status"', 1)[1].split("</select>", 1)[0]
    assert 'value="under_review"' in options and 'value="rejected"' in options and "زائف" in options
    for code in ("assigned", "in_progress", "resolved"):
        assert f'value="{code}"' not in options
    sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "under_review"})
    html = sup.get(f"/admin/reports/{rep.id}").get_data(as_text=True)
    options = html.split('name="st-to_status"', 1)[1].split("</select>", 1)[0]
    assert 'value="new"' in options and 'value="rejected"' in options and 'value="under_review"' not in options


# ------------------------------------------------------------------ false reports («زائف»): staff accounts only
def _false_report(app):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    rep.title = "FALSE-REPORT-T"
    db.session.commit()
    sup = app.test_client()
    login(sup, "0921000003")
    sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "rejected"})  # no reason needed
    db.session.refresh(rep)
    assert rep.status.code == "rejected" and rep.status.tr("name", "ar") == "زائف"
    return rep, citizen


def test_false_report_hidden_from_public_and_reporter(app, users):
    rep, citizen = _false_report(app)
    anon = app.test_client()
    for c in (anon, citizen):
        assert "FALSE-REPORT-T" not in c.get("/").get_data(as_text=True)
        assert "FALSE-REPORT-T" not in c.get("/reports/").get_data(as_text=True)
        assert c.get(f"/reports/{rep.reference}").status_code == 404
        assert c.get(f"/api/v1/reports/{rep.reference}").status_code == 404
        assert rep.reference not in c.get("/api/v1/reports").get_data(as_text=True)
    assert "FALSE-REPORT-T" not in citizen.get("/reports/?tab=mine").get_data(as_text=True)
    assert rep.reference not in citizen.get("/api/v1/reports?mine=1").get_data(as_text=True)
    assert citizen.get(f"/admin/reports/{rep.id}").status_code in (403, 404)
    # the reporter is not notified about a report they can no longer open
    updates = db.session.execute(db.select(Notification).filter_by(user_id=users["public"].id,
                                                                   kind="report_update")).scalars().all()
    assert [n.title_en for n in updates] == ["Report received"]


def test_false_report_visible_to_staff(app, users):
    rep, _ = _false_report(app)
    staff = app.test_client()
    login(staff, "admin@example.ly")
    assert staff.get(f"/admin/reports/{rep.id}").status_code == 200
    assert staff.get(f"/reports/{rep.reference}").status_code == 200
    assert "FALSE-REPORT-T" in staff.get("/admin/reports").get_data(as_text=True)


# ------------------------------------------------------------------ staff reports are verified automatically
def test_staff_report_is_verified_automatically(app, users):
    emp = app.test_client()
    login(emp, "0921000002")
    rep = _new_report(emp)
    assert rep.status.code == ReportStatus.UNDER_REVIEW
    assert rep.status.tr("name", "ar") == "متحقق منه" and rep.status.tr("name", "en") == "Verified"
    assert [h.to_status.code for h in rep.history] == ["new", "under_review"]
    assert rep.first_response_at is None  # not counted as a response to a citizen
    n = db.session.execute(db.select(Notification).filter_by(user_id=users["employee"].id)).scalars().all()
    assert any(x.title_ar == "نُشر البلاغ" for x in n)
    # public right away
    assert rep.reference in app.test_client().get("/reports/").get_data(as_text=True)


def test_citizen_report_stays_new(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    assert _new_report(citizen).status.code == ReportStatus.NEW


def test_api_staff_report_is_verified_too(app, users):
    emp = app.test_client()
    login(emp, "0921000002")
    from .test_reports import _cat_id
    r = emp.post("/api/v1/reports", data={"category_id": _cat_id(), "latitude": "31.36", "longitude": "16.06",
                                          "location_source": "gps", "severity": "low"})
    assert r.status_code == 201
    rep = db.session.execute(db.select(Report).filter_by(reference=r.get_json()["data"]["reference"])).scalar_one()
    assert rep.status.code == ReportStatus.UNDER_REVIEW


# ------------------------------------------------------------------ dashboard = analytics layout
def test_dashboard_is_the_analytics_view(client, users):
    login(client, "admin@example.ly")
    html = client.get("/admin/").get_data(as_text=True)
    assert 'id="chTime"' in html and 'id="chCat"' in html and "js/analytics.js" in html
    assert "/admin/analytics" not in html  # no separate menu entry any more


def test_employee_dashboard_limited_to_own_reports(client, users):
    login(client, "0921000002")
    r = client.get("/admin/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'id="chStatus"' in html and 'id="chTime"' not in html


# ------------------------------------------------------------------ migration c5e8a1d4b7f2 renames the live status
def test_migration_renames_under_review(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from flask_migrate import downgrade, upgrade

    import config
    from app import create_app
    from tests.test_drive import ROOT
    monkeypatch.setattr(config.TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    app = create_app("testing")
    mig = str(ROOT / "migrations")
    with app.app_context():
        upgrade(directory=mig, revision="a3d9c2e41f07")
        with db.engine.begin() as c:  # a database as it is on the live server today
            c.execute(sa.text("INSERT INTO report_statuses (id, code, sort_order, tone, is_final) "
                              "VALUES (2, 'under_review', 2, 'review', 0)"))
            c.execute(sa.text("INSERT INTO report_status_translations (status_id, locale, name) "
                              "VALUES (2, 'ar', 'قيد المراجعة'), (2, 'en', 'Under review')"))

        def names():
            with db.engine.connect() as c:
                return dict(c.execute(sa.text("SELECT locale, name FROM report_status_translations")).all())
        upgrade(directory=mig)
        assert names() == {"ar": "متحقق منه", "en": "Verified"}
        downgrade(directory=mig, revision="a3d9c2e41f07")
        assert names() == {"ar": "قيد المراجعة", "en": "Under review"}
        db.engine.dispose()


# ------------------------------------------------------------------ migration e7b3f9a2c6d1 renames «مرفوض» to «زائف»
def test_migration_renames_rejected_to_false_report(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from flask_migrate import downgrade, upgrade

    import config
    from app import create_app
    from tests.test_drive import ROOT
    monkeypatch.setattr(config.TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    app = create_app("testing")
    mig = str(ROOT / "migrations")
    with app.app_context():
        upgrade(directory=mig, revision="c5e8a1d4b7f2")
        with db.engine.begin() as c:
            c.execute(sa.text("INSERT INTO report_statuses (id, code, sort_order, tone, is_final) "
                              "VALUES (6, 'rejected', 6, 'rejected', 1)"))
            c.execute(sa.text("INSERT INTO report_status_translations (status_id, locale, name) "
                              "VALUES (6, 'ar', 'مرفوض'), (6, 'en', 'Rejected')"))

        def names():
            with db.engine.connect() as c:
                return dict(c.execute(sa.text("SELECT locale, name FROM report_status_translations")).all())
        upgrade(directory=mig)
        assert names() == {"ar": "زائف", "en": "False report"}
        downgrade(directory=mig, revision="c5e8a1d4b7f2")
        assert names() == {"ar": "مرفوض", "en": "Rejected"}
        db.engine.dispose()
