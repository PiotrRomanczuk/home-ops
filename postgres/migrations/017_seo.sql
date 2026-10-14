-- 017_seo.sql
-- Daily search-visibility snapshots for Piotr's public sites (gitarawarszawa.pl,
-- romanczuk.online), written by ops/elitedesk/seo-collect.py via
-- POST /api/seo/ingest. Three sources, one table each, all keyed so a re-run
-- of the same day upserts instead of duplicating:
--   * seo_gsc_daily    — Search Console: query × page per day (2–3 day lag, so
--                        the collector re-fetches a rolling window).
--   * seo_ga4_daily    — GA4: sessions/users + tracked conversion events per
--                        day × source/medium.
--   * seo_places_daily — Google Places: rating + review count per business per
--                        day (own listing + local competitors), the basis for
--                        review-velocity comparisons.
--
-- Numbered 017 (not 016) because feature/multi-project-hub already claims 016.
-- Idempotent: safe to re-run on an existing deploy.

CREATE TABLE IF NOT EXISTS public.seo_gsc_daily (
  site        text        NOT NULL,
  day         date        NOT NULL,
  query       text        NOT NULL,
  page        text        NOT NULL,
  clicks      integer     NOT NULL,
  impressions integer     NOT NULL,
  ctr         real        NOT NULL,
  position    real        NOT NULL,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, day, query, page)
);

CREATE INDEX IF NOT EXISTS seo_gsc_daily_site_query_idx ON public.seo_gsc_daily (site, query, day DESC);

CREATE TABLE IF NOT EXISTS public.seo_ga4_daily (
  site          text        NOT NULL,
  day           date        NOT NULL,
  source_medium text        NOT NULL,
  sessions      integer     NOT NULL,
  users         integer     NOT NULL,
  events        jsonb       NOT NULL DEFAULT '{}'::jsonb,
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, day, source_medium)
);

CREATE TABLE IF NOT EXISTS public.seo_places_daily (
  place_id     text        NOT NULL,
  day          date        NOT NULL,
  label        text        NOT NULL,
  name         text        NOT NULL,
  is_self      boolean     NOT NULL DEFAULT false,
  rating       real,
  review_count integer,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (place_id, day)
);

CREATE INDEX IF NOT EXISTS seo_places_daily_label_idx ON public.seo_places_daily (label, day DESC);

COMMENT ON TABLE public.seo_gsc_daily IS
  'Search Console searchAnalytics rows (dimensions date, query, page). site = config slug '
  '(e.g. gitarawarszawa.pl), same key as seo_ga4_daily.site. Anonymised queries are not returned by the API.';
COMMENT ON COLUMN public.seo_ga4_daily.events IS
  'Tracked GA4 event counts for the day × source/medium, e.g. {"booking_success": 2, "phone_click": 1}.';
COMMENT ON COLUMN public.seo_places_daily.label IS
  'Stable config label (e.g. "tetmajer") so a listing stays comparable even if its display name changes.';
