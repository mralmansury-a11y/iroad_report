"""Driving mode: nearby API, Libya boundary, report validation, settings, page, migration, JS engine."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Report, ReportCategory, ReportStatus
from app.services.drive import DriveConfig, drive_config, validate_drive_settings
from app.services.geo import (
    LIBYA_BBOX, BBoxBoundary, PolygonBoundary, bounding_box, haversine_km, is_in_libya, valid_coordinates,
)
from app.services.settings import DEFAULT_SETTINGS, set_setting

from .conftest import login

ROOT = Path(__file__).resolve().parents[1]
# Sabha area: inside Libya and > 400 km from the demo reports on the coastal road (test isolation).
SABHA = (27.0377, 14.4283)
KM_PER_DEG_LAT = math.pi * 6371.0 / 180.0


def north_of(origin, km):
    return origin[0] + km / KM_PER_DEG_LAT, origin[1]


_seq = iter(range(1, 10_000))


def make_report(lat, lng, status="assigned", severity="high", category="pothole"):
    cat = db.session.execute(db.select(ReportCategory).filter_by(code=category)).scalar_one()
    st = db.session.execute(db.select(ReportStatus).filter_by(code=status)).scalar_one()
    r = Report(title=f"Test {status}", category_id=cat.id, status_id=st.id, severity=severity,
               latitude=round(lat, 6), longitude=round(lng, 6), location_source="gps", reference=f"TST-{next(_seq):05d}")
    db.session.add(r)
    db.session.commit()
    return r


def nearby(client, **params):
    return client.post("/api/v1/reports/nearby", json=params)


def refs(resp):
    return [i["reference"] for i in resp.get_json()["data"]["items"]]


# ------------------------------------------------------------------ geo service
class TestLibyaBoundary:
    @pytest.mark.parametrize("lat,lng", [
        (32.8872, 13.1913),   # Tripoli
        (32.1167, 20.0667),   # Benghazi
        SABHA,
        (25.0, 10.0),         # south-west desert (used by existing tests)
        (19.5, 9.3), (33.5, 25.2), (19.5, 25.2), (33.5, 9.3),  # bbox corners are inclusive
    ])
    def test_inside(self, lat, lng):
        assert is_in_libya(lat, lng)

    @pytest.mark.parametrize("lat,lng", [
        (36.8065, 10.1815),   # Tunis
        (30.0444, 31.2357),   # Cairo
        (19.4999, 15.0), (33.5001, 15.0), (25.0, 9.2999), (25.0, 25.2001),  # just outside each edge
        (0, 0), (-27.0, -14.4),
    ])
    def test_outside(self, lat, lng):
        assert not is_in_libya(lat, lng)

    @pytest.mark.parametrize("lat,lng", [(None, 15), (25, None), ("abc", 15), (float("nan"), 15),
                                         (25, float("inf")), (91, 15), (25, 181)])
    def test_invalid_values_are_never_inside(self, lat, lng):
        assert not valid_coordinates(lat, lng) and not is_in_libya(lat, lng)

    def test_accepts_strings_and_decimals(self):
        from decimal import Decimal
        assert is_in_libya("32.88", "13.19") and is_in_libya(Decimal("32.88"), Decimal("13.19"))

    def test_pluggable_polygon_boundary(self):
        """The interface accepts a polygon later without changes (synthetic shapes, not real borders)."""
        square = PolygonBoundary([(0, 0), (0, 10), (10, 10), (10, 0)])
        assert is_in_libya(5, 5, boundary=square) and not is_in_libya(11, 5, boundary=square)
        triangle = PolygonBoundary([(0, 0), (10, 0), (0, 10)])
        assert triangle.contains(2, 2) and not triangle.contains(6, 6)
        assert is_in_libya(1, 1, boundary=BBoxBoundary(0, 2, 0, 2))

    def test_bbox_constants(self):
        assert LIBYA_BBOX.as_dict() == {"min_lat": 19.5, "max_lat": 33.5, "min_lng": 9.3, "max_lng": 25.2}

    @pytest.mark.parametrize("lat", [0.0, 27.0, 33.0, 60.0])
    def test_bounding_box_contains_the_circle(self, lat):
        min_lat, max_lat, min_lng, max_lng = bounding_box(lat, 15.0, 30)
        for brg in range(0, 360, 15):
            # point at exactly 30 km on bearing `brg`
            d = 30 / 6371.0
            p1, l1, th = math.radians(lat), math.radians(15.0), math.radians(brg)
            p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(th))
            l2 = l1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
            assert min_lat <= math.degrees(p2) <= max_lat and min_lng <= math.degrees(l2) <= max_lng


# ------------------------------------------------------------------ settings
class TestDriveSettings:
    def test_defaults(self, app):
        c = drive_config()
        assert (c.enabled, c.alert_statuses, c.far_m, c.near_m, c.fetch_radius_km, c.cone_deg, c.refresh_s) == \
            (True, ("assigned", "in_progress"), 5000, 500, 30, 40, 120)

    def test_all_defaults_are_seeded(self, app):
        from app.models import SystemSetting
        keys = {k for k in DEFAULT_SETTINGS if k.startswith("drive_")}
        assert len(keys) == 7
        rows = db.session.execute(db.select(SystemSetting.key).where(SystemSetting.key.in_(keys))).scalars().all()
        assert set(rows) == keys

    def test_bad_stored_values_are_clamped(self, app):
        set_setting("drive_alert_far_m", "abc")
        set_setting("drive_cone_deg", "500")
        set_setting("drive_fetch_radius_km", "999")
        set_setting("drive_alert_near_m", "9000")      # not smaller than far
        set_setting("drive_alert_statuses", '["resolved", "bogus", "assigned", "assigned"]')
        db.session.commit()
        c = drive_config()
        assert c.far_m == 5000 and c.cone_deg == 90 and c.fetch_radius_km == 50
        assert c.near_m < c.far_m
        assert c.alert_statuses == ("assigned",)  # final/unknown statuses can never trigger alerts

    def test_invalid_json_falls_back_to_default(self, app):
        set_setting("drive_alert_statuses", "not json")
        db.session.commit()
        assert drive_config().alert_statuses == ("assigned", "in_progress")

    def test_validation(self):
        assert validate_drive_settings({"drive_alert_far_m": "5000", "drive_alert_near_m": "500",
                                        "drive_alert_statuses": ["assigned"]}) == []
        assert validate_drive_settings({"drive_alert_far_m": "500", "drive_alert_near_m": "500"}) == \
            ["drive_alert_far_m", "drive_alert_near_m"]
        assert set(validate_drive_settings({"drive_cone_deg": "0", "drive_refresh_s": "x", "drive_fetch_radius_km": "51"})) == \
            {"drive_cone_deg", "drive_refresh_s", "drive_fetch_radius_km"}
        assert validate_drive_settings({"drive_alert_statuses": []}) == ["drive_alert_statuses"]
        assert validate_drive_settings({"drive_alert_statuses": ["resolved"]}) == ["drive_alert_statuses"]

    def test_validation_uses_stored_value_of_a_rejected_partner(self):
        stored = {"drive_alert_far_m": "1000", "drive_alert_near_m": "500", "drive_fetch_radius_km": "30"}
        # far is out of range → rejected; near=4000 must then be compared with the stored far (1000)
        assert set(validate_drive_settings({"drive_alert_far_m": "30000", "drive_alert_near_m": "4000"}, stored)) ==             {"drive_alert_far_m", "drive_alert_near_m"}
        # near alone is checked against the stored far as well
        assert validate_drive_settings({"drive_alert_near_m": "1500"}, stored) == ["drive_alert_near_m"]
        assert validate_drive_settings({"drive_alert_near_m": "900"}, stored) == []

    def test_validation_fetch_radius_must_cover_far_distance(self):
        stored = {"drive_alert_far_m": "5000", "drive_alert_near_m": "500", "drive_fetch_radius_km": "30"}
        assert validate_drive_settings({"drive_fetch_radius_km": "5"}, stored) == ["drive_fetch_radius_km"]
        assert validate_drive_settings({"drive_fetch_radius_km": "6"}, stored) == []
        assert validate_drive_settings({"drive_alert_far_m": "20000"}, {**stored, "drive_fetch_radius_km": "10"}) ==             ["drive_alert_far_m"]

    def test_refresh_distance_keeps_far_alert_inside_fetched_circle(self):
        def cfg(radius, far):
            return DriveConfig(True, (), far, 100, radius, 40, 120)
        assert cfg(30, 5000).refresh_dist_m == 10000          # capped
        assert cfg(8, 5000).refresh_dist_m == 3000            # radius - far
        assert cfg(6, 5000).refresh_dist_m == 1000            # minimum
        for radius, far in [(30, 5000), (8, 5000), (6, 5000), (21, 20000)]:
            c = cfg(radius, far)
            assert c.fetch_radius_km * 1000 >= c.far_m + c.refresh_dist_m
        assert cfg(8, 5000).client_dict()["refresh_dist_m"] == 3000

    def test_stored_radius_too_small_for_far_is_raised(self, app):
        set_setting("drive_alert_far_m", "5000")
        set_setting("drive_fetch_radius_km", "2")
        db.session.commit()
        c = drive_config()
        assert c.fetch_radius_km == 6 and c.fetch_radius_km * 1000 >= c.far_m + c.refresh_dist_m


# ------------------------------------------------------------------ POST /api/v1/reports/nearby
class TestNearbyApi:
    def test_only_verified_statuses(self, client):
        for st in ReportStatus.ALL:
            make_report(*north_of(SABHA, 2), status=st)
        r = nearby(client, lat=SABHA[0], lng=SABHA[1])
        assert r.status_code == 200
        items = r.get_json()["data"]["items"]
        assert sorted(i["status"]["code"] for i in items) == ["assigned", "in_progress"]

    def test_payload_fields(self, client):
        rep = make_report(*north_of(SABHA, 3), status="in_progress", severity="medium")
        body = nearby(client, lat=SABHA[0], lng=SABHA[1]).get_json()["data"]
        item = body["items"][0]
        assert item["reference"] == rep.reference
        assert set(item) >= {"reference", "lat", "lng", "severity", "category", "title", "status", "updated_at", "distance_m"}
        assert item["category"]["code"] == "pothole" and item["category"]["name"] and item["category"]["icon"]
        assert item["severity"]["code"] == "medium" and item["severity"]["name"]
        assert abs(item["distance_m"] - 3000) < 5
        assert item["updated_at"].endswith("Z") and body["generated_at"].endswith("Z")
        assert body["count"] == 1 and body["radius_km"] == 30
        assert "guest_phone" not in json.dumps(body) and "reporter" not in json.dumps(body)

    def test_sorted_by_distance(self, client):
        far = make_report(*north_of(SABHA, 20))
        near = make_report(*north_of(SABHA, 1))
        mid = make_report(*north_of(SABHA, 8))
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1])) == [near.reference, mid.reference, far.reference]

    def test_radius_is_respected(self, client):
        r10 = make_report(*north_of(SABHA, 10))
        r40 = make_report(*north_of(SABHA, 40))
        make_report(*north_of(SABHA, 60))
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=30)) == [r10.reference]
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=45)) == [r10.reference, r40.reference]
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=9.9)) == []

    def test_radius_is_capped_at_50_km(self, client):
        r40 = make_report(*north_of(SABHA, 40))
        make_report(*north_of(SABHA, 60))
        body = nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=500).get_json()["data"]
        assert body["radius_km"] == 50 and [i["reference"] for i in body["items"]] == [r40.reference]

    def test_default_radius_comes_from_settings(self, client):
        make_report(*north_of(SABHA, 10))
        set_setting("drive_fetch_radius_km", "8")
        db.session.commit()
        body = nearby(client, lat=SABHA[0], lng=SABHA[1]).get_json()["data"]
        assert body["radius_km"] == 8 and body["items"] == []

    def test_configured_statuses(self, client):
        new = make_report(*north_of(SABHA, 2), status="new")
        make_report(*north_of(SABHA, 2), status="assigned")
        set_setting("drive_alert_statuses", '["new"]')
        db.session.commit()
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1])) == [new.reference]

    @pytest.mark.parametrize("body", [{}, {"lat": 27}, {"lng": 14}, {"lat": "abc", "lng": 14}, {"lat": 91, "lng": 14},
                                      {"lat": 27, "lng": 181}, {"lat": "nan", "lng": 14}, {"lat": 27, "lng": "inf"},
                                      {"lat": True, "lng": 14}, {"lat": [27], "lng": 14}])
    def test_invalid_coordinates(self, client, body):
        r = client.post("/api/v1/reports/nearby", json=body)
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "invalid_coordinates"

    def test_non_json_body_is_rejected(self, client):
        r = client.post("/api/v1/reports/nearby", data="lat=27&lng=14", content_type="text/plain")
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "invalid_coordinates"

    def test_position_never_in_the_url(self, client):
        """GET with the position in the query string is refused: URLs end up in the access logs."""
        r = client.get(f"/api/v1/reports/nearby?lat={SABHA[0]}&lng={SABHA[1]}")
        assert r.status_code in (404, 405)  # GET /reports/<reference> treats "nearby" as an unknown reference

    def test_no_csrf_needed_for_this_read_only_post(self, app, client):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            r = nearby(client, lat=SABHA[0], lng=SABHA[1])
        finally:
            app.config["WTF_CSRF_ENABLED"] = False
        assert r.status_code == 200

    @pytest.mark.parametrize("lat,lng", [(36.8065, 10.1815), (30.0444, 31.2357), (0, 0)])
    def test_outside_libya(self, client, lat, lng):
        r = nearby(client, lat=lat, lng=lng)
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "outside_libya"

    @pytest.mark.parametrize("radius", ["0", "-5", "abc", "nan", "inf"])
    def test_invalid_radius(self, client, radius):
        r = nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=radius)
        assert r.status_code == 422 and r.get_json()["error"]["code"] == "invalid_radius"

    def test_arabic_digits_accepted(self, client):
        make_report(*north_of(SABHA, 1))
        r = client.post("/api/v1/reports/nearby", json={"lat": "٢٧.٠٣٧٧", "lng": "14.4283"})
        assert r.status_code == 200 and r.get_json()["data"]["count"] == 1

    def test_disabled_returns_404(self, client):
        set_setting("drive_mode_enabled", False)
        db.session.commit()
        r = nearby(client, lat=SABHA[0], lng=SABHA[1])
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "drive_disabled"

    def test_not_cached_and_localized(self, client):
        make_report(*north_of(SABHA, 1))
        r = nearby(client, lat=SABHA[0], lng=SABHA[1])
        assert "no-store" in r.headers["Cache-Control"]
        assert r.get_json()["data"]["items"][0]["category"]["name"] == "حفرة بالطريق"
        client.get("/lang/en")
        assert nearby(client, lat=SABHA[0], lng=SABHA[1]).get_json()["data"]["items"][0]["category"]["name"] == "Pothole"

    def test_position_is_not_stored(self, client, app):
        """The request must not write anything (no tracking of the driver)."""
        from app.models import AuditLog
        before = db.session.execute(db.select(db.func.count(AuditLog.id))).scalar_one()
        nearby(client, lat=SABHA[0], lng=SABHA[1])
        assert db.session.execute(db.select(db.func.count(AuditLog.id))).scalar_one() == before

    def test_uses_haversine_not_only_the_box(self, client):
        # A point in the bounding-box corner is ~42 km away for a 30 km radius → excluded.
        corner = (SABHA[0] + 30 / KM_PER_DEG_LAT, SABHA[1] + 30 / (KM_PER_DEG_LAT * math.cos(math.radians(SABHA[0]))))
        assert haversine_km(*SABHA, *corner) > 30
        make_report(*corner)
        assert refs(nearby(client, lat=SABHA[0], lng=SABHA[1], radius_km=30)) == []


# ------------------------------------------------------------------ GET /api/v1/reports/alertable (offline list)
class TestAlertableApi:
    URL = "/api/v1/reports/alertable"

    def test_only_alertable_statuses_no_position_needed(self, client):
        for st in ReportStatus.ALL:
            make_report(*north_of(SABHA, 2), status=st)
        r = client.get(self.URL)
        assert r.status_code == 200
        items = r.get_json()["data"]["items"]
        assert sorted(i["status"]["code"] for i in items if i["reference"].startswith("TST-")) == ["assigned", "in_progress"]

    def test_whole_country_and_public_fields_only(self, client):
        far_away = make_report(32.8872, 13.1913)        # Tripoli, > 600 km from Sabha
        make_report(36.8065, 10.1815)                    # Tunis: outside Libya, never listed
        body = client.get(self.URL).get_json()["data"]
        refs_ = [i["reference"] for i in body["items"]]
        assert far_away.reference in refs_ and body["count"] == len(body["items"])
        assert all(abs(i["lat"] - 36.8065) > 1e-6 for i in body["items"])
        item = next(i for i in body["items"] if i["reference"] == far_away.reference)
        assert set(item) == {"reference", "lat", "lng", "title", "severity", "category", "status", "km_label", "updated_at"}
        assert "reporter" not in json.dumps(body) and "guest_phone" not in json.dumps(body)

    def test_etag_and_not_modified(self, client):
        make_report(*north_of(SABHA, 2))
        r1 = client.get(self.URL)
        etag = r1.headers["ETag"]
        assert etag.startswith('"') and "no-store" in r1.headers["Cache-Control"]
        r2 = client.get(self.URL, headers={"If-None-Match": etag})
        assert r2.status_code == 304 and r2.get_data() == b"" and r2.headers["ETag"] == etag
        make_report(*north_of(SABHA, 3))                 # list changed → full response with a new ETag
        r3 = client.get(self.URL, headers={"If-None-Match": etag})
        assert r3.status_code == 200 and r3.headers["ETag"] != etag

    def test_etag_depends_on_language(self, client):
        make_report(*north_of(SABHA, 2))
        ar = client.get(self.URL).headers["ETag"]
        client.get("/lang/en")
        assert client.get(self.URL, headers={"If-None-Match": ar}).status_code == 200

    def test_configured_statuses_and_disabled(self, client):
        new = make_report(*north_of(SABHA, 2), status="new")
        set_setting("drive_alert_statuses", '["new"]')
        db.session.commit()
        items = client.get(self.URL).get_json()["data"]["items"]
        assert [i["reference"] for i in items if i["reference"].startswith("TST-")] == [new.reference]
        set_setting("drive_mode_enabled", False)
        db.session.commit()
        r = client.get(self.URL)
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "drive_disabled"


# ------------------------------------------------------------------ report creation inside Libya only
class TestReportsInsideLibya:
    def _cat(self):
        return db.session.execute(db.select(ReportCategory.id).filter_by(code="pothole")).scalar_one()

    def test_api_rejects_outside(self, client, users):
        login(client, "0921000001")
        r = client.post("/api/v1/reports", data={"category_id": self._cat(), "latitude": "36.8065", "longitude": "10.1815"})
        assert r.status_code == 422 and "latitude" in r.get_json()["error"]["fields"]
        assert db.session.execute(db.select(db.func.count(Report.id)).filter(Report.latitude == 36.8065)).scalar_one() == 0

    def test_api_accepts_inside(self, client, users):
        login(client, "0921000001")
        r = client.post("/api/v1/reports", data={"category_id": self._cat(), "latitude": "27.0377", "longitude": "14.4283"})
        assert r.status_code == 201

    def test_api_requires_both_coordinates(self, client, users):
        login(client, "0921000001")
        r = client.post("/api/v1/reports", data={"category_id": self._cat(), "latitude": "27.0377"})
        assert r.status_code == 422 and "latitude" in r.get_json()["error"]["fields"]

    def test_api_without_coordinates_still_allowed(self, client, users):
        login(client, "0921000001")
        r = client.post("/api/v1/reports", data={"category_id": self._cat(), "km_marker": "120"})
        assert r.status_code == 201

    def test_web_form_rejects_outside(self, client, users):
        login(client, "0921000001")
        r = client.post("/reports/new", data={"category_id": self._cat(), "latitude": "30.0444", "longitude": "31.2357",
                                              "location_source": "gps", "severity": "low"},
                        headers={"X-Requested-With": "fetch"})
        assert r.status_code == 422 and "latitude" in r.get_json()["error"]["fields"]

    def test_web_form_message_is_translated(self, client, users):
        login(client, "0921000001")
        r = client.post("/reports/new", data={"category_id": self._cat(), "latitude": "30.0444", "longitude": "31.2357",
                                              "location_source": "gps", "severity": "low"},
                        headers={"X-Requested-With": "fetch"})
        assert "يجب أن يكون الموقع داخل ليبيا." in r.get_json()["error"]["fields"]["latitude"]

    def test_web_form_accepts_inside(self, client, users):
        login(client, "0921000001")
        r = client.post("/reports/new", data={"category_id": self._cat(), "latitude": "27.0377", "longitude": "14.4283",
                                              "location_source": "gps", "severity": "low"},
                        headers={"X-Requested-With": "fetch"})
        assert r.status_code == 201


# ------------------------------------------------------------------ /drive page and home button
class TestDrivePage:
    def test_page_both_languages(self, client):
        for lang, word in (("ar", "وضع القيادة"), ("en", "Driving mode")):
            client.get(f"/lang/{lang}")
            r = client.get("/drive")
            html = r.get_data(as_text=True)
            assert r.status_code == 200 and word in html
            assert 'id="drive-config"' in html and "js/drive.js" in html and "js/geo.js" in html and "js/drive-engine.js" in html
        assert 'dir="ltr"' in html

    def test_config_comes_from_settings(self, client):
        set_setting("drive_alert_far_m", "4000")
        set_setting("drive_cone_deg", "30")
        db.session.commit()
        html = client.get("/drive").get_data(as_text=True)
        raw = html.split('id="drive-config">', 1)[1].split("</script>", 1)[0]
        cfg = json.loads(raw)
        assert cfg["far_m"] == 4000 and cfg["near_m"] == 500 and cfg["cone_deg"] == 30
        assert cfg["fetch_radius_km"] == 30 and cfg["refresh_s"] == 120 and cfg["enabled"] is True
        assert cfg["libya_bbox"] == LIBYA_BBOX.as_dict() and cfg["endpoint"] == "/api/v1/reports/nearby"
        assert cfg["simulate"] is False and "sim" not in cfg and "alert_statuses" not in cfg
        assert "{category}" in cfg["i18n"]["alertFar"] and "{distance}" in cfg["i18n"]["alertNear"]

    def test_home_button_and_page_follow_the_setting(self, client):
        assert 'data-testid="start-driving"' in client.get("/").get_data(as_text=True)
        set_setting("drive_mode_enabled", False)
        db.session.commit()
        assert 'data-testid="start-driving"' not in client.get("/").get_data(as_text=True)
        assert client.get("/drive").status_code == 404

    def test_simulator_never_without_flag(self, client):
        html = client.get("/drive?simulate=1").get_data(as_text=True)
        assert "drive-sim.js" not in html

    def test_simulator_with_development_flag(self, client, app):
        app.config["DRIVE_SIMULATOR"] = True
        assert "drive-sim.js" not in client.get("/drive").get_data(as_text=True)
        html = client.get("/drive?simulate=1&lat=27.03&lng=14.42&speed=40").get_data(as_text=True)
        assert "drive-sim.js" in html
        cfg = json.loads(html.split('id="drive-config">', 1)[1].split("</script>", 1)[0])
        assert cfg["simulate"] is True and cfg["sim"]["lat"] == 27.03 and cfg["sim"]["speed_mps"] == 40

    def test_production_hard_disables_simulator(self, monkeypatch):
        import config
        from app import create_app
        monkeypatch.setattr(config.ProductionConfig, "SECRET_KEY", "x" * 32)
        monkeypatch.setattr(config.ProductionConfig, "SQLALCHEMY_DATABASE_URI", "mysql+pymysql://u:p@127.0.0.1/none")
        monkeypatch.setattr(config.ProductionConfig, "DRIVE_SIMULATOR", True)
        assert create_app("production").config["DRIVE_SIMULATOR"] is False
        assert config.DevelopmentConfig.DRIVE_SIMULATOR is True and config.TestingConfig.DRIVE_SIMULATOR is False

    def test_no_inline_script_and_strict_csp(self, client):
        r = client.get("/drive")
        html = r.get_data(as_text=True)
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
        # only JSON data blocks are inline
        import re
        for tag in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html):
            assert 'type="application/json"' in tag

    def test_service_worker_rules(self, client):
        sw = client.get("/sw.js").get_data(as_text=True)
        assert r"/^\/drive$/" in sw and r"/^\/api\/v1\/reports\/(nearby|alertable)/" in sw
        assert '"/static/js/drive-engine.js"' in sw and '"/static/js/geo.js"' in sw
        assert "drive-sim.js" not in sw

    def test_service_worker_offline_support(self, client):
        sw = client.get("/sw.js").get_data(as_text=True)
        assert '"/static/js/offline-store.js"' in sw and '"/static/js/map.js"' in sw
        # viewed tiles are kept (CORS only, bounded); the drive and map pages open offline
        assert "TILE_CACHE" in sw and "TILE_MAX_ENTRIES" in sw and 'res.type === "opaque"' in sw
        assert r"const OFFLINE_APP_PAGES = [/^\/drive$/, /^\/map$/]" in sw
        assert 'postMessage({ type: "CLEAR_PRIVATE" })' in (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")

    def test_tile_hosts_allowed_for_the_service_worker(self, client):
        csp = client.get("/drive").headers["Content-Security-Policy"]
        connect = next(p for p in csp.split(";") if p.strip().startswith("connect-src"))
        assert "'self'" in connect and "https://tile.openstreetmap.org" in connect

    def test_page_loads_offline_store(self, client):
        html = client.get("/drive").get_data(as_text=True)
        assert "js/offline-store.js" in html
        cfg = json.loads(html.split('id="drive-config">', 1)[1].split("</script>", 1)[0])
        assert cfg["hazards_endpoint"] == "/api/v1/reports/alertable" and cfg["road_endpoint"] == "/api/v1/road"


# ------------------------------------------------------------------ admin settings form
class TestAdminDriveSettings:
    def _form(self, **overrides):
        from app.services.settings import get_setting
        data = {}
        for key, (_d, typ, *_r) in DEFAULT_SETTINGS.items():
            v = get_setting(key)
            if typ == "bool":
                if v:
                    data[key] = "on"
            elif typ == "json":
                data[key] = list(v or [])
            else:
                data[key] = "" if v is None else str(v)
        data.update(overrides)
        return data

    def test_page_shows_drive_settings(self, client, users):
        login(client, "admin@example.ly")
        html = client.get("/admin/settings").get_data(as_text=True)
        assert "drive_alert_far_m" in html and 'name="drive_alert_statuses" value="assigned"' in html

    def test_save_valid(self, client, users):
        login(client, "admin@example.ly")
        r = client.post("/admin/settings", data=self._form(drive_alert_far_m="3000", drive_alert_near_m="300",
                                                         drive_cone_deg="35", drive_alert_statuses=["in_progress"]))
        assert r.status_code == 302
        c = drive_config()
        assert (c.far_m, c.near_m, c.cone_deg, c.alert_statuses) == (3000, 300, 35, ("in_progress",))

    def test_reject_invalid(self, client, users):
        login(client, "admin@example.ly")
        client.post("/admin/settings", data=self._form(drive_alert_far_m="400", drive_alert_near_m="450",
                                                     drive_fetch_radius_km="80", drive_alert_statuses=[]))
        c = drive_config()
        assert (c.far_m, c.near_m, c.fetch_radius_km, c.alert_statuses) == (5000, 500, 30, ("assigned", "in_progress"))
        # a valid value submitted together with invalid ones is still saved
        client.post("/admin/settings", data=self._form(drive_cone_deg="25", drive_fetch_radius_km="80"))
        assert drive_config().cone_deg == 25 and drive_config().fetch_radius_km == 30

    def test_partial_save_is_not_reported_as_success(self, client, users):
        login(client, "admin@example.ly")
        # far is out of range (rejected); near=5000 is in range but not below the stored far (5000)
        r = client.post("/admin/settings", data=self._form(drive_alert_far_m="30000", drive_alert_near_m="5000"),
                        follow_redirects=True)
        html = r.get_data(as_text=True)
        assert "تم حفظ التغييرات." not in html and "تم حفظ بقية التغييرات." in html
        c = drive_config()
        assert (c.far_m, c.near_m) == (5000, 500)

    def test_toggle_off(self, client, users):
        login(client, "admin@example.ly")
        form = self._form()
        form.pop("drive_mode_enabled")
        client.post("/admin/settings", data=form)
        assert drive_config().enabled is False

    def test_public_user_cannot_change(self, client, users):
        login(client, "0921000001")
        client.post("/admin/settings", data=self._form(drive_alert_far_m="3000"))
        assert drive_config().far_m == 5000


# ------------------------------------------------------------------ Alembic migration
def test_migration_upgrade_downgrade(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from flask_migrate import downgrade, upgrade

    import config
    from app import create_app
    monkeypatch.setattr(config.TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{(tmp_path / 'mig.db').as_posix()}")
    app = create_app("testing")
    mig_dir = str(ROOT / "migrations")
    with app.app_context():
        engine = db.engine

        def indexes():
            return {i["name"]: i["column_names"] for i in sa.inspect(engine).get_indexes("reports")}

        upgrade(directory=mig_dir)
        assert indexes()["ix_reports_lat_lng"] == ["latitude", "longitude"]
        downgrade(directory=mig_dir, revision="6818f5288d1c")
        assert "ix_reports_lat_lng" not in indexes() and "ix_reports_section_km" in indexes()
        upgrade(directory=mig_dir)
        assert "ix_reports_lat_lng" in indexes()
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "a3d9c2e41f07"
        engine.dispose()


def test_model_declares_the_index():
    assert any(i.name == "ix_reports_lat_lng" and [c.name for c in i.columns] == ["latitude", "longitude"]
               for i in Report.__table__.indexes)


def test_mariadb_schema_script_in_sync():
    sql = (ROOT / "deploy" / "sql" / "schema_mariadb.sql").read_text(encoding="utf-8")
    assert "CREATE INDEX ix_reports_lat_lng ON reports (latitude, longitude);" in sql
    assert "VALUES ('a3d9c2e41f07')" in sql


# ------------------------------------------------------------------ JavaScript engine (Node built-in test runner)
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_js_engine_node_suite():
    files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
    assert files, "no JavaScript tests found"
    res = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
