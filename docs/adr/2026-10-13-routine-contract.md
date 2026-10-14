# ADR: Routines report through cards and ask through decisions

**Date**: 2026-10-13
**Status**: accepted
**Scope**: home-ops digest, every scheduled routine on elitedesk

## Context

The morning digest had grown into a terminal dump: 5 KPI tiles (3 about a GPU
lane switched off in July), 2 961 "errors" that were two faults, full Now/Next
vault sections, and `digest.d/*.txt` files rendered daily even when months old.
Meanwhile routines that produce public output (weekly SEO PR, social posts)
had no way to ask before acting, so their output was never merged or was
published unreviewed.

## Options considered

- **Adopt an external approval inbox** (Impri, Pizza Bot, gotoHuman,
  HumanLayer): each assumes the agent runs inside it or waits in-process; ours
  are systemd timers that exit and come back tomorrow. Impri is closest but
  single-maintainer and very early.
- **Adopt an agent orchestrator** (Paperclip): matching vocabulary (board of
  directors, approvals, budgets) but every routine would be rewritten as its
  agent and state would live in a second database.
- **Workflow engine** (Windmill suspend/resume, n8n Wait): proven signed
  resume URLs, but moving the timers into an engine buys nothing.
- **Build a thin layer in home-ops** borrowing those patterns: chosen.

## Decision

1. `digest_cards` — every routine posts one card per run (headline, ≤5 items,
   one metric with direction). Cards past `fresh_for` render as "did not run".
2. `decisions` — a routine about to do something public or irreversible files
   a question and stops. Answers come from signed one-tap links in the email
   (GET confirms, POST records), the console Decisions tab, or the API. A
   rejection carries a one-line reason. `parent_id` gives decision trees
   without a graph model.
3. `GET /api/digest` builds one JSON model; `render-digest.py` is a pure
   renderer. The shell script only fetches, renders, sends.

Borrowed: signed resume/cancel URLs with expiry (Windmill), approve /
reject-with-reason and MCP filing (Impri), "thread you come back to" with an
action queue (Pizza Bot).

## Consequences

- One place (`/api/digest`) decides what is noise; muted patterns are listed
  in code with the decision that muted them.
- Acceptance rate per routine becomes visible, which is the signal for
  keeping or killing a routine.
- Revisit Paperclip if decision trees outgrow `parent_id` or routines need
  budgets.
