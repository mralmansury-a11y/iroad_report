from app.extensions import db
from app.models import (
    Notification, PointsTransaction, Report, ReportAttachment, ReportCategory, ReportStatus, ReportStatusHistory,
)

from .conftest import login, png_bytes


def _cat_id(code="pothole"):
    return db.session.execute(db.select(ReportCategory.id).filter_by(code=code)).scalar_one()


def test_submit_report_logged_in(client, users, app):
    login(client, "0921000001")
    r = client.post("/reports/new", data={
        "category_id": _cat_id(), "latitude": "31.205000", "longitude": "16.588000", "location_source": "gps", "severity": "high", "description": "حفرة كبيرة",
        "images": (png_bytes(), "photo.png")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "/reports/submitted/IR-" in r.headers["Location"]
    rep = db.session.execute(db.select(Report).order_by(Report.id.desc())).scalars().first()
    assert rep.reference.startswith("IR-") and rep.status.code == "new"
    assert rep.road_section is not None and rep.road_section.code == "SRT"  # km → section
    assert rep.title  # defaulted from category
    assert len(rep.attachments) == 1 and rep.attachments[0].mime_type == "image/jpeg"
    assert db.session.execute(db.select(Notification).filter_by(user_id=users["public"].id)).first() is not None
    # owner can view the attachment, anonymous cannot
    att = rep.attachments[0]
    assert client.get(f"/reports/attachment/{att.id}").status_code == 200
    anon = app.test_client()
    assert anon.get(f"/reports/attachment/{att.id}").status_code == 404


def test_report_validation(client, users):
    login(client, "0921000001")
    r = client.post("/reports/new", data={"severity": "high"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 422
    errs = r.get_json()["error"]["fields"]
    assert "category_id" in errs and "latitude" in errs  # location required (GPS or map only)


def test_manual_km_is_ignored(client, users):
    """The form no longer accepts typed km/section: they are derived from the coordinates on the server."""
    login(client, "0921000001")
    r = client.post("/reports/new", data={"category_id": _cat_id(), "km_marker": "999", "road_section_id": "1",
                                          "severity": "low"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 422
    r = client.post("/reports/new", data={"category_id": _cat_id(), "km_marker": "999", "latitude": "31.205",
                                          "longitude": "16.588", "location_source": "map", "severity": "low"},
                    headers={"X-Requested-With": "fetch"})
    rep = db.session.execute(db.select(Report).filter_by(reference=r.get_json()["reference"])).scalar_one()
    assert abs(float(rep.km_marker) - 214) < 1 and rep.location_source == "map"


def test_off_road_point_kept_without_km(client, users):
    login(client, "0921000001")
    r = client.post("/reports/new", data={"category_id": _cat_id(), "latitude": "25.0", "longitude": "10.0",
                                          "location_source": "gps", "severity": "low"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 201
    rep = db.session.execute(db.select(Report).filter_by(reference=r.get_json()["reference"])).scalar_one()
    assert rep.km_marker is None and float(rep.latitude) == 25.0


def test_reject_non_image_upload(client, users):
    login(client, "0921000001")
    import io
    r = client.post("/reports/new", data={
        "category_id": _cat_id(), "latitude": "31.6", "longitude": "15.64", "severity": "low",
        "images": (io.BytesIO(b"#!/bin/sh\necho pwned"), "evil.jpg")}, content_type="multipart/form-data",
        headers={"X-Requested-With": "fetch"})
    assert r.status_code == 422
    assert db.session.execute(db.select(db.func.count(ReportAttachment.id))).scalar_one() == 0


def test_reject_bad_extension(client, users):
    login(client, "0921000001")
    r = client.post("/reports/new", data={
        "category_id": _cat_id(), "latitude": "31.6", "longitude": "15.64", "severity": "low",
        "images": (png_bytes(), "shell.php")}, content_type="multipart/form-data", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 422


def test_guest_report_and_tracking(app):
    c = app.test_client()
    r = c.post("/reports/new", data={"category_id": _cat_id("lighting"), "latitude": "31.24", "longitude": "16.45", "severity": "medium",
                                     "guest_name": "زائر", "guest_phone": "0919998877"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code == 201
    ref = r.get_json()["reference"]
    assert c.get(f"/reports/{ref}").status_code == 200  # tracked in session
    other = app.test_client()
    page = other.get(f"/reports/{ref}").get_data(as_text=True)
    assert "0919998877" not in page  # no personal data in public view
    r = other.post("/reports/track", data={"reference": ref, "phone": "0919998877"})
    assert r.status_code == 302
    r = other.post("/reports/track", data={"reference": ref, "phone": "0910000000"})
    assert r.status_code == 200  # wrong phone → no access


def test_guest_requires_phone(app):
    c = app.test_client()
    r = c.post("/reports/new", data={"category_id": _cat_id(), "latitude": "31.99", "longitude": "15.32", "severity": "low"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code in (200, 422)
    assert db.session.execute(db.select(db.func.count(Report.id)).filter(Report.latitude == 31.99)).scalar_one() == 0


def _new_report(client):
    r = client.post("/reports/new", data={"category_id": _cat_id(), "latitude": "31.36", "longitude": "16.06",
                                         "location_source": "gps", "severity": "high"},
                    headers={"X-Requested-With": "fetch"})
    return db.session.execute(db.select(Report).filter_by(reference=r.get_json()["reference"])).scalar_one()


def test_full_workflow_history_points(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)

    sup = app.test_client()
    login(sup, "0921000003")
    r = sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "under_review", "st-internal_note": "check"})
    assert r.status_code == 302
    team_id = users["employee"].team_memberships[0].team_id
    r = sup.post(f"/admin/reports/{rep.id}/assign", data={"as-team_id": team_id, "as-assignee_id": users["employee"].id})
    assert r.status_code == 302
    db.session.refresh(rep)
    assert rep.status.code == "assigned" and rep.assigned_user_id == users["employee"].id
    assert rep.first_response_at is not None

    emp = app.test_client()
    login(emp, "0921000002")
    assert emp.get(f"/admin/reports/{rep.id}").status_code == 200
    emp.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "in_progress"})
    emp.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "resolved", "st-public_note": "تم الردم"})
    db.session.refresh(rep)
    assert rep.status.code == "resolved" and rep.resolved_at is not None
    hist = [h.to_status.code for h in rep.history]
    assert hist == ["new", "under_review", "assigned", "in_progress", "resolved"]
    pts = db.session.execute(db.select(PointsTransaction).filter_by(user_id=users["public"].id)).scalars().all()
    assert sum(p.points for p in pts) == 20
    db.session.refresh(users["public"])
    assert users["public"].points == 20
    kinds = {n.kind for n in db.session.execute(db.select(Notification).filter_by(user_id=users["public"].id)).scalars()}
    assert {"report_update", "points"} <= kinds
    # bilingual system notification
    n = db.session.execute(db.select(Notification).filter_by(user_id=users["public"].id, kind="points")).scalars().first()
    assert n.title_ar == "نقاط جديدة" and n.title_en == "New points"


def test_invalid_transition_rejected(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    sup = app.test_client()
    login(sup, "0921000003")
    sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "resolved"})  # new → resolved not allowed
    db.session.refresh(rep)
    assert rep.status.code == "new"
    sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "rejected"})  # missing reason
    db.session.refresh(rep)
    assert rep.status.code == "new"


def test_employee_cannot_touch_unassigned(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    emp = app.test_client()
    login(emp, "0921000005")
    assert emp.get(f"/admin/reports/{rep.id}").status_code == 404
    emp.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "under_review"})
    db.session.refresh(rep)
    assert rep.status.code == "new"


def test_internal_notes_hidden_from_reporter(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    sup = app.test_client()
    login(sup, "0921000003")
    sup.post(f"/admin/reports/{rep.id}/note", data={"nt-body": "SECRET-INTERNAL", "nt-visibility": "internal"})
    sup.post(f"/admin/reports/{rep.id}/note", data={"nt-body": "PUBLIC-REPLY", "nt-visibility": "public"})
    sup.post(f"/admin/reports/{rep.id}/status", data={"st-to_status": "under_review", "st-internal_note": "HIDDEN-NOTE"})
    page = citizen.get(f"/reports/{rep.reference}").get_data(as_text=True)
    assert "PUBLIC-REPLY" in page and "SECRET-INTERNAL" not in page and "HIDDEN-NOTE" not in page
    api = citizen.get(f"/api/v1/reports/{rep.reference}").get_json()["data"]
    assert "SECRET-INTERNAL" not in str(api) and "HIDDEN-NOTE" not in str(api)


def test_status_history_relationships(app, users):
    citizen = app.test_client()
    login(citizen, "0921000001")
    rep = _new_report(citizen)
    h = db.session.execute(db.select(ReportStatusHistory).filter_by(report_id=rep.id)).scalar_one()
    assert h.to_status.code == ReportStatus.NEW and h.from_status_id is None
    assert rep.reporter.id == users["public"].id and rep.category.code == "pothole"
