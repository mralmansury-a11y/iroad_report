#!/usr/bin/env python3
"""Regenerate PWA icons/favicons from the OFFICIAL high-resolution logo exported from Figma.

    python scripts/build_icons.py path/to/irs-logo-1024.png [--bg "#ffffff"]

Writes app/static/icons/icon-*.png, maskable-*.png, favicon-32.png and app/static/favicon.ico,
and copies the logo to app/static/images/brand/irs-logo.png.
"""
import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "app" / "static" / "icons"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logo")
    ap.add_argument("--bg", default="#ffffff")
    a = ap.parse_args()
    logo = Image.open(a.logo).convert("RGBA")
    ICONS.mkdir(parents=True, exist_ok=True)
    for size, pad, prefix in [(s, 0.06, "icon") for s in (72, 96, 128, 144, 152, 180, 192, 384, 512)] + \
                             [(s, 0.14, "maskable") for s in (192, 512)]:
        bg = Image.new("RGBA", (size, size), a.bg)
        inner = int(size * (1 - 2 * pad))
        lg = logo.copy()
        lg.thumbnail((inner, inner), Image.LANCZOS)
        bg.alpha_composite(lg, ((size - lg.width) // 2, (size - lg.height) // 2))
        bg.convert("RGB").save(ICONS / f"{prefix}-{size}.png", optimize=True)
    small = logo.copy()
    small.thumbnail((48, 48), Image.LANCZOS)
    small.save(ROOT / "app" / "static" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    s32 = logo.copy()
    s32.thumbnail((32, 32), Image.LANCZOS)
    s32.save(ICONS / "favicon-32.png")
    brand = logo.copy()
    brand.thumbnail((256, 256), Image.LANCZOS)
    brand.save(ROOT / "app" / "static" / "images" / "brand" / "irs-logo.png", optimize=True)
    print("icons regenerated")


if __name__ == "__main__":
    main()
