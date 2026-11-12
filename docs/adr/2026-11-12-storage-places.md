---
created: 2026-11-12
updated: 2026-11-12
status: accepted
---

# ADR: the vault storage register mirrored as `storage_places`

**Date**: 2026-11-12 · **Author**: Piotr (with Claude) · **Scope**: planner-sync, ingest `/api/storage*`, migration 029

## Context

The vault keeps a register of every place where Piotr's data lives (hosts,
folders, databases, cloud accounts): `2-Obszary/mapy/STORAGE.md`. Until
2026-11-12 it was one markdown table — 78 rows, cells of several hundred
characters, three duplicated row numbers and one row with a missing column.
Piotr's goal is "absolute order" in every place, which needs a strict
definition of green (7 conditions, vault
`3-Zasoby/analysis/2026-11-12-porzadek-wszystkich-miejsc.md`), a weekly
automated audit, and queries such as "places without a restore test in 90 days".
A table cell cannot be validated, queried or updated by a machine.

## Decision

- **Source of truth stays in the vault**, one note per place:
  `2-Obszary/mapy/miejsca/NN-name.md` with flat frontmatter (`type: miejsce`,
  `id`, `nazwa`, `gdzie`, `sciezka`, `rola`, `stan`, `porzadek`, `backup`,
  `sprawdzone`, `test_odtworzenia`, `sprawdzenie`, `problem`, `updated`).
  The register describes where backups and keys are and how to recover them,
  so it must not live only on uwh, the server it describes; the vault is on
  the Mac, uwh and the NAS and readable offline.
- **Postgres is a mirror**, like `public.projects`: planner-sync parses the
  notes (`agents/elitedesk/storage_md.py`) and POSTs the full set to
  `POST /api/storage/sync` **only when the notes change** (md5 of the parsed
  set). The handler validates (`ingest/src/storage-model.ts`), upserts by `id`
  and deletes ids that left the vault, in one transaction. An empty valid set
  is refused (400) so a broken clone cannot wipe the table.
- **Statuses are enums enforced twice** (TS validator + CHECK constraints):
  `porzadek` ok / do-poprawy / problem / niesprawdzone; `backup` the same plus
  nie-wymaga / brak-oceny; `stan` aktywne / usuniete. Invalid notes are
  rejected individually and logged by planner-sync with their note path.
- `GET /api/storage` (viewer or token) returns the places ordered by id, with
  optional `stan`, `porzadek`, `backup`, `gdzie` filters and per-status counts.

## Consequences

- The weekly audit (next step) can read the `sprawdzenie` commands from the
  table and write its measurements to a separate `storage_checks` history
  table — not part of this change.
- The parser passes values through untouched; the server is the only place
  that decides what is valid, so the two cannot drift.
- Editing still happens only in Obsidian. The table is never written back.
