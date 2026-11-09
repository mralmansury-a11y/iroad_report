"""Utility helpers."""
from urllib.parse import urlparse

from flask import request


def safe_next(target: str | None, default: str = "/") -> str:
    """Only allow same-site relative redirects (prevents open-redirects)."""
    if not target:
        return default
    p = urlparse(target)
    if p.scheme or p.netloc or not target.startswith("/") or target.startswith("//"):
        return default
    return target


def safe_referrer(default: str = "/") -> str:
    ref = request.referrer
    if not ref:
        return default
    p = urlparse(ref)
    if p.netloc and p.netloc != request.host:
        return default
    path = p.path or "/"
    # drop explicit ?lang= so the new language preference wins
    from urllib.parse import parse_qsl, urlencode
    qs = [(k, v) for k, v in parse_qsl(p.query) if k != "lang"]
    return path + (("?" + urlencode(qs)) if qs else "")
