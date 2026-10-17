# ADR: Day briefs come from a cloud routine via a git repo, shown on a "Dziś" tab

**Date**: 2026-10-17
**Status**: accepted
**Scope**: home-ops console (default tab), ingest API, elitedesk units, repo `PiotrRomanczuk/daily-brief`

## Context

Piotr wants a morning plan and an evening review of the working day (calendar,
Now tasks from the vault, open signals). The analysis runs as Claude Code cloud
routines (Google Calendar connector, the vault mirror `PiotrRomanczuk/planner`
on GitHub). Those routines cannot reach the console API: `:64421` is
LAN/Tailscale-only and must stay that way. The same tool is meant to move to
an office setup in November, so the "recipe" (prompts, config) lives in its own
portable repo, not in home-ops.

## Decision

1. The routine commits one markdown file per run to `PiotrRomanczuk/daily-brief`
   at `briefs/YYYY-MM-DD-<slot>.md`. **File contract**:

   ```markdown
   ---
   date: 2026-10-17                       # YYYY-MM-DD, must match the filename
   slot: morning                          # morning | evening, must match the filename
   generated_at: 2026-10-17T07:02:41+02:00  # ISO 8601
   title: "Sobota 17.10 — dzień na home-ops"
   sources: [google-calendar, planner]    # flow list or block list of strings
   ---

   ## Section heading
   - bullets, **bold**, `code`, [links](https://…) (http/https only),
     [[wikilinks]] (rendered as plain text)
   ```

   Body ≤ 20 000 chars. Only that markdown subset renders; anything else shows as text.
2. elitedesk **pulls** (`ops/elitedesk/brief-pull.py`, user timer every 15 min):
   `git pull --ff-only` with a read-only deploy key, then POSTs every brief file
   added/changed since the last processed commit to `POST /api/briefs`
   (token-only, upsert on `(brief_date, slot)`). No inbound exposure.
3. `daily_briefs` (migration 022) keeps 120 days (pg_cron prune); the repo is the
   full history.
4. `GET /api/today` composes the page model: latest brief (today's evening ›
   today's morning › most recent), unchecked Now lines of hot/warm projects +
   Board Now cards (deduped), problems/hosts reusing the digest SQL, open
   decisions **without signed links** (viewer-readable endpoint), fresh cards.
5. The console's default tab becomes **„Dziś”** (key `1`; others shift by one,
   Decisions moves to `0`). Markdown is rendered by `md-lite.js`: escape first,
   then a fixed pattern set.

## Options considered

- **Routine POSTs straight to the API**: needs the API on the internet
  (Cloudflare tunnel + auth). Rejected — larger attack surface for a page only
  Piotr reads.
- **Email the brief**: the inbox is being cleaned up, and an email can't sit
  next to live tasks and problems.
- **Render on uwh with a local model**: no calendar connector, weaker analysis.

## Consequences

- A brief appears ≤ 15 min after the routine pushes. Idempotent: deleting the
  state file re-sends everything harmlessly.
- A malformed file is logged (`agent:brief-pull`, level error → shows in
  Problemy) and skipped; network/5xx failures keep the state file in place and retry.
- At work, the same contract can feed a different viewer; nothing in the file
  format is home-ops-specific.
