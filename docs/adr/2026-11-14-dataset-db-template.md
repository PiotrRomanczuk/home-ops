---
created: 2026-11-14
updated: 2026-11-14
status: accepted
---

# ADR: a template for dataset schemas in `home_ops`

**Date**: 2026-11-14 · **Author**: Piotr (with Claude) · **Scope**: `templates/dataset-db/`, `scripts/new-dataset.sh`; first user: coupon-ocr (schema `zakupy`)

## Context

A survey of all 13 data stores in `~/code` (2026-11-14) found two groups:

- **Products with users** (Strummy, lesson-notes, social-hub): own database, own migration tool
  (Supabase CLI, custom runner, drizzle-kit), own backup. Mature; out of scope here.
- **Datasets filled by a job** (song2logic, job-radar, d4, daily-news, olx-scraper, now leaflet
  prices): each does the same thing differently. Shared good habits: natural key + upsert, raw
  document next to typed columns, nothing deleted, real-Postgres tests. Shared gaps: no migration
  ledger (job-radar has columns "waiting for a migration" with no way to apply them), writes as
  superuser, no guard against a load that empties a table (olx-scraper 2026-10-12, Strummy dev
  2026-11-10).

Two vault decisions pull in different directions: "own database per product" (2026-11-08) and
"a new schema in `home_ops`, don't multiply places" (2026-10-25). Piotr chose (2026-11-14) the
second for datasets: a household dataset is not a product.

## Decision

1. A dataset lives in **its own schema in `home_ops`**. The nightly `pg-backup` already dumps the
   whole database to the NAS and offsite, so a new schema is backed up from day one.
2. The **owning repo** holds the schema as numbered migrations with a ledger
   (`<schema>.schema_migrations`, checksums, files immutable once applied) and applies them itself.
   home-ops' own `postgres/migrations/` stays for home-ops tables.
3. The Mac writes with **`ssh uwh docker exec -i home-ops-postgres-1 psql`** (the song2logic
   pattern): no driver, password or open port. JSONL files stay the source of truth.
4. `templates/dataset-db/` is **copied** into the project by `scripts/new-dataset.sh` (workspace
   rule: projects don't share code). It carries the conventions table in its README.

## Alternatives

- **Own database per dataset in the same container** (like `d4`): cleaner boundary, but it has to
  be added to `pg-backup` and needs a role with a password to be reached from the Mac.
- **Own container** (like lesson-notes): most work, and no existing way for a Mac job to write to it.
- **A shared Python package**: one place to fix bugs, but couples every collector to home-ops'
  release cycle; rejected by the workspace rule.

## Consequences

- Writes run as `postgres`. Accepted: single writer per schema, the guard in `db/load.py` and the
  ledger are the safety net; readers get `<schema>_ro`.
- `schema_migrations` of a dataset is not home-ops' `public.schema_migrations`;
  `scripts/apply-migrations.sh` never touches dataset schemas.
- song2logic and job-radar can move onto the template later (separate plans); nothing changes for them now.
