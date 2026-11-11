#!/usr/bin/env python3
"""Valideer data/hacks.json en schrijf data/meta.json.

Gebruik: python3 scripts/finalize.py [--vorige pad/naar/oude/hacks.json]
Stopt met exitcode 1 en een duidelijke foutmelding als de data niet klopt.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "hacks.json"
META = ROOT / "data" / "meta.json"

CAT = {"Aanval/datalek", "Crypto", "Kwetsbaarheid"}
STATUS = {"Bevestigd", "Deels bevestigd", "Claim"}
SEV = {"Kritiek": 4, "Hoog": 3, "Middel": 2, "Laag": 1}
REQ = ["id", "datum", "categorie", "titel", "doelwit", "land", "ernst", "ernst_score",
       "samenvatting", "bron", "bron_url"]


def fail(msg):
    print(f"FOUT: {msg}", file=sys.stderr)
    sys.exit(1)


TRACK_FIELDS = {"toegevoegd", "bijgewerkt"}


def main():
    datum = None
    if "--datum" in sys.argv:
        datum = sys.argv[sys.argv.index("--datum") + 1]

    vorige_rows: dict = {}
    if "--vorige" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--vorige") + 1])
        if p.exists():
            for r in json.loads(p.read_text(encoding="utf-8")):
                vorige_rows[r["id"]] = r
    vorige = set(vorige_rows) if vorige_rows else None

    try:
        rows = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        fail(f"data/hacks.json is geen geldige JSON: {e}")
    if not isinstance(rows, list) or not rows:
        fail("data/hacks.json moet een niet-lege array zijn")

    ids = set()
    for i, r in enumerate(rows):
        waar = f"regel {i} ({r.get('id', '?')})"
        for k in REQ:
            if r.get(k) in (None, ""):
                fail(f"{waar}: veld '{k}' ontbreekt")
        if r["id"] in ids:
            fail(f"{waar}: dubbele id")
        ids.add(r["id"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["datum"]):
            fail(f"{waar}: datum moet YYYY-MM-DD zijn")
        if r["categorie"] not in CAT:
            fail(f"{waar}: onbekende categorie '{r['categorie']}'")
        r.setdefault("status", "Bevestigd")
        if r["status"] not in STATUS:
            fail(f"{waar}: onbekende status '{r['status']}'")
        if r["ernst"] not in SEV:
            fail(f"{waar}: onbekende ernst '{r['ernst']}'")
        if r["ernst_score"] != SEV[r["ernst"]]:
            r["ernst_score"] = SEV[r["ernst"]]
        if not str(r["bron_url"]).startswith("https://"):
            fail(f"{waar}: bron_url moet met https:// beginnen")
        for k in ("schade_usd", "records", "cvss"):
            if r.get(k) is not None and not isinstance(r[k], (int, float)):
                fail(f"{waar}: '{k}' moet een getal of null zijn")
        r.setdefault("schade_usd", None)
        r.setdefault("records", None)
        r.setdefault("cve", None)
        r.setdefault("cvss", None)
        if r["categorie"] == "Kwetsbaarheid":
            if not isinstance(r.get("misbruikt"), bool):
                r["misbruikt"] = True
        else:
            r["misbruikt"] = None

    if datum and vorige_rows:
        for r in rows:
            rid = r["id"]
            if rid not in vorige_rows:
                r["toegevoegd"] = datum
                r["bijgewerkt"] = None
            else:
                old = vorige_rows[rid]
                changed = any(r.get(k) != old.get(k) for k in set(r) | set(old) if k not in TRACK_FIELDS)
                if changed:
                    r["toegevoegd"] = old.get("toegevoegd", datum)
                    r["bijgewerkt"] = datum
                else:
                    r["toegevoegd"] = old.get("toegevoegd")
                    r["bijgewerkt"] = old.get("bijgewerkt")

    rows.sort(key=lambda r: (r["datum"], r["ernst_score"]), reverse=True)
    DATA.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    nieuw = None if vorige is None else len(ids - vorige)
    META.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aantal": len(rows),
        "nieuw": nieuw,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OK: {len(rows)} incidenten" + (f", {nieuw} nieuw" if nieuw is not None else ""))


if __name__ == "__main__":
    main()
