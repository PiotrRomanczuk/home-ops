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
- [x] bramki: py_compile + unittest; commit; PR
- [x] wdrożenie na uwh: pull, migracje, env, symlinki, timery, klon gitara-lekcje, run ręczny
- [ ] kroki Piotra: konto serwisowe Google (klucz JSON), `claude login` na uwh
- [x] vault: home-ops.md + gitara-lekcje.md

## Review (2026-10-13)
- Zrobione: warstwy 2 i 3 w PR #46 (na #45). 15/15 testów, CI py_compile + bash -n rozszerzone.
- Wdrożone na uwh: migracje 017+018, ingest przebudowany (health 200), 3 timery aktywne; `seo-analyse` przeszedł na zielono bez danych (karta „brak danych”), `seo-improve --dry-run` buduje prompt.
- Otwarte: klucz konta serwisowego Google (bez niego kolektor pomija GSC/GA4), token subskrypcji Max dla headless Claude (API key bez kredytów usunięty), scalenie #45 i #46, stash `elitedesk-local-2026-10-13` na uwh → PR.
- Lekcja: `ANTHROPIC_API_KEY` w env wyłącza logowanie subskrypcją — na serwerze z planem Max używać `claude setup-token`.

## Etap 2 (2026-10-13, gałąź feat/seo-plan) — plan jako stan
- [x] migracja 019: seo_plan, seo_page_snapshot, seo_findings
- [x] seo_plan.py — werdykty 14/28 dni vs baseline + strony kontrolne, MIN 10 wyśw.
- [x] seo_drift.py — crawl sitemapy, reguły (title/desc/canonical/noindex/JSON-LD/CTA/thin/title-changed)
- [x] seo_opps.py — adaptacyjne progi striking distance + niski CTR
- [x] seo_plan_db.py — I/O planu, walidacja plan-updates, in_pr→shipped przez gh
- [x] seo-analyse.py — crawl + plan + okazje + blok plan-updates
- [x] seo-improve.sh — brief z planu, sędzia faktów (seo-judge.prompt.md), in_pr
- [x] testy 27/27, CI, README, raport docs/manual-tests/2026-10-13-seo-plan.html
- [ ] wdrożenie uwh: migracja 019, pull, przebieg próbny z realnym crawlem
