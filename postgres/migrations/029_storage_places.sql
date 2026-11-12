-- 029_storage_places.sql
-- Created: 2026-11-12
--
-- The storage register: every place where Piotr's data lives (hosts,
-- folders, databases, cloud accounts). Since 2026-11-12 each place is one
-- vault note in 2-Obszary/mapy/miejsca/NN-name.md with typed frontmatter;
-- planner-sync parses them (agents/elitedesk/storage_md.py) and POSTs the
-- full set to /api/storage/sync, which upserts by id and deletes ids that
-- left the vault. The vault stays authoritative — this is a mirror the
-- weekly audit and the console can query. See docs/adr/2026-11-12-storage-places.md.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.storage_places (
  id               integer     PRIMARY KEY CHECK (id > 0),
  nazwa            text        NOT NULL,
  gdzie            text,
  sciezka          text,
  rola             text,
  stan             text        NOT NULL DEFAULT 'aktywne'
                     CHECK (stan IN ('aktywne', 'usuniete')),
  porzadek         text        NOT NULL DEFAULT 'niesprawdzone'
                     CHECK (porzadek IN ('ok', 'do-poprawy', 'problem', 'niesprawdzone')),
  backup           text        NOT NULL DEFAULT 'brak-oceny'
                     CHECK (backup IN ('ok', 'do-poprawy', 'problem', 'niesprawdzone', 'nie-wymaga', 'brak-oceny')),
  sprawdzone       date,        -- last time someone verified the place
  test_odtworzenia date,        -- last successful restore test of its backup
  sprawdzenie      text,        -- command that re-checks the place (for the audit)
  problem          text,
  note_path        text        NOT NULL,  -- vault-relative path of the note
  updated_at       date,        -- frontmatter `updated`
  synced_at        timestamptz NOT NULL DEFAULT now(),
  raw_frontmatter  jsonb       NOT NULL DEFAULT '{}'::jsonb
);

-- "What is not green yet" and "no backup" are the two questions the audit asks.
CREATE INDEX IF NOT EXISTS storage_places_status_idx ON public.storage_places (stan, porzadek, backup);

COMMENT ON TABLE public.storage_places IS
  'Mirror of the vault storage register (2-Obszary/mapy/miejsca/*.md). Upserted '
  'by planner-sync via POST /api/storage/sync; read by GET /api/storage.';
