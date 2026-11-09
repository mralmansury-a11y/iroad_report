"""In-app notifications and Web Push delivery.

System notifications are rendered in BOTH Arabic and English at creation time
(using the gettext catalogues) so that each user sees them in their current
interface language, and push messages use the subscriber's language.
"""
import json
import logging
from typing import Callable

from flask import current_app
from flask_babel import force_locale

from ..extensions import db
from ..models import Notification, NotificationPreference, PushSubscription, User, utcnow

log = logging.getLogger(__name__)


def get_prefs(user: User) -> NotificationPreference:
    pref = user.notification_pref
    if pref is None:
        pref = NotificationPreference(user=user, report_updates=True, weather_alerts=True, project_updates=True,
                                      points_rewards=True, sound=False, push_enabled=True)
        db.session.add(pref)
        db.session.flush()
    return pref


def _render_both(fn: Callable[[], tuple[str, str]]) -> dict:
    out = {}
    for loc in ("ar", "en"):
        with force_locale(loc):
            title, body = fn()
            out[f"title_{loc}"] = str(title)[:200]
            out[f"body_{loc}"] = str(body)[:1000] if body else None
    return out


def notify(user: User, kind: str, render: Callable[[], tuple[str, str]], url: str | None = None,
           report=None, announcement=None, push: bool = True) -> Notification | None:
    """Create a notification for `user`. `render` is called once per locale and must return (title, body)."""
    if user is None or not user.is_active:
        return None
    user = getattr(user, "_get_current_object", lambda: user)()  # unwrap LocalProxy (current_user)
    pref = get_prefs(user)
    if not pref.allows(kind):
        return None
    texts = _render_both(render)
    n = Notification(user_id=user.id, kind=kind, url=url,
                     report_id=report.id if report is not None else None,
                     announcement_id=announcement.id if announcement is not None else None, **texts)
    db.session.add(n)
    if push and pref.push_enabled:
        subs = db.session.execute(db.select(PushSubscription).filter_by(user_id=user.id)).scalars().all()
        for s in subs:
            send_push(s, texts, url, kind)
    return n


def broadcast_push(texts: dict, url: str | None, kind: str, exclude_user_ids: set[int] | None = None) -> int:
    """Push an announcement to every subscription (including anonymous visitors)."""
    exclude_user_ids = exclude_user_ids or set()
    count = 0
    for s in db.session.execute(db.select(PushSubscription)).scalars():
        if s.user_id and s.user_id in exclude_user_ids:
            continue
        if send_push(s, texts, url, kind):
            count += 1
    return count


def send_push(sub: PushSubscription, texts: dict, url: str | None, kind: str) -> bool:
    cfg = current_app.config
    if not (cfg.get("VAPID_PRIVATE_KEY") and cfg.get("VAPID_PUBLIC_KEY")) or cfg.get("TESTING"):
        return False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover
        return False
    loc = sub.locale if sub.locale in ("ar", "en") else "ar"
    payload = json.dumps({
        "title": texts.get(f"title_{loc}") or texts.get("title_ar"),
        "body": texts.get(f"body_{loc}") or "",
        "url": url or "/",
        "kind": kind,
        "lang": loc,
        "dir": "rtl" if loc == "ar" else "ltr",
    }, ensure_ascii=False)
    try:
        webpush(
            subscription_info=sub.as_webpush_info(),
            data=payload,
            vapid_private_key=cfg["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": cfg["VAPID_CLAIM_EMAIL"]},
            ttl=60 * 60 * 12,
            timeout=10,
        )
        sub.last_success_at = utcnow()
        sub.failure_count = 0
        return True
    except WebPushException as exc:  # expired / unsubscribed → cleanup
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            db.session.delete(sub)
        else:
            sub.failure_count = (sub.failure_count or 0) + 1
            if sub.failure_count >= 5:
                db.session.delete(sub)
        log.warning("web push failed (%s): %s", status, exc)
    except Exception as exc:  # network etc.
        sub.failure_count = (sub.failure_count or 0) + 1
        log.warning("web push error: %s", exc)
    return False
