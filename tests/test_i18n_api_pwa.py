import json

from app.extensions import db
from app.models import PushSubscription

from .conftest import login


def test_default_language_is_arabic_rtl(client):
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="ar" dir="rtl"' in html
    assert "الطريق الدولي ليبيا" in html and "bootstrap.rtl.min.css" in html


def test_switch_to_english_ltr_and_back(client):
    r = client.get("/lang/en", headers={"Referer": "http://localhost/reports/"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/reports/")  # preserves current page
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="en" dir="ltr"' in html and "International Road Libya" in html
    assert "bootstrap.min.css" in html and "bootstrap.rtl.min.css" not in html
    client.get("/lang/ar")
    assert 'dir="rtl"' in client.get("/").get_data(as_text=True)


def test_language_saved_in_profile(client, users):
    login(client, "0921000001")
    client.get("/lang/en")
    db.session.refresh(users["public"])
    assert users["public"].locale == "en"
    # new session (other device) uses the profile preference
    client.post("/auth/logout")
    client.delete_cookie("lang")
    login(client, "0921000001")
    assert 'lang="en"' in client.get("/").get_data(as_text=True)


def test_all_major_pages_both_languages(client, users):
    pages = ["/", "/reports/", "/reports/new", "/reports/track", "/map", "/alerts", "/privacy", "/about", "/support",
             "/install", "/settings/language", "/auth/login", "/auth/register", "/auth/forgot", "/offline"]
    for lang in ("ar", "en"):
        client.get(f"/lang/{lang}")
        for p in pages:
            r = client.get(p)
            assert r.status_code == 200, (lang, p)
    login(client, "0921000001")
    for lang in ("ar", "en"):
        client.get(f"/lang/{lang}")
        for p in ("/profile", "/profile/edit", "/settings/notifications", "/notifications/"):
            assert client.get(p).status_code == 200, (lang, p)


def test_status_labels_translated(client):
    ar = client.get("/reports/").get_data(as_text=True)
    assert "قيد المراجعة" in ar
    client.get("/lang/en")
    en = client.get("/reports/").get_data(as_text=True)
    assert "Under review" in en


def test_manifest_localized(client):
    m = json.loads(client.get("/manifest.webmanifest?lang=en").get_data(as_text=True))
    assert m["display"] == "standalone" and m["dir"] == "ltr" and m["name"] == "International Road Libya"
    assert any(i["sizes"] == "512x512" for i in m["icons"]) and any(i.get("purpose") == "maskable" for i in m["icons"])
    m = json.loads(client.get("/manifest.webmanifest?lang=ar").get_data(as_text=True))
    assert m["dir"] == "rtl" and m["name"] == "الطريق الدولي ليبيا" and m["shortcuts"]


def test_service_worker_served_with_version(client):
    r = client.get("/sw.js")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "__SW_VERSION__" not in body
    assert r.headers["Service-Worker-Allowed"] == "/"
    assert "/admin" in body  # admin excluded from caching


def test_private_pages_not_cacheable(client, users):
    login(client, "0921000001")
    assert "no-store" in client.get("/profile").headers["Cache-Control"]
    assert "no-store" in client.get("/api/v1/me").headers["Cache-Control"]


def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"


def test_api_meta_and_home(client):
    d = client.get("/api/v1/meta").get_json()
    assert d["ok"] and {s["code"] for s in d["data"]["statuses"]} >= {"new", "resolved"}
    d = client.get("/api/v1/home?km=214").get_json()["data"]
    assert d["km"] == 214 and d["section"] == "قاطع سرت" and d["nearby_count"] >= 1
    d = client.get("/api/v1/home").get_json()["data"]
    assert d["km"] is None and d["nearby_count"] is None  # no fabricated location


def test_api_locate(client):
    d = client.get("/api/v1/locate?lat=31.2050&lng=16.5880").get_json()["data"]
    assert d["on_road"] and abs(d["km"] - 214) < 1
    d = client.get("/api/v1/locate?lat=25.0&lng=10.0").get_json()["data"]
    assert d["on_road"] is False and d["km"] is None
    assert client.get("/api/v1/locate?lat=abc&lng=1").status_code == 422


def test_api_token_auth(client, users):
    r = client.post("/api/v1/auth/token", json={"identifier": "0921000001", "password": "Passw0rd1", "device": "test"})
    assert r.status_code == 201
    tok = r.get_json()["data"]["token"]
    fresh = client.application.test_client()
    assert fresh.get("/api/v1/me").status_code == 401
    me = fresh.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"}).get_json()
    assert me["data"]["name"] == "Citizen"
    fresh.delete("/api/v1/auth/token", headers={"Authorization": f"Bearer {tok}"})
    assert fresh.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    assert client.post("/api/v1/auth/token", json={"identifier": "0921000001", "password": "bad"}).status_code == 401


def test_api_create_report_with_token(client, users):
    tok = client.post("/api/v1/auth/token", json={"identifier": "0921000001", "password": "Passw0rd1"}).get_json()["data"]["token"]
    from app.models import ReportCategory
    cid = db.session.execute(db.select(ReportCategory.id).filter_by(code="crack")).scalar_one()
    c = client.application.test_client()
    r = c.post("/api/v1/reports", data={"category_id": cid, "km_marker": "٢١٠", "severity": "low"},
               headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201 and r.get_json()["data"]["km"] == 210.0  # Arabic-Indic digits accepted


def test_push_subscribe_unsubscribe(client, users):
    login(client, "0921000001")
    sub = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "k" * 40, "auth": "a" * 16}}
    assert client.post("/api/v1/push/subscribe", json={"subscription": sub}).status_code == 201
    row = db.session.execute(db.select(PushSubscription)).scalar_one()
    assert row.user_id == users["public"].id and row.locale == "ar"
    assert client.post("/api/v1/push/subscribe", json={"subscription": {"endpoint": "http://x"}}).status_code == 422
    client.post("/api/v1/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    assert db.session.execute(db.select(PushSubscription)).first() is None


def test_notifications_read(client, users):
    login(client, "0921000001")
    from app.models import Notification
    db.session.add(Notification(user_id=users["public"].id, title_ar="ت", title_en="T"))
    db.session.commit()
    assert client.get("/api/v1/notifications").get_json()["data"]["unread"] == 1
    client.post("/notifications/read-all")
    assert client.get("/api/v1/notifications").get_json()["data"]["unread"] == 0


def test_translation_catalogue_complete():
    from babel.messages.pofile import read_po
    from pathlib import Path
    po = Path(__file__).resolve().parents[1] / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    cat = read_po(po.open("rb"))
    missing = [m.id for m in cat if m.id and not m.string]
    assert not missing, missing[:10]


def test_web_push_delivery_and_cleanup(app, users, monkeypatch):
    """Push payload is localised to the subscriber; 410 Gone removes the subscription."""
    import pywebpush
    from app.services.notify import send_push
    app.config.update(TESTING=False, VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv")
    sent = []

    def fake_webpush(subscription_info, data, **kw):
        sent.append(json.loads(data))

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    sub = PushSubscription(user_id=users["public"].id, endpoint="https://push.example/1",
                           endpoint_hash=PushSubscription.hash_endpoint("https://push.example/1"),
                           p256dh="k", auth="a", locale="en")
    db.session.add(sub)
    db.session.commit()
    texts = {"title_ar": "عنوان", "title_en": "Title", "body_ar": "نص", "body_en": "Body"}
    with app.test_request_context():
        assert send_push(sub, texts, "/x", "weather") is True
    assert sent[0]["title"] == "Title" and sent[0]["dir"] == "ltr"

    class Gone(pywebpush.WebPushException):
        pass

    def gone(*a, **k):
        resp = type("R", (), {"status_code": 410})()
        raise pywebpush.WebPushException("gone", response=resp)

    monkeypatch.setattr(pywebpush, "webpush", gone)
    with app.test_request_context():
        assert send_push(sub, texts, "/x", "weather") is False
    db.session.commit()
    assert db.session.execute(db.select(PushSubscription)).first() is None


def test_vapid_cli(app):
    runner = app.test_cli_runner()
    out = runner.invoke(args=["vapid-keys"]).output
    assert "VAPID_PUBLIC_KEY=" in out and "VAPID_PRIVATE_KEY=" in out
