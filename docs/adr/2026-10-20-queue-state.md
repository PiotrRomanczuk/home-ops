---
created: 2026-10-20
updated: 2026-10-20
status: accepted
---

# ADR: the agent queue (vault `QUEUE.md`) mirrored as `queue_state`

**Date**: 2026-10-20 · **Author**: Piotr (with Claude) · **Scope**: planner-sync, ingest `/api/queue*`, the "Dziś" tab

## Context

Since 2026-10-19 the planner vault has a single `QUEUE.md`: one work window
(dates, capacity in hours, focus), **one ticket in progress** (WIP = 1), an
ordered queue, a local-LLM lane, items waiting for Piotr and what was done in
the window. Design and the priority rubric: vault
`analysis/2026-10-19-agent-queue-design.md` (§4 file shape, §8 rubric, §9
local lane). Every Claude Code session reads the "W toku" section through a
`SessionStart` hook; nothing in home-ops knew the file existed.

The console's "Dziś" tab already merges the vault's Now sections, the Board,
problems and decisions into one page. The queue is the one missing input, and
it was planned as the first UI step ("1a") once the file proved itself.

## Decision

1. **The vault stays authoritative.** home-ops only mirrors the file; nothing
   writes back. Editing happens in Obsidian or by Claude sessions.
2. **One parser, in the agent.** `agents/elitedesk/queue_md.py` turns the
   markdown into JSON (header fields, five sections of tickets, a summary).
   It is tolerant: an unclassified line is kept as text, never dropped. Ticket
   shape follows rubric §8: class (🔴 💰 🎯 🧹 💡 → `risk|money|focus|clean|idea`),
   size `S|M|L|XL`, flags (⛓ `unblocks`, 🖥 `local`, ⏸ `paused`, 🧪
   `experiment`), entry date, `[[project]]`, `ID-n`, text, `plan → exec`
   model, trailing meta, indented brief lines, and a duration (`~1 h`,
   `30 min`) summed into `summary.done_hours`.
3. **One row.** Migration 023 creates `public.queue_state` (`id = 1`), with
   `sections` and `summary` as jsonb. planner-sync POSTs `/api/queue/sync`
   (token) once per file change; the API also short-circuits on
   `source_hash`, so restarts cost one SELECT. `GET /api/queue` (viewer)
   returns the row; `GET /api/today` carries it as `queue`.
4. **The card, not a tab.** `today-queue.js` renders the window and capacity
   bar (done hours vs capacity, plus the in-progress ticket's size budget
   S=1 h, M=3 h, L=8 h), the ticket in progress, the next three, and one line
   of counts. Design: Claude Design project "home-ops · Kolejka agentów",
   option 1a. Options 1b (a "Kolejka" tab) and 1c ("Modele", from a future
   `agent_runs` table) wait for ten tickets of real use.
5. **Helpers deploy with the agent.** `deploy-agent.sh` now rsyncs
   `agents/<host>/*_*.py` next to the hyphenated agent file, so a module
   like `queue_md.py` imports on the host.

## Consequences

- planner-sync gains one tick step and one network call per file change; a
  missing `QUEUE.md` is silently a no-op (the card stays hidden).
- The card shows only what the file says. Hours come from `~1 h` / `30 min`
  in done lines, so the capacity bar is as honest as the retro lines are.
- CI applies 023 and runs `queue.test.ts` against real Postgres.
- Deploy (uwh): `scripts/apply-migrations.sh`, rebuild `ingest`
  (`docker compose up -d --build ingest`), `scripts/deploy-agent.sh elitedesk
  planner-sync`.

## References

- Vault: `QUEUE.md`, `analysis/2026-10-19-agent-queue-design.md`
- Code: `agents/elitedesk/queue_md.py`, `ingest/src/queue-model.ts`,
  `ingest/src/routes/queue.ts`, `ingest/public/today-queue.js`,
  `postgres/migrations/023_queue_state.sql`
- Report: `docs/manual-tests/2026-10-20-queue-card-today.html`
- Related: `2026-10-17-daily-briefs.md` (same mirror pattern for briefs)
