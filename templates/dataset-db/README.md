---
created: 2026-11-14
updated: 2026-11-14
---

# dataset-db — template for a dataset schema in `home_ops`

For **datasets collected by a job** (prices from leaflets, scan results, offers, measurements):
something runs on a schedule, collects documents, and the documents land in Postgres on uwh so
they are backed up and can be queried. Not for products with users (Strummy, lesson-notes,
social-hub): those keep their own database and migration tooling.

Decision and alternatives: `docs/adr/2026-11-14-dataset-db-template.md`.

## Start a new dataset

```bash
~/code/homelab/home-ops/scripts/new-dataset.sh <schema> <package-dir>
# e.g. new-dataset.sh zakupy ~/code/homelab/coupon-ocr/src/coupon_ocr
```

It copies `db/`, `migrations/` and `sql/` into the package and puts the schema name and today's
date into the SQL. This is a copy, not a library: the project owns its copy from then on.

Then:

1. Replace the example table `items` in `migrations/001_init.sql` and `sql/upsert.sql`.
2. Collector writes **JSONL files** (one document per line, every field it got: `data-collection.md`).
   The files are the source of truth; the schema is the backed-up, queryable copy.
3. `sync` command: `db.migrate.migrate(schema, dir, psql)`, then
   `db.load.load({"items": read_jsonl(path)}, upsert, [tables], psql)`.
4. Tests: copy the pattern of `tests/test_live.py` (throwaway Postgres, own schema per test).
5. Vault: a place note in `2-Obszary/mapy/miejsca/` for `home_ops.<schema>` and one for the JSONL folder.

## Conventions

| Topic | Rule | Seen first in |
|---|---|---|
| Where | own schema in `home_ops` on uwh; the nightly `pg-backup` (04:30 → NAS → offsite) covers it | song2logic |
| How the Mac writes | `ssh uwh docker exec -i home-ops-postgres-1 psql`: no driver, password or open port (`db/psql.py`; off the LAN pass `uwo`) | song2logic |
| Schema changes | numbered `migrations/NNN_name.sql` in the owning repo, ledger `<schema>.schema_migrations` with checksums; a file is never edited after it was applied, add a new one (expand → contract) | home-ops, Strummy |
| Raw data | the full document in `raw jsonb` next to the typed columns pulled from it | job-radar, song2logic, Strummy |
| Keys | natural `unique (source, external_id)` plus `bigint generated always as identity` | job-radar |
| Time | `timestamptz`, names ending in `_at`: `fetched_at`, `first_seen_at`, `last_seen_at` | d4 |
| Writing | `insert … on conflict … do update`; `distinct on` the key within one batch; `first_seen_at` and human-set fields are kept; older documents never overwrite newer ones (`where excluded.fetched_at >= …`) | job-radar, song2logic |
| Deleting | never; `db/load.py` aborts a load after which any watched table holds fewer rows | olx-scraper / Strummy incidents |
| Runs | table `runs` (start, end, status, counts, error, stats) | d4, daily-news |
| Value sets | `text` with a named `check` constraint, no enums | job-radar, social-hub |
| Money | integer grosze | Strummy |
| Readers | role `<schema>_ro` (select only) and views as the contract | decision 2026-11-08 |
| Names | snake_case plural tables, indexes `<table>_<cols>_idx`, `comment on table` stating the write rules | lesson-notes, job-radar |

Known limit: writing through `docker exec psql` runs as `postgres`. A dedicated writer role would
need a password and a reachable port, which this pattern avoids on purpose.

## Files

| File | What |
|---|---|
| `db/psql.py` | runs SQL through the psql command (`DATASET_PSQL` or the ssh default); `query()` returns rows as dicts |
| `db/migrate.py` | ledger, order, checksums, one transaction per file; `python -m db.migrate --schema s --dir migrations [--dry-run]` |
| `db/load.py` | JSONL → `copy` into `incoming_<name>` temp tables → your `upsert.sql` → row-count guard → commit (or rollback with `dry_run`) |
| `migrations/001_init.sql` | schema, `runs`, example `items`, a view, the read-only role |
| `sql/upsert.sql` | example upsert from `incoming_items` |
| `tests/` | `test_pure.py` (no database), `test_live.py` (needs `DATASET_TEST_PSQL`) |

Tests:

```bash
docker run -d --rm --name dataset-db-test -e POSTGRES_PASSWORD=x postgres:17-alpine
cd templates/dataset-db
DATASET_TEST_PSQL="docker exec -i dataset-db-test psql -U postgres -d postgres" \
  python3 -m unittest discover -s tests -t . -v
docker stop dataset-db-test
```
