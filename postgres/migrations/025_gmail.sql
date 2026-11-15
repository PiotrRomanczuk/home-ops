-- 025_gmail.sql
-- Created: 2026-10-26
--
-- The personal Gmail mailbox (p.romanczuk@) as data: every message's headers,
-- the categorisation rules (editable rows instead of a private JSON on the Mac),
-- what was applied to which message and when (the undo journals), and the
-- current category of each message. Written by ops/elitedesk/gmail_import.py
-- (one-off backfill) and gmail-daily.py (timer). Gmail itself stays the
-- system of record for mail; this schema is the system of record for *rules*.
-- See docs/adr/2026-10-26-gmail-postgres.md.
--
-- Idempotent: safe to re-run.

CREATE SCHEMA IF NOT EXISTS gmail;

-- One row per message, keyed by the REST message id (hex of X-GM-MSGID).
CREATE TABLE IF NOT EXISTS gmail.message (
  id             text        PRIMARY KEY,
  thread_id      text,
  internal_at    timestamptz NOT NULL,
  size_bytes     integer     NOT NULL DEFAULT 0,
  from_addr      text        NOT NULL DEFAULT '',
  from_name      text        NOT NULL DEFAULT '',
  from_domain    text        NOT NULL DEFAULT '',
  to_addrs       text        NOT NULL DEFAULT '',   -- comma-joined, lower-cased
  subject        text        NOT NULL DEFAULT '',
  has_unsub      boolean     NOT NULL DEFAULT false, -- List-Unsubscribe header present
  gmail_labels   text        NOT NULL DEFAULT '',   -- labelIds at inventory time (INBOX, UNREAD, CATEGORY_*…)
  inventoried_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS message_from_addr_idx   ON gmail.message (from_addr);
CREATE INDEX IF NOT EXISTS message_from_domain_idx ON gmail.message (from_domain);
CREATE INDEX IF NOT EXISTS message_internal_at_idx ON gmail.message (internal_at DESC);

-- Rules, in evaluation order (first hit wins). kind='subrule' refines `parent`.
-- senders: 'addr@x.pl' exact, '@x.pl' exact domain, 'x.pl' domain + subdomains.
CREATE TABLE IF NOT EXISTS gmail.rule (
  id             serial      PRIMARY KEY,
  position       integer     NOT NULL,
  kind           text        NOT NULL DEFAULT 'rule' CHECK (kind IN ('rule', 'subrule')),
  parent         text,                                -- subrule only: the category it refines
  label          text        NOT NULL,
  senders        text[]      NOT NULL DEFAULT '{}',
  subject        text,                                -- case-insensitive regex (Python re)
  automated_only boolean     NOT NULL DEFAULT false,  -- subject rule applies to bot-like senders only
  enabled        boolean     NOT NULL DEFAULT true,
  note           text,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rule_order_idx ON gmail.rule (kind, position);

-- Scalar config the classifier needs besides rules: me, freemail, protect, _doc.
CREATE TABLE IF NOT EXISTS gmail.config (
  key        text        PRIMARY KEY,
  value      jsonb       NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Every label/trash/archive/read/restore operation, one row per message, as
-- recorded in the JSONL undo journals (journal file + line = one batch).
CREATE TABLE IF NOT EXISTS gmail.applied (
  journal    text        NOT NULL,   -- basename of the journal file
  line_no    integer     NOT NULL,
  message_id text        NOT NULL,
  op         text        NOT NULL,   -- add | remove | trash | archive | read | restore | label-*
  label      text,                   -- category label, or TRASH / INBOX / UNREAD for moves
  had_inbox  boolean     NOT NULL DEFAULT false,  -- trash/archive: message was in INBOX before (undo puts it back)
  note       text,
  ts         timestamptz NOT NULL,
  PRIMARY KEY (journal, line_no, message_id)
);
CREATE INDEX IF NOT EXISTS applied_message_idx ON gmail.applied (message_id);
CREATE INDEX IF NOT EXISTS applied_ts_idx      ON gmail.applied (ts DESC);

-- Current classification per message, rewritten by gmail-daily after each run.
CREATE TABLE IF NOT EXISTS gmail.message_state (
  message_id  text        PRIMARY KEY REFERENCES gmail.message (id) ON DELETE CASCADE,
  category    text        NOT NULL,
  subcategory text,
  reason      text        NOT NULL,   -- rule | rule:recipient | me | person | tab | unsub | none
  in_trash    boolean     NOT NULL DEFAULT false,
  in_inbox    boolean     NOT NULL DEFAULT false,
  unread      boolean     NOT NULL DEFAULT false,
  protected   boolean     NOT NULL DEFAULT false,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS message_state_category_idx ON gmail.message_state (category, subcategory);

-- The rules in the exact JSON shape gmail_classify.rules_from_dict() reads
-- (same as the former ~/.config/home-ops/gmail-rules.json), so the classifier
-- has one parser for both sources.
CREATE OR REPLACE FUNCTION gmail.rules_json() RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    '_doc',     COALESCE((SELECT value FROM gmail.config WHERE key = '_doc'), '""'::jsonb),
    'me',       COALESCE((SELECT value FROM gmail.config WHERE key = 'me'), '[]'::jsonb),
    'freemail', COALESCE((SELECT value FROM gmail.config WHERE key = 'freemail'), '[]'::jsonb),
    'protect',  COALESCE((SELECT value FROM gmail.config WHERE key = 'protect'), '{}'::jsonb),
    'rules',    COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                  'label', label, 'from', to_jsonb(senders), 'subject', subject,
                  'automated_only', CASE WHEN automated_only THEN true END)) ORDER BY position, id)
                 FROM gmail.rule WHERE kind = 'rule' AND enabled), '[]'::jsonb),
    'subrules', COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                  'parent', parent, 'label', label, 'from', to_jsonb(senders), 'subject', subject)) ORDER BY position, id)
                 FROM gmail.rule WHERE kind = 'subrule' AND enabled), '[]'::jsonb));
$$;

-- Category sizes for the console / digest.
CREATE OR REPLACE VIEW gmail.category_summary AS
SELECT s.category, s.subcategory,
       count(*)                          AS messages,
       count(*) FILTER (WHERE s.in_inbox) AS in_inbox,
       count(*) FILTER (WHERE s.unread)   AS unread,
       count(*) FILTER (WHERE s.in_trash) AS in_trash,
       sum(m.size_bytes)                  AS bytes,
       max(m.internal_at)                 AS newest
FROM gmail.message_state s JOIN gmail.message m ON m.id = s.message_id
GROUP BY 1, 2;

COMMENT ON SCHEMA gmail IS 'Personal Gmail cleanup: message headers, categorisation rules, applied-operations log, current category per message.';
