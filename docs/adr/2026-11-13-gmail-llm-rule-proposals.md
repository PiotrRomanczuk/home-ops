---
created: 2026-11-13
updated: 2026-11-14
status: accepted
---

# ADR: Claude proposes Gmail rules; a human accepts them

**Date**: 2026-11-13 · **Author**: Piotr (with Claude) · **Scope**: `ops/elitedesk/gmail_llm*.py`, `gmail_review.py`, `gmail-llm.py`, migration 031, the `gmail-daily` routine

## Context

`gmail-daily` (ADR 2026-10-26) labels every message with deterministic rules. Mail no rule
covers falls back to Gmail's tabs (`Promocje`, `Powiadomienia`, `Newslettery`) or to
`Inne/Do-przejrzenia`; on 2026-11-09 the second INBOX ZERO had to be done by hand, sender
by sender. A model can do the judging — but `reconcile_live` recomputes labels from the
rules on every run and removes anything else, so labels written by a model would be undone
the next morning.

## Decision

1. **The model proposes rules, not labels.** For each sender whose mail lands only in
   weak buckets (reason `none` / `tab` / `unsub`) it proposes `sender (address or exact
   domain) → category + inbox policy (keep | archive)`. The category is a JSON Schema enum
   of the existing labels; anything off-schema becomes `Inne/Do-przejrzenia`. Freemail
   domains never get a domain rule.
2. **A human accepts** — backlog in the terminal (`gmail_review.py`), new senders as yes/no
   questions on "Dziś" (at most 3 open; options *tak / tak, ale w skrzynce / nie*). An
   accepted proposal is appended to `gmail.rule` (note `llm <model> <date>`), so
   classification stays deterministic and explainable. A rejected sender is never asked again.
3. **Archive, never trash.** `gmail.rule.inbox = 'archive'` moves matched inbox mail to the
   archive through `gmail_apply.move` (journaled, `undo` restores INBOX); protected mail
   (starred, protected categories, document-like subjects) is never archived.
4. **Claude, not a local model — by measurement.** `gmail_llm_eval.py` replays the existing
   rules as gold (senders labelled by a single rule; the model never sees the rules, and the
   example senders shown per category never come from a domain in the same batch). Local
   models on wfh reached 26 % (`qwen3.5:9b`) and ~45 % (`gemma4:12b`) exact agreement with
   flat confidence. Claude with per-category examples, 588 gold senders: Sonnet 59 % exact /
   63 % same branch, **Opus 64 % / 68 %**, and Opus's confidence is calibrated (≥ 0.9 → 94 %
   right, 90 senders). Misses are mostly neighbouring categories of the owner's taxonomy.
   Piotr chose Claude (2026-11-13); default model `opus`. Details in the vault:
   `3-Zasoby/analysis/2026-11-13-gmail-llm-ewaluacja.md`.
6. **Review only, no auto mode.** 64–68 % agreement is below the 80 % bar; every proposal goes
   through a human. Auto acceptance (e.g. confidence ≥ 0.9) only after real review statistics.
5. **Headless `claude -p` on the Max subscription**, as `seo_llm.py` already does: batches of
   20 senders, `--json-schema` for structured output, and the CLI trimmed to ~1k tokens of
   overhead (`--tools ''`, `--strict-mcp-config`, `--setting-sources ''`, own `--system-prompt`)
   — without the trimming one call loaded ~570k tokens of user config.

## Consequences

- `gmail-daily` gains three steps (consume answers → … → propose, ask, archive); `GMAIL_LLM=0`
  switches them off.
- Claude sees headers only (sender, name, Gmail tab, unsubscribe share, recent subjects) —
  these leave the home network to Anthropic; bodies stay in Gmail. A snippet could be added
  later from the REST `metadata` response.
- `gmail-daily.env` needs `CLAUDE_CODE_OAUTH_TOKEN` (same token as `seo-collect.env`); a failed
  call (limit, network, logged-out CLI) only skips proposals for that day.
- Rules created this way are ordinary rows: editable, disable-able (`enabled = false`), and
  visible in `gmail.rules_json()` with their `inbox` policy.
