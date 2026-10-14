# Decisions inbox + digest rewrite

_2026-10-13_ — branch `feat/decisions-inbox` (worktree `.claude/worktrees/decisions`, from `origin/main`)

Goal: the morning email becomes a report from the routines (what they did, what needs Piotr), not a server dashboard. Routines report through one card contract; anything irreversible asks through a decision with signed yes/no links.

## Phase 1 (this branch)

- [x] Migration `020_digest_cards.sql` — `digest_cards` (routine, ran_at, status, headline, items, metric). Latest row per routine = today's card; history = weekly trend.
- [x] Migration `021_decisions.sql` — `decisions` (routine, slug, question, options, context_url, parent_id, expires_at, answer, reason). Parent id gives trees for free.
- [x] `decision-links.ts` — HMAC-signed `/d/:id/:option/:exp/:sig` links + unit test (no DB).
- [x] Routes: `POST/GET /api/cards`, `POST/GET /api/decisions`, `POST /api/decisions/:id/answer`, `GET|POST /d/...` (GET = confirmation page, POST = record; mail prefetch-safe).
- [x] `GET /api/digest` — one JSON model: verdict, problems (grouped by source+normalised message, with since), hosts, sites (rpi probes), focus/next, cards, open decisions with links, narrative.
- [x] Console: Decisions tab (`decisions*.js/css`, key 9, badge = open count).
- [x] `render-digest.py` (stdlib, pure function JSON→HTML, Apple-style light layout) + `daily-digest.sh` slimmed to fetch → render → send. Legacy `digest.d/*.txt` kept only when < 26 h old.
- [x] `agents/routine_report.py` (Reporter class + CLI: card / ask / answers / consume); MCP tools `post_digest_card`, `create_decision`, `list_decisions`, `consume_decision`.
- [x] Tests: vitest unit (links), vitest integration (decisions routes, skip w/o DATABASE_URL), python unittest (render).
- [x] Docs: `docs/manual-tests/2026-10-13-decisions-inbox.html`, ops README, ADR for the card contract.
- [x] Gates: `npm run check`, `npm test -- --run`, `python3 -m unittest`, `bash -n`, `py_compile`.

## Phase 2 (after merge, separate PRs)

- SEO routine posts a card + a "merge PR?" decision; lesson-notes-social posts "publish?" decisions.
- Fix the three live faults: planner-sync (since 10-10), Kuma DNS (since 09-13), elitedesk metrics missing. Silence gpu-queue sentinel.
- Strummy book + EN socials routines, reporting through the same contract from day one.

## Notes

- Migration numbers 016–018 are taken by unmerged branches (multi-project-hub, seo-*); this branch uses 020/021 (renumbered after the SEO PRs took 017–019).
- Branch count is at the limit (5 open + this one). Flagged to Piotr.

## Review (2026-10-13)

Done and verified against a local copy of live elitedesk data. Gates: tsc + biome clean, vitest 39/39 (local Postgres 16), unittest 25/25 agents + 7/7 renderer. Browser-verified: email at phone width, signed-link confirm → record → replay refused, console Decisions tab answering.

Found on live data and fixed before commit: stack traces split into 5 "problems" (now grouped per source), elitedesk under 3 host names (collapsed to one line), job-search app events shown as site probes (now host='rpi' only), future deadlines rendered "just now"/"expires now", red delta on a falling error count (metric.lower_is_better).

Lesson: test fixtures looked fine; real data broke four assumptions. Always dry-run a digest against a live-data copy before calling it done.

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
