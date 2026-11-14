-- 031_gmail_llm.sql
-- Created: 2026-11-13
--
-- Claude (headless `claude -p`) proposes *rules* for senders the rules do not
-- cover yet: sender (address or exact domain) → category + inbox policy.
-- Nothing changes in Gmail until a human accepts a proposal (terminal review
-- `gmail_review.py` or a yes/no question on "Dziś"); an accepted proposal
-- becomes an ordinary gmail.rule row, so classification stays deterministic.
--
-- gmail.rule.inbox: 'archive' = messages matched by this rule leave the inbox
-- (journaled, undoable, protected mail excepted); 'keep' = labels only.
-- Nothing is ever trashed by this path.
--
-- Idempotent: safe to re-run. Depends on 025_gmail.sql.

ALTER TABLE gmail.rule ADD COLUMN IF NOT EXISTS inbox text NOT NULL DEFAULT 'keep';
DO $$ BEGIN
  ALTER TABLE gmail.rule ADD CONSTRAINT rule_inbox_check CHECK (inbox IN ('keep', 'archive'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS gmail.rule_proposal (
  id             serial      PRIMARY KEY,
  sender         text        NOT NULL,                 -- the address the model looked at
  sender_key     text        NOT NULL,                 -- what goes into rule.senders: address or '@domain'
  scope          text        NOT NULL CHECK (scope IN ('address', 'domain')),
  label          text        NOT NULL,
  inbox          text        NOT NULL CHECK (inbox IN ('keep', 'archive')),
  confidence     real        NOT NULL,
  reason         text,
  model          text        NOT NULL,
  prompt_version text        NOT NULL,
  sample         jsonb       NOT NULL DEFAULT '{}',    -- sender digest the model saw (count, tab, subjects)
  response       jsonb       NOT NULL DEFAULT '{}',    -- Claude's answer for this sender + batch usage/cost
  status         text        NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'accepted', 'rejected')),
  decided_via    text        CHECK (decided_via IN ('terminal', 'dzis')),
  decision_id    bigint,                               -- decisions.id when asked on "Dziś"
  rule_id        integer     REFERENCES gmail.rule (id) ON DELETE SET NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  decided_at     timestamptz
);
-- one live proposal per sender: a rejected sender is not asked again
CREATE UNIQUE INDEX IF NOT EXISTS rule_proposal_sender_idx ON gmail.rule_proposal (sender);
CREATE INDEX IF NOT EXISTS rule_proposal_status_idx ON gmail.rule_proposal (status, created_at);

CREATE OR REPLACE FUNCTION gmail.rules_json() RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    '_doc',     COALESCE((SELECT value FROM gmail.config WHERE key = '_doc'), '""'::jsonb),
    'me',       COALESCE((SELECT value FROM gmail.config WHERE key = 'me'), '[]'::jsonb),
    'freemail', COALESCE((SELECT value FROM gmail.config WHERE key = 'freemail'), '[]'::jsonb),
    'protect',  COALESCE((SELECT value FROM gmail.config WHERE key = 'protect'), '{}'::jsonb),
    'rules',    COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                  'label', label, 'from', to_jsonb(senders), 'subject', subject,
                  'automated_only', CASE WHEN automated_only THEN true END,
                  'inbox', CASE WHEN inbox = 'archive' THEN 'archive' END)) ORDER BY position, id)
                 FROM gmail.rule WHERE kind = 'rule' AND enabled), '[]'::jsonb),
    'subrules', COALESCE((SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                  'parent', parent, 'label', label, 'from', to_jsonb(senders), 'subject', subject)) ORDER BY position, id)
                 FROM gmail.rule WHERE kind = 'subrule' AND enabled), '[]'::jsonb));
$$;

COMMENT ON TABLE gmail.rule_proposal IS 'Rules proposed by a local LLM for uncovered senders; accepted ones become gmail.rule rows.';
