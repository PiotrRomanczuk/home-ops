---
created: 2026-11-14
updated: 2026-11-14
status: accepted
---

# ADR: The Mac joins home-ops as a sleeping host, with a journal of Claude Code work

**Date**: 2026-11-14 · **Author**: Piotr (with Claude) · **Scope**: agents (`claude-collector`, `mac/*`), ingest (`/api/claude/*`, `/api/journal/*`), migration 032, Dziś / Hosty / Status / Postęp

## Context

Since 2026-11-07 all development happens on the Mac. That is where the day goes, and home-ops did not see it.
On 2026-11-14 58 GB of models were downloading in the background, and finding out *which Claude session started it,
and why* took a manual dig through `ps`, scratchpads and transcripts.

Piotr wants one place with (a) everything done with Claude Code and (b) what runs on the Mac's CPU, GPU and network,
to decide where to go next. Decisions taken with him:

- the place is home-ops (not a local-only report);
- the database keeps prompts and actions with secrets masked; raw transcripts stay on the host;
- a local model on the Mac writes the evening "what next";
- sessions come from the Mac and from elitedesk's headless agents.

## Decision

1. **Claude Code transcripts are the source.** `~/.claude/projects/**.jsonl` already records prompts, tool calls,
   tokens, titles, PRs, pushes, compactions and away summaries.
   - Hooks were rejected: they only see the future, miss Desktop and phone sessions, and add latency to every tool call.
   - `agents/claude-collector.py` runs every 5 min (launchd on the Mac, a systemd timer on elitedesk). It reads each
     file from the byte offset reached last time and folds the new lines into one row per session
     (`claude_transcript.py`).
   - It POSTs `/api/claude/sessions` and `/api/claude/events`. If either fails, it does not save its state, and the
     next run re-reads the same lines; events are idempotent on `(host, session_id, uuid)`.
2. **Masking happens on the host.** `agents/redact.py` keeps the first 6 characters of a secret plus `...`. It runs
   on prompts, Bash commands and process command lines (MCP servers get API keys and DSNs as arguments).
3. **Project = evidence, resolved server-side.** In order:
   1. the cwd's git origin vs the note's `repo:`;
   2. the cwd folder name vs the slug;
   3. the cwd under the note's `path:`;
   4. for sessions started from `~` (most of them), the `~/code/<group>/<slug>/` folder holding most of the edited
      files.

   Counts land in `project_signals` (`claude_prompts`, `claude_sessions`). They are recomputed per touched day, never
   added, so re-sent batches can't double count.
4. **`mac-watcher` is a sibling of rpi/win10-watcher.** It sends `host_metrics` as host `mac`, every 30 s, with no
   sudo:
   - **GPU:** `ioreg` gives Apple GPU utilisation and memory.
   - **Network per process:** `nettop` deltas.
   - **Attribution:** each process is linked to the Claude session that started it. It walks ancestors up to a pid in
     `~/.claude/sessions/<pid>.json`, or to a command line pointing into the session's scratchpad (this catches
     detached jobs whose ppid is 1).
   - **Notable processes** become `host_logs` lines "proc start/stop": a session's Bash-tool job alive for 2 min or
     more, 25 % CPU or more in two samples, or 1 MB/s or more.
5. **The laptop sleeps and roams.**
   - Every sample is archived locally first (`~/.local/state/home-ops/mac/metrics-YYYY-MM-DD.jsonl`, gzipped daily).
   - The watcher sends over the LAN at home and over Tailscale elsewhere. Anything undeliverable waits in a spool and
     is replayed with its original `ts`.
   - `host_profiles.sleeps` (032) stops the dead-agent sentinel from alerting and shows the Mac as asleep, not
     down, on Dziś, Status and the digest mail.
6. **The day is a rollup plus a note.** `GET /api/journal/day` composes one Warsaw day: hours, top apps, process runs,
   Claude sessions on every host. "Active time" is the number of distinct 5-minute buckets with any Claude event.
   - `day-summary` runs at 21:30 (launchd re-runs a missed slot after wake). It asks the local Ollama for
     "Dzień" + "Co dalej" and stores both in `day_journal`, with no pruning, so the day outlives `host_metrics`' 30
     days.
   - It posts the card `mac-dziennik` on Dziś. If Ollama is down, the card stays factual.

## Consequences

- One shared `INGEST_TOKEN`, as everywhere: on the Mac it lives in the Keychain (`home-ops-ingest`), read by
  `agents/mac/run.sh`, never in a plist or file.
- `deploy-agent.sh` gains `mac` (run on the Mac: copies to `~/bin/home-ops/`, installs the LaunchAgent) and timer
  support (`<agent>.timer` next to the unit). Root-level `agents/*.py` libraries are now copied to every host.
- Per-process GPU stays unknown without root (`powermetrics`). The proxy is host GPU % plus the models loaded in
  Ollama.
- `claude_events` grows by roughly 10 k rows a week. They are small, text-only and intentionally not pruned (the
  data-collection rule).
- The day view in the console (React SPA, next to Mapa) is a separate PR on top of #76. Until then the data shows up
  in the Dziś card, Hosty (mac), Status and Postęp (view "Claude").

## Rejected

- **Claude Code hooks as the feed.** See Decision 1.
- **A local-only HTML report on the Mac.** It would be a second place, outside the planner and digest loop.
- **Per-host tokens.** Already rejected for home-ops (`CONTEXT.md`).
- **`claude -p` for the evening note.** It costs plan quota every day. The local model is free and private.
