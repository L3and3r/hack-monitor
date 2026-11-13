#!/usr/bin/env python3
"""Hack Monitor – hulpscript voor de dagelijkse workflow.

Subcommando's:
  plan    Bepaalt of vandaag nog onderzocht en/of een Telegram-bericht gestuurd moet worden.
  index   Schrijft een compacte lijst van bestaande incidenten (voor ontdubbelen door Claude).
  merge   Voegt de door Claude gevonden regels (spoor*.json) deterministisch samen met data/hacks.json.
  digest  Maakt het Telegram-bericht en verstuurt het (of print het met --dry-run).
  mark    Noteert in meta.json dat het Telegram-bericht van vandaag is verstuurd.
  verify  Controleert of de live site de data van vandaag serveert.

Alleen standaardbibliotheek; Python 3.9+.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

CATEGORIEEN = {"Aanval/datalek", "Crypto", "Kwetsbaarheid"}
STATUSSEN = {"Bevestigd", "Deels bevestigd", "Claim"}
ERNST_SCORE = {"Kritiek": 4, "Hoog": 3, "Middel": 2, "Laag": 1}
VELDEN = ["id", "datum", "categorie", "status", "titel", "doelwit", "land", "ernst",
          "ernst_score", "schade_usd", "records", "cve", "cvss", "samenvatting", "bron",
          "bron_url", "misbruikt", "toegevoegd", "bijgewerkt"]
INHOUD_VELDEN = [v for v in VELDEN if v not in ("id", "toegevoegd", "bijgewerkt")]
BEWAAR_DAGEN = 60
DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CVE_RE = re.compile(r"^(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3})$", re.I)
BITCOIN_RE = re.compile(
    r"\b(bitcoin|lightning|lnd|lnbits|btcpay|core lightning|eclair|ldk|bdk|electrum|"
    r"sparrow|krux|seedsigner|coldcard|bitbox|trezor|specter|libsecp256k1|btcd|knots)\b", re.I)


def vandaag() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def nu_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def lees_json(pad, standaard=None):
    if not os.path.exists(pad):
        return standaard
    with open(pad, encoding="utf-8") as f:
        return json.load(f)


def schrijf_json(pad, data):
    tmp = pad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, pad)


def log(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- validatie
def normaliseer(r: dict) -> tuple[dict | None, str | None]:
    """Geeft (genormaliseerde regel, None) of (None, foutmelding)."""
    if not isinstance(r, dict):
        return None, "geen object"
    x = {k: r.get(k) for k in VELDEN}
    for k in ("id", "datum", "categorie", "status", "titel", "doelwit", "ernst", "samenvatting", "bron", "bron_url"):
        if not isinstance(x[k], str) or not x[k].strip():
            return None, f"veld {k} ontbreekt of is leeg"
        x[k] = x[k].strip()
    if not DATUM_RE.match(x["datum"]):
        return None, "datum geen YYYY-MM-DD"
    try:
        d = date.fromisoformat(x["datum"])
    except ValueError:
        return None, "ongeldige datum"
    if d > datetime.now(timezone.utc).date() + timedelta(days=1):
        return None, "datum in de toekomst"
    if x["categorie"] not in CATEGORIEEN:
        return None, f"onbekende categorie {x['categorie']!r}"
    if x["status"] not in STATUSSEN:
        return None, f"onbekende status {x['status']!r}"
    if x["ernst"] not in ERNST_SCORE:
        return None, f"onbekende ernst {x['ernst']!r}"
    x["ernst_score"] = ERNST_SCORE[x["ernst"]]
    if not x["bron_url"].startswith("https://"):
        return None, "bron_url begint niet met https://"
    if not isinstance(x.get("land"), str) or not x["land"].strip():
        x["land"] = "Onbekend"
    for k in ("schade_usd", "records", "cvss"):
        v = x[k]
        if v is None or v == "":
            x[k] = None
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            try:
                x[k] = float(str(v).replace(",", "."))
            except ValueError:
                x[k] = None
        if x[k] is not None and x[k] < 0:
            x[k] = None
    if x["records"] is not None:
        x["records"] = int(x["records"])
    if x["schade_usd"] is not None and float(x["schade_usd"]).is_integer():
        x["schade_usd"] = int(x["schade_usd"])
    if x["cvss"] is not None and not (0 <= x["cvss"] <= 10):
        x["cvss"] = None
    if x["cve"] in ("", None):
        x["cve"] = None
    elif not isinstance(x["cve"], str) or not CVE_RE.match(x["cve"].strip()):
        x["cve"] = None
    else:
        c = x["cve"].strip()
        x["cve"] = c.upper() if c.upper().startswith("CVE-") else "GHSA" + c[4:].lower()
    if x["categorie"] == "Kwetsbaarheid":
        x["misbruikt"] = bool(x["misbruikt"]) if isinstance(x["misbruikt"], bool) else False
    else:
        x["misbruikt"] = None
    x["id"] = re.sub(r"[^a-z0-9-]", "-", x["id"].lower()).strip("-")
    if not x["id"].startswith(x["datum"]):
        x["id"] = f"{x['datum']}-{x['id']}"
    return x, None


def sleutel_doelwit(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_duplicaat(a: dict, b: dict) -> bool:
    """Zelfde incident? Conservatief: liever een dubbele regel dan een gemiste hack."""
    if a.get("cve") and b.get("cve"):
        return a["cve"] == b["cve"]  # verschillende CVE's = verschillende incidenten
    da, db = date.fromisoformat(a["datum"]), date.fromisoformat(b["datum"])
    return (sleutel_doelwit(a["doelwit"]) == sleutel_doelwit(b["doelwit"])
            and a["categorie"] == b["categorie"]
            and abs((da - db).days) <= 3)


def sorteer(rijen):
    rijen.sort(key=lambda x: (x["datum"], x["ernst_score"], x["id"]), reverse=True)
    return rijen


# ---------------------------------------------------------------- subcommando's
def cmd_plan(a):
    meta = lees_json(a.meta, {}) or {}
    t = vandaag()
    onderzoek = a.force == "true" or meta.get("updated_on") != t
    telegram = a.skip_telegram != "true" and (onderzoek or meta.get("telegram_sent_on") != t)
    print(f"research={'true' if onderzoek else 'false'}")
    print(f"telegram={'true' if telegram else 'false'}")
    log(f"plan: vandaag={t} meta.updated_on={meta.get('updated_on')} "
        f"meta.telegram_sent_on={meta.get('telegram_sent_on')} -> research={onderzoek} telegram={telegram}")


def cmd_index(a):
    data = lees_json(a.data, []) or []
    for x in data:
        print(f"{x['id']} | {x['datum']} | {x.get('doelwit')} | {x.get('cve')} | {x.get('titel')}")


def cmd_merge(a):
    t = vandaag()
    bestaand = lees_json(a.data, []) or []
    meta = lees_json(a.meta, {}) or {}
    grens = (datetime.now(timezone.utc).date() - timedelta(days=BEWAAR_DAGEN)).isoformat()

    bestanden = sorted(glob.glob(os.path.join(a.incoming, "**", "*.json"), recursive=True)) if a.incoming else []
    binnen, fouten = [], 0
    for pad in bestanden:
        if os.path.basename(pad) in ("claude-run.json",):
            continue
        try:
            inhoud = lees_json(pad, [])
        except json.JSONDecodeError as e:
            log(f"WAARSCHUWING: {pad} is geen geldige JSON ({e}); overgeslagen")
            fouten += 1
            continue
        if isinstance(inhoud, dict):
            inhoud = inhoud.get("items") or inhoud.get("incidenten") or []
        if not isinstance(inhoud, list):
            log(f"WAARSCHUWING: {pad} bevat geen array; overgeslagen")
            continue
        for r in inhoud:
            n, fout = normaliseer(r)
            if fout:
                fouten += 1
                log(f"  afgekeurd ({os.path.basename(pad)}): {fout}: {str(r)[:120]}")
            else:
                binnen.append(n)
    log(f"merge: {len(bestanden)} bestand(en), {len(binnen)} geldige regels, {fouten} afgekeurd")
    if a.require_incoming and not bestanden:
        log("FOUT: geen invoerbestanden gevonden terwijl onderzoek wel gedraaid heeft")
        sys.exit(2)

    per_id = {x["id"]: x for x in bestaand}
    nieuw, bijgewerkt = 0, 0
    for r in binnen:
        doel = per_id.get(r["id"])
        if doel is None:  # misschien hetzelfde incident onder een andere id
            doel = next((x for x in per_id.values() if is_duplicaat(r, x)), None)
        if doel is not None:
            gewijzigd = {k: r[k] for k in INHOUD_VELDEN
                         if r[k] is not None and r[k] != doel.get(k)}
            # alleen zinvolle updates: nieuwe cijfers, status, misbruik, cve
            relevant = {k: v for k, v in gewijzigd.items()
                        if k in ("status", "ernst", "ernst_score", "schade_usd", "records", "cve", "cvss",
                                 "misbruikt", "samenvatting", "titel", "bron", "bron_url")}
            if r["id"] != doel["id"] and not ({"status", "schade_usd", "records", "misbruikt", "cve"} & relevant.keys()):
                continue  # duplicaat zonder nieuwe feiten
            if relevant:
                doel.update(relevant)
                doel["ernst_score"] = ERNST_SCORE[doel["ernst"]]
                if doel.get("bijgewerkt") != t and doel.get("toegevoegd") != t:
                    bijgewerkt += 1
                if doel.get("toegevoegd") != t:
                    doel["bijgewerkt"] = t
            continue
        r["toegevoegd"] = t
        r["bijgewerkt"] = None
        per_id[r["id"]] = r
        nieuw += 1

    resultaat = [x for x in per_id.values() if x["datum"] >= grens]
    # vangnet: geen bestaande regel binnen de bewaartermijn mag verdwijnen
    oud_ids = {x["id"] for x in bestaand if x["datum"] >= grens}
    kwijt = oud_ids - {x["id"] for x in resultaat}
    if kwijt:
        log(f"FOUT: {len(kwijt)} bestaande regels zouden verdwijnen: {sorted(kwijt)[:5]}")
        sys.exit(3)
    if len({x['id'] for x in resultaat}) != len(resultaat):
        log("FOUT: dubbele id's")
        sys.exit(3)
    for x in resultaat:
        x2, fout = normaliseer(x)
        if fout:
            log(f"FOUT: regel {x.get('id')} ongeldig na samenvoegen: {fout}")
            sys.exit(3)
    resultaat = sorteer([{k: x.get(k) for k in VELDEN} for x in resultaat])

    vandaag_nieuw = sum(1 for x in resultaat if x.get("toegevoegd") == t)
    vandaag_bij = sum(1 for x in resultaat if x.get("bijgewerkt") == t)
    meta.update({
        "updated_at": nu_iso(),
        "updated_on": t,
        "updated_by": "GitHub Actions + Claude Code (webonderzoek)",
        "total": len(resultaat),
        "new_today": vandaag_nieuw,
        "updated_today": vandaag_bij,
        "rejected_today": fouten,
    })
    schrijf_json(a.data, resultaat)
    schrijf_json(a.meta, meta)
    log(f"merge klaar: {nieuw} nieuw deze run, {bijgewerkt} bijgewerkt; vandaag totaal nieuw={vandaag_nieuw} "
        f"bijgewerkt={vandaag_bij}; {len(resultaat)} regels in totaal")


def maak_bericht(data, meta, site_url, t) -> str:
    nieuw = [x for x in data if x.get("toegevoegd") == t]
    bij = [x for x in data if x.get("bijgewerkt") == t and x.get("toegevoegd") != t]
    datum_nl = date.fromisoformat(t).strftime("%d-%m-%Y")
    e = html.escape
    if not nieuw and not bij:
        return (f"<b>Hack Monitor {datum_nl}</b>\nGeen nieuwe incidenten vandaag.\n"
                f'<a href="{e(site_url)}">Open de Hack Monitor</a>')
    kritiek = [x for x in nieuw if x["ernst"] == "Kritiek"]
    claims = [x for x in nieuw if x["status"] == "Claim"]
    regels = [f"<b>Hack Monitor {datum_nl}</b>",
              f"{len(nieuw)} nieuw ({len(kritiek)} kritiek, {len(claims)} claims), {len(bij)} bijgewerkt", ""]

    def regel(x):
        pre = "Claim: " if x["status"] == "Claim" and not x["titel"].lower().startswith("claim") else ""
        icoon = {"Kritiek": "🔴", "Hoog": "🟠", "Middel": "🟡", "Laag": "⚪"}[x["ernst"]]
        return f'{icoon} <a href="{e(x["bron_url"], quote=True)}">{e(pre + x["titel"])}</a>'

    top = sorted(nieuw, key=lambda x: (x["ernst_score"], x["status"] != "Claim", x["datum"]), reverse=True)
    btc = [x for x in top if BITCOIN_RE.search(x["titel"] + " " + x["doelwit"])]
    top_zonder_btc = [x for x in top if x not in btc][:5]
    if top_zonder_btc:
        regels.append("<b>Belangrijkste</b>")
        regels += [regel(x) for x in top_zonder_btc]
    if btc:
        regels += ["", "<b>Bitcoin/Lightning</b>"]
        regels += [regel(x) for x in btc[:5]]
    regels += ["", f'<a href="{e(site_url)}">Alle incidenten op de Hack Monitor</a>']
    tekst = "\n".join(regels)
    while len(tekst) > 4000 and len(regels) > 5:  # Telegram-limiet 4096
        regels.pop(-3)
        tekst = "\n".join(regels)
    return tekst


def telegram(token, chat_id, tekst):
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": tekst, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    for poging in range(1, 4):
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30) as r:
                antwoord = json.load(r)
        except urllib.error.HTTPError as err:
            antwoord = json.loads(err.read() or b"{}")
            if 400 <= err.code < 500 and err.code != 429:
                raise SystemExit(f"Telegram weigert ({err.code}): {antwoord.get('description')}")
        except Exception as err:  # netwerkfout
            antwoord = {"ok": False, "description": str(err)}
        if antwoord.get("ok"):
            log("Telegram: verzonden (ok=true)")
            return
        log(f"Telegram poging {poging} mislukt: {antwoord.get('description')}")
        time.sleep(10 * poging)
    raise SystemExit("Telegram: verzenden mislukt na 3 pogingen")


def cmd_digest(a):
    t = a.date or vandaag()
    data = lees_json(a.data, []) or []
    meta = lees_json(a.meta, {}) or {}
    tekst = maak_bericht(data, meta, a.site_url, t)
    if a.dry_run:
        print(tekst)
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise SystemExit("TELEGRAM_BOT_TOKEN of TELEGRAM_CHAT_ID ontbreekt")
    telegram(token, chat, tekst)


def cmd_mark(a):
    meta = lees_json(a.meta, {}) or {}
    meta["telegram_sent_on"] = vandaag()
    meta["telegram_sent_at"] = nu_iso()
    schrijf_json(a.meta, meta)


def cmd_verify(a):
    t = vandaag()
    for poging in range(1, a.tries + 1):
        try:
            url = f"{a.url}?v={int(time.time())}"
            req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=30) as r:
                meta = json.load(r)
            if meta.get("updated_on") == t:
                log(f"verify: live site serveert data van {t} ({meta.get('total')} regels)")
                return
            log(f"verify poging {poging}: live updated_on={meta.get('updated_on')}, verwacht {t}")
        except Exception as err:
            log(f"verify poging {poging}: {err}")
        time.sleep(a.wait)
    raise SystemExit("verify: live site toont niet de data van vandaag")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan"); s.add_argument("--meta", default="data/meta.json")
    s.add_argument("--force", default="false"); s.add_argument("--skip-telegram", default="false")
    s = sub.add_parser("index"); s.add_argument("--data", default="data/hacks.json")
    s = sub.add_parser("merge"); s.add_argument("--data", default="data/hacks.json")
    s.add_argument("--meta", default="data/meta.json"); s.add_argument("--incoming", default="")
    s.add_argument("--require-incoming", action="store_true")
    s = sub.add_parser("digest"); s.add_argument("--data", default="data/hacks.json")
    s.add_argument("--meta", default="data/meta.json"); s.add_argument("--site-url", required=True)
    s.add_argument("--date"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("mark"); s.add_argument("--meta", default="data/meta.json")
    s = sub.add_parser("verify"); s.add_argument("--url", required=True)
    s.add_argument("--tries", type=int, default=12); s.add_argument("--wait", type=int, default=20)
    a = p.parse_args()
    {"plan": cmd_plan, "index": cmd_index, "merge": cmd_merge, "digest": cmd_digest,
     "mark": cmd_mark, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
