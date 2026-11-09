# Hack Monitor

Dagelijks overzicht van hacks, datalekken, crypto-hacks en (misbruikte) kwetsbaarheden, met ernst, schade en records per dag.

**Site:** https://l3and3r.github.io/hack-monitor/

## Hoe het werkt

- `index.html` + `app.js` + `style.css` vormen een statische site die `data/hacks.json` leest.
- De workflow `.github/workflows/update.yml` draait alleen elke ochtend (geen handmatige verversing, zodat het verbruik van je abonnement vastligt). Claude Code zoekt dan volgens `CLAUDE.md` naar nieuwe incidenten, `scripts/finalize.py` valideert de data, de wijziging wordt gecommit en de site opnieuw gepubliceerd.
- De run gebruikt je Claude-abonnement via het secret `CLAUDE_CODE_OAUTH_TOKEN` (geen API-kosten).

## Eenmalige setup

1. **Token:** draai lokaal `claude setup-token` en zet de uitkomst als repo-secret `CLAUDE_CODE_OAUTH_TOKEN` (Settings → Secrets and variables → Actions).
2. **Pages:** Settings → Pages → Source: **GitHub Actions**.

## Ernstschaal

Zie `CLAUDE.md` of onderaan de site.
