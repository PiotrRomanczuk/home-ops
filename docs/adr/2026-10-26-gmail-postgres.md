---
created: 2026-10-26
updated: 2026-10-26
status: accepted
---

# ADR: the personal Gmail mailbox as a `gmail` schema in `home_ops`

**Date**: 2026-10-26 · **Author**: Piotr (with Claude) · **Scope**: `ops/elitedesk/gmail_*`, migration 025, the `gmail-daily` timer

## Context

The Gmail cleanup (2026-10-19 → 10-26, vault `analysis/2026-10-19-gmail-cleanup-plan.md`)
ran from the Mac: an IMAP inventory of 107k message headers in a local SQLite,
a private `gmail-rules.json` (sender/subject rules → exactly one category per
message), add-only labelling through the REST API, and JSONL undo journals for
every batch. It ended with INBOX at zero and every message labelled — but the
rules and the only record of what was applied lived in one copy on one laptop,
the SQLite was a stale snapshot (labels as of inventory time), and "what is the
current category of message X" could only be answered by re-running the
classifier and replaying 20 journals. The daily routine the plan calls for had
no host to run on.

Piotr's decision (2026-10-26): stop deleting, catalogue everything, and move the
catalogue into Postgres so it is queryable, backed up and editable like the rest
of home-ops.

## Decision

1. **A schema, not a database.** `gmail` lives inside `home_ops` (migration
   `025_gmail.sql`), so `pg-backup.sh` already backs it up nightly to the NAS
   and the console can read it over the existing connection. One place per
   role (vault `STORAGE.md` rule), no new container.
2. **Four tables, one function.** `gmail.message` (headers, keyed by the REST
   message id), `gmail.rule` + `gmail.config` (the rules as rows — editable from
   SQL or the console; `gmail.rules_json()` returns them in the exact JSON shape
   the classifier already parses), `gmail.applied` (every journal line
   flattened to one row per message), `gmail.message_state` (current
   category/subcategory/flags, rewritten after each run). The view
   `gmail.category_summary` feeds the console and the digest.
3. **Gmail stays the system of record for mail; Postgres for rules.** Nothing
   in the schema is needed to read mail. If the schema is lost, the classifier
   can run from the JSON export again (`gmail_import.py rules` reverses it).
4. **The classifier does not change.** `gmail_classify.rules_from_dict()` takes
   the same dict from a file or from `gmail.rules_json()`; `GMAIL_RULES=db`
   selects Postgres. Every rule the Mac file had is a row; `automated_only`
   (subject rules that never fire on a person) is a column.
5. **Never delete, never bulk-trash from the routine.** `gmail-daily.py` only
   adds/removes *category* labels (and journals both). Trash/archive stay
   explicit, human-approved operations with their own journals.
6. **Transport = `docker exec psql`**, like `seo_db.py`: COPY FROM STDIN into a
   temp table, then upsert. No driver on the host.
7. **One routine on elitedesk**: `gmail-daily.timer` 06:40 → IMAP inventory of
   new messages → classify → reconcile labels → rewrite state → one digest card
   (`gmail-daily`). The OAuth client + token move to
   `~/.config/home-ops/` on the host; the GCP consent screen must be *In
   production* (Testing-mode refresh tokens expire after 7 days).

## Consequences

- Message subjects and sender addresses of a personal mailbox sit on elitedesk.
  Same trust level as Strummy production data on the same host; the repo is
  public but holds only the schema and code, never data or rules.
- The Mac SQLite becomes a cache of the inventory (still used by the routine
  for the correspondents heuristic and as the IMAP resume point); the
  authoritative copy of headers, rules and applied operations is Postgres.
- Rule edits are SQL (`UPDATE gmail.rule …` / `INSERT`) until the console gets
  a form. The review HTML pages generated on the Mac remain the way to *look*
  at categories; their "poprawki" export maps 1:1 onto rule rows.
- Undo of any batch is still possible from the journals (files and
  `gmail.applied`), but Gmail empties its Trash 30 days after a trash operation
  regardless — the schema records the fact, it cannot bring the mail back.

## Not chosen

- A separate database or Supabase project: another place to back up and secure
  for no isolation gain.
- Storing rules only in Postgres and dropping the JSON path: the JSON path is
  the disaster-recovery route and the unit tests' fixture; both sources go
  through one parser, so keeping it costs nothing.
- A Postgres driver (psycopg): the whole host convention is `docker exec psql`;
  COPY makes the bulk path fast enough (107k rows in seconds).
