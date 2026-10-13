# Decisions inbox + digest rewrite

_2026-10-13_ — branch `feat/decisions-inbox` (worktree `.claude/worktrees/decisions`, from `origin/main`)

Goal: the morning email becomes a report from the routines (what they did, what needs Piotr), not a server dashboard. Routines report through one card contract; anything irreversible asks through a decision with signed yes/no links.

## Phase 1 (this branch)

- [x] Migration `019_digest_cards.sql` — `digest_cards` (routine, ran_at, status, headline, items, metric). Latest row per routine = today's card; history = weekly trend.
- [x] Migration `020_decisions.sql` — `decisions` (routine, slug, question, options, context_url, parent_id, expires_at, answer, reason). Parent id gives trees for free.
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

- Migration numbers 016–018 are taken by unmerged branches (multi-project-hub, seo-*); this branch uses 019/020.
- Branch count is at the limit (5 open + this one). Flagged to Piotr.

## Review (2026-10-13)

Done and verified against a local copy of live elitedesk data. Gates: tsc + biome clean, vitest 39/39 (local Postgres 16), unittest 25/25 agents + 7/7 renderer. Browser-verified: email at phone width, signed-link confirm → record → replay refused, console Decisions tab answering.

Found on live data and fixed before commit: stack traces split into 5 "problems" (now grouped per source), elitedesk under 3 host names (collapsed to one line), job-search app events shown as site probes (now host='rpi' only), future deadlines rendered "just now"/"expires now", red delta on a falling error count (metric.lower_is_better).

Lesson: test fixtures looked fine; real data broke four assumptions. Always dry-run a digest against a live-data copy before calling it done.
