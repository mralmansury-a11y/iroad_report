#!/usr/bin/env python3
"""Extract → update → fill → compile the ar/en gettext catalogues.

Usage (from the project root):
    python scripts/build_translations.py            # full rebuild, fails if any Arabic string is missing
    python scripts/build_translations.py --check    # only report missing translations

English is the source language (msgid). The English catalogue mirrors msgids so that
both languages are first-class catalogues; Arabic strings come from the existing .po
file first, then from scripts/i18n_ar.py.
"""
import subprocess
import sys
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n_ar import AR  # noqa: E402

TR = ROOT / "translations"
POT = TR / "messages.pot"


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(check_only=False):
    run("pybabel", "extract", "-F", "babel.cfg", "-k", "_l", "-k", "lazy_gettext", "--no-location",
        "--sort-output", "-o", str(POT), ".")
    template = read_po(POT.open("rb"))
    missing = []
    for loc in ("ar", "en"):
        po_path = TR / loc / "LC_MESSAGES" / "messages.po"
        po_path.parent.mkdir(parents=True, exist_ok=True)
        if po_path.exists():
            cat = read_po(po_path.open("rb"), locale=loc)
            cat.update(template, no_fuzzy_matching=True)
        else:
            cat = read_po(POT.open("rb"), locale=loc)
        cat.locale = loc
        cat.fuzzy = False
        cat.project, cat.version = "International Road Services - Libya", "1.0"
        cat.copyright_holder = "National Development Agency"
        cat.language_team = "IRS Libya"
        cat.last_translator = "IRS Libya"
        for m in cat:
            if not m.id:
                continue
            if loc == "en":
                m.string = m.id
            elif not m.string:
                if m.id in AR:
                    m.string = AR[m.id]
                else:
                    missing.append(m.id)
            m.flags.discard("fuzzy")
        if not check_only:
            with po_path.open("wb") as fh:
                write_po(fh, cat, width=0, omit_header=False)
            with (po_path.with_suffix(".mo")).open("wb") as fh:
                write_mo(fh, cat)
    if missing:
        print("Missing Arabic translations:")
        for m in missing:
            print("  -", m)
        sys.exit(1)
    print("Catalogues OK (ar, en).")


if __name__ == "__main__":
    main("--check" in sys.argv)
