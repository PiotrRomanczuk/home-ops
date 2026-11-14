-- 001_init.sql — schema __SCHEMA__: <one line: what this dataset holds>
-- Created: __DATE__
--
-- Writer: <repo> (`<cli> sync`, run on the Mac, reaches uwh as `ssh uwh docker exec -i
-- home-ops-postgres-1 psql`). Readers: role __SCHEMA___ro through the views below.
-- Applied by db/migrate.py in one transaction and recorded in __SCHEMA__.schema_migrations.
-- Never edit this file once applied: add 002_… instead.

create schema if not exists __SCHEMA__;

-- One row per run of the collector: when, how much, what failed.
create table if not exists __SCHEMA__.runs (
  id          bigint generated always as identity primary key,
  started_at  timestamptz not null,
  finished_at timestamptz,
  status      text not null default 'running'
              constraint runs_status_check check (status in ('running', 'ok', 'failed')),
  counts      jsonb not null default '{}'::jsonb,
  error       text,
  stats       jsonb not null default '{}'::jsonb
);
comment on table __SCHEMA__.runs is
  'One row per collector run. counts = rows written per table, stats = timings/tokens/cost.';

-- Example ingest table: replace or extend. Keep the shape: natural key, typed columns pulled from
-- the document, the full document in raw, first/last seen.
create table if not exists __SCHEMA__.items (
  id            bigint generated always as identity primary key,
  source        text not null,
  external_id   text not null,
  name          text not null,
  status        text not null default 'new'
                constraint items_status_check check (status in ('new', 'seen')),
  raw           jsonb not null,
  fetched_at    timestamptz not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  constraint items_source_external_id_key unique (source, external_id)
);
create index if not exists items_last_seen_at_idx on __SCHEMA__.items (last_seen_at);
comment on table __SCHEMA__.items is
  'Upsert on (source, external_id): typed columns and raw are refreshed, first_seen_at and a '
  'human-set status are kept, rows are never deleted.';

-- Consumers read through views; the read-only role is the contract.
create or replace view __SCHEMA__.items_recent as
  select id, source, external_id, name, status, fetched_at, first_seen_at, last_seen_at
  from __SCHEMA__.items
  where last_seen_at > now() - interval '30 days';

do $$
begin
  if not exists (select 1 from pg_roles where rolname = '__SCHEMA___ro') then
    create role __SCHEMA___ro nologin;
  end if;
end $$;
grant usage on schema __SCHEMA__ to __SCHEMA___ro;
grant select on all tables in schema __SCHEMA__ to __SCHEMA___ro;
alter default privileges in schema __SCHEMA__ grant select on tables to __SCHEMA___ro;
