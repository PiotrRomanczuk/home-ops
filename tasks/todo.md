# Plan: dzienna rutyna SEO na elitedesk (gitarawarszawa.pl)

_2026-10-13_

Cel: codziennie zbierać GSC/GA4/Places → analizować → rekomendować, a co tydzień
proponować konkretne zmiany w gitara-lekcje jako PR (nigdy auto-merge).

## Warstwa 1 — zbieranie (PR #45, gotowe, nie scalone)
- [ ] scalić `feat/seo-collector` (zgoda Piotra), wdrożyć migrację 017 + unit 06:00

## Warstwa 2 — analiza dzienna (ta gałąź)
- [x] `postgres/migrations/018_seo_analysis.sql` — `seo_analysis_daily`
- [x] `ops/elitedesk/seo-districts.json` — regexy dzielnic/stacji (prawy brzeg + M2 + M1 centrum)
- [x] `ops/elitedesk/seo_metrics.py` — czyste obliczenia 7d vs 7d, nowe frazy, dzielnice (testy)
- [x] `ops/elitedesk/seo_render.py` — karta tekstowa do digest.d (bez LLM)
- [x] `ops/elitedesk/seo_llm.py` — `claude -p` z promptem, timeout, graceful skip
- [x] `ops/elitedesk/seo-analyse.py` — main: psql → metryki → karta → LLM → upsert
- [x] `ops/elitedesk/seo-analyse.prompt.md` — prompt analityka (PL)
- [x] `seo-analyse.service` + `.timer` 06:30
- [x] testy `ops/elitedesk/tests/test_seo_analyse.py`

## Warstwa 3 — tygodniowa rozbudowa promocji (PR do gitara-lekcje)
- [x] `ops/elitedesk/seo-improve.sh` — klon, gałąź `seo/auto-<data>`, `claude -p` z narzędziami, bramki, `gh pr create`
- [x] `ops/elitedesk/seo-improve.prompt.md`
- [x] `seo-improve.service` + `.timer` (poniedziałek 06:45)

## Dokumentacja / wdrożenie
- [x] README `ops/elitedesk` sekcja SEO, `seo-collect.env.example` nowe klucze
- [x] `docs/manual-tests/2026-10-13-seo-analyse.html`
- [ ] bramki: py_compile + unittest; commit; PR
- [ ] wdrożenie na uwh: pull, migracje, env, symlinki, timery, klon gitara-lekcje, run ręczny
- [ ] kroki Piotra: konto serwisowe Google (klucz JSON), `claude login` na uwh
- [ ] vault: home-ops.md + gitara-lekcje.md

## Review
(uzupełnić po zakończeniu)
