#!/usr/bin/env python3
"""Stuur een dagelijkse digest van nieuwe incidenten naar een Telegram-groep.

Gebruik: python3 scripts/telegram_digest.py --vorige /tmp/vorige.json [--dry-run]
Test:    python3 scripts/telegram_digest.py --sinds 2026-11-09 [--dry-run]
Omgevingsvariabelen: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (en optioneel SITE_URL).
Alleen standaardbibliotheek; geen extra packages nodig.
"""
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "hacks.json"
SITE = os.environ.get("SITE_URL", "https://l3and3r.github.io/hack-monitor/")
MAX_LEN = 4000  # Telegram-limiet is 4096 tekens per bericht
MAX_KRITIEK = 10  # per categorie maximaal zoveel kritieke regels
MAX_HOOG = 5  # en maximaal zoveel "hoog"
ICON = {"Kritiek": "🔴", "Hoog": "🟠", "Middel": "⚪", "Laag": "▫️"}


def usd(v):
    if v is None:
        return ""
    if v >= 1e9:
        return f"${v / 1e9:.1f} mld".replace(".", ",")
    if v >= 1e6:
        return f"${v / 1e6:.1f} mln".replace(".", ",")
    if v >= 1e3:
        return f"${round(v / 1e3)}K"
    return f"${v}"


def num(v):
    if v is None:
        return ""
    if v >= 1e6:
        return f"{v / 1e6:.1f} mln".replace(".", ",")
    return f"{int(v):,}".replace(",", ".")


def regel(r):
    e = html.escape
    extra = []
    if r.get("schade_usd"):
        extra.append(usd(r["schade_usd"]))
    if r.get("records"):
        extra.append(num(r["records"]) + " records")
    if r.get("cve"):
        extra.append(r["cve"] + (f", CVSS {r['cvss']}" if r.get("cvss") else ""))
    status = r.get("status", "Bevestigd")
    if status == "Claim":
        extra.append("claim, onbevestigd")
    elif status == "Deels bevestigd":
        extra.append("omvang geclaimd")
    if r.get("categorie") == "Kwetsbaarheid":
        extra.append("actief misbruikt" if r.get("misbruikt") else "nog niet misbruikt")
    tail = f" <i>({e(' · '.join(extra))})</i>" if extra else ""
    return f'{ICON.get(r["ernst"], "•")} <a href="{e(r["bron_url"], quote=True)}">{e(r["titel"])}</a>{tail}'


def bouw(nieuw, totaal):
    if not nieuw:
        return [f"🛡 <b>Hack Monitor</b>\nGeen nieuwe incidenten sinds gisteren.\n<a href=\"{SITE}\">Open de monitor</a>"]
    nieuw.sort(key=lambda r: r["datum"], reverse=True)
    nieuw.sort(key=lambda r: r["ernst_score"], reverse=True)
    tel = {s: sum(r["ernst"] == s for r in nieuw) for s in ICON}
    claims = sum(r.get("status") == "Claim" for r in nieuw)
    kop = (f"🛡 <b>Hack Monitor</b>: {len(nieuw)} nieuwe incidenten\n"
           f"🔴 {tel['Kritiek']} kritiek · 🟠 {tel['Hoog']} hoog · ⚪ {tel['Middel'] + tel['Laag']} overig"
           + (f" · {claims} claims" if claims else "") + "\n")
    secties = []
    for cat, naam in [("Aanval/datalek", "Aanvallen en datalekken"), ("Crypto", "Crypto"), ("Kwetsbaarheid", "Kwetsbaarheden")]:
        rows = [r for r in nieuw if r["categorie"] == cat]
        toon = [r for r in rows if r["ernst"] == "Kritiek"][:MAX_KRITIEK] + [r for r in rows if r["ernst"] == "Hoog"][:MAX_HOOG]
        rest = len(rows) - len(toon)
        if not rows:
            continue
        s = f"\n<b>{naam}</b>" + "".join("\n" + regel(r) for r in toon)
        if rest:
            s += f"\n<i>+ {rest} {'ander incident' if rest == 1 else 'andere incidenten'} in de monitor</i>"
        secties.append(s)
    voet = f'\n\n<a href="{SITE}">Alle {totaal} incidenten in de monitor</a>'

    berichten, huidig = [], kop
    for sec in secties:
        for line in sec.split("\n"):
            if len(huidig) + len(line) + 1 > MAX_LEN:
                berichten.append(huidig)
                huidig = ""
            huidig += line + "\n"
    if len(huidig) + len(voet) > 4090:
        berichten.append(huidig)
        huidig = ""
    berichten.append(huidig + voet)
    return berichten


def stuur(tekst, token, chat):
    data = urllib.parse.urlencode({"chat_id": chat, "text": tekst, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if not out.get("ok"):
        raise SystemExit(f"Telegram gaf een fout: {out}")


def main():
    vorige = set()
    if "--vorige" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--vorige") + 1])
        if p.exists():
            vorige = {r["id"] for r in json.loads(p.read_text(encoding="utf-8"))}
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    if "--sinds" in sys.argv:  # test: doe alsof alles vanaf deze datum nieuw is
        sinds = sys.argv[sys.argv.index("--sinds") + 1]
        vorige = {r["id"] for r in rows if r["datum"] < sinds}
    nieuw = [r for r in rows if r["id"] not in vorige]
    berichten = bouw(nieuw, len(rows))
    if "--dry-run" in sys.argv:
        for b in berichten:
            print(b, f"\n--- ({len(b)} tekens) ---")
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN of TELEGRAM_CHAT_ID ontbreekt; digest niet verstuurd.")
        return
    for b in berichten:
        stuur(b, token, chat)
    print(f"{len(berichten)} bericht(en) verstuurd met {len(nieuw)} nieuwe incidenten.")


if __name__ == "__main__":
    main()
