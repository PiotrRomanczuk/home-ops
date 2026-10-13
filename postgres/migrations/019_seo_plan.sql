-- 019_seo_plan.sql
-- "Plan as state" for the SEO routine (ops/elitedesk/seo-*.py):
--   * seo_plan          — one row per hypothesis. The weekly seo-improve job
--                         executes 'ready' rows (→ PR, 'in_pr'); when the PR is
--                         merged the daily job stamps shipped_at and from then
--                         on evaluates the hypothesis at 14 and 28 days against
--                         its own baseline AND the control pages (pages no
--                         shipped hypothesis targets), giving a verdict of
--                         helped / hurt / neutral / insufficient.
--   * seo_page_snapshot — daily crawl of the site's own sitemap: what the HTML
--                         actually says (title, description, canonical, robots,
--                         JSON-LD, CTA + internal-link coverage). Diffed day to
--                         day for drift (regressions after our own changes).
--   * seo_findings      — deterministic rule hits keyed by (site, path, rule)
--                         with an open/auto-resolve lifecycle (Cloudflare
--                         seo-agent pattern): re-raised when seen again,
--                         resolved when the condition clears, never duplicated.
-- Idempotent: safe to re-run on an existing deploy.

CREATE TABLE IF NOT EXISTS public.seo_plan (
  id             serial      PRIMARY KEY,
  site           text        NOT NULL,
  title          text        NOT NULL,
  change         text        NOT NULL,
  rationale      text,
  target_queries text        NOT NULL DEFAULT '',      -- regex over GSC query, '' = none
  target_pages   text[]      NOT NULL DEFAULT '{}',    -- URL paths, e.g. {'/','/poradnik/x'}
  metric         text        NOT NULL DEFAULT 'impressions',
  status         text        NOT NULL DEFAULT 'proposed',
  priority       integer     NOT NULL DEFAULT 50,      -- higher first
  observe_days   integer     NOT NULL DEFAULT 28,
  source         text        NOT NULL DEFAULT 'llm',   -- llm | piotr | rule
  pr_url         text,
  shipped_at     date,
  baseline       jsonb,
  verdict        jsonb,                                -- {"day14": {...}, "day28": {...}}
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT seo_plan_metric_chk CHECK (metric IN ('impressions', 'clicks', 'ctr', 'position')),
  CONSTRAINT seo_plan_status_chk CHECK (status IN
    ('proposed', 'ready', 'in_pr', 'shipped', 'helped', 'hurt', 'neutral', 'retired')),
  CONSTRAINT seo_plan_site_title_uniq UNIQUE (site, title)
);

CREATE INDEX IF NOT EXISTS seo_plan_site_status_idx ON public.seo_plan (site, status, priority DESC);

CREATE TABLE IF NOT EXISTS public.seo_page_snapshot (
  site            text        NOT NULL,
  day             date        NOT NULL,
  path            text        NOT NULL,
  status_code     integer     NOT NULL,
  title           text,
  description     text,
  canonical       text,
  robots          text,
  has_jsonld      boolean     NOT NULL DEFAULT false,
  words           integer     NOT NULL DEFAULT 0,
  cta_links       integer     NOT NULL DEFAULT 0,     -- links to booking / pricing / tel:
  internal_links  integer     NOT NULL DEFAULT 0,
  h1              text,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, day, path)
);

CREATE TABLE IF NOT EXISTS public.seo_findings (
  site         text        NOT NULL,
  path         text        NOT NULL,
  rule         text        NOT NULL,
  severity     text        NOT NULL DEFAULT 'warn',
  detail       text        NOT NULL,
  status       text        NOT NULL DEFAULT 'open',
  first_seen   date        NOT NULL,
  last_seen    date        NOT NULL,
  resolved_at  date,
  PRIMARY KEY (site, path, rule),
  CONSTRAINT seo_findings_status_chk CHECK (status IN ('open', 'resolved', 'dismissed'))
);

COMMENT ON TABLE public.seo_plan IS
  'SEO hypotheses. Lifecycle: proposed → ready (Piotr/LLM) → in_pr (seo-improve opened a PR) → shipped (PR merged) '
  '→ helped | hurt | neutral (verdict after observe_days) | retired. Evaluated by ops/elitedesk/seo_plan.py.';
COMMENT ON COLUMN public.seo_plan.target_queries IS
  'Case-insensitive regex matched against seo_gsc_daily.query; the hypothesis metric is summed over matching rows.';
COMMENT ON TABLE public.seo_findings IS
  'Deterministic rule hits from the daily own-site crawl (seo_drift.py). Re-open on recurrence, auto-resolve when clear.';
