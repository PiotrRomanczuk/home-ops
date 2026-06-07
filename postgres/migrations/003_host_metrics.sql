-- host_metrics — periodic CPU/mem/GPU samples with process-level attribution
-- Created: 2026-06-07
--
-- Third pillar of home-ops (alongside host_logs and gpu_jobs).
-- See docs/adr/2026-06-07-no-grafana.md for the why behind keeping
-- this in the same Postgres rather than building on Grafana/Prometheus.

CREATE TABLE IF NOT EXISTS public.host_metrics (
  id            bigserial PRIMARY KEY,
  ts            timestamptz NOT NULL DEFAULT now(),
  ingested_at   timestamptz NOT NULL DEFAULT now(),
  host          text        NOT NULL,
  cpu_pct       real,
  cpu_load_1    real,
  mem_pct       real,
  mem_used_mb   int,
  mem_total_mb  int,
  swap_pct      real,
  disk_pct      real,
  net_rx_kbps   real,
  net_tx_kbps   real,
  gpu_pct       real,
  gpu_mem_pct   real,
  gpu_temp_c    int,
  data          jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_host_metrics_ts       ON public.host_metrics (ts DESC);
CREATE INDEX IF NOT EXISTS idx_host_metrics_host_ts  ON public.host_metrics (host, ts DESC);
CREATE INDEX IF NOT EXISTS idx_host_metrics_data_gin ON public.host_metrics USING gin (data);

-- =====================================================================
-- Retention — same 30-day window as host_logs, identical pattern.
-- =====================================================================

CREATE OR REPLACE FUNCTION prune_host_metrics(keep_days int DEFAULT 30)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.host_metrics
    WHERE ts < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;

-- Schedule the prune hourly. cron.schedule is idempotent on jobname.
-- Stagger from the other prunes: host_logs runs at :00, gpu_jobs at :15,
-- host_metrics at :30.
SELECT cron.schedule(
  'prune-host-metrics',
  '30 * * * *',
  $$SELECT prune_host_metrics(30)$$
);
