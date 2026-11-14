-- upsert.sql — moves the documents of temp table incoming_items (doc jsonb, one per line of
-- items.jsonl) into __SCHEMA__.items. Run by db/load.py inside its transaction.
-- `distinct on` keeps the newest copy of a key that appears twice in one batch: ON CONFLICT
-- cannot touch the same row twice in one statement.
insert into __SCHEMA__.items (source, external_id, name, raw, fetched_at)
select distinct on (doc->>'source', doc->>'external_id')
  doc->>'source', doc->>'external_id', doc->>'name', doc, (doc->>'fetched_at')::timestamptz
from incoming_items
order by doc->>'source', doc->>'external_id', (doc->>'fetched_at')::timestamptz desc
on conflict (source, external_id) do update set
  name         = excluded.name,
  raw          = excluded.raw,
  fetched_at   = greatest(__SCHEMA__.items.fetched_at, excluded.fetched_at),
  last_seen_at = now();
