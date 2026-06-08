/* ============================================================
   hosts-api.js — wires the Hosts tab to /api/metrics.

   Two reads per refresh:
     GET /api/metrics?latest=1           → one row per emitting host
     GET /api/metrics?host=X&since_min=N → series per host, for sparklines

   Server row shape (postgres jsonb):
     cpu_pct, cpu_load_1, mem_pct, mem_used_mb, mem_total_mb,
     swap_pct, disk_pct, net_rx_kbps, net_tx_kbps,
     gpu_pct, gpu_mem_pct, gpu_temp_c,
     data: { top_cpu, top_mem, gpu_models_loaded, docker_containers }

   The legacy prototype renderer (hosts.js) expects:
     cpu, mem, gpu, disk, net, gpu_temp, gpu_models, top_cpu, *_s

   This module normalises the server shape into the prototype shape so
   hosts.js stays a thin presentation layer.
   ============================================================ */

const HOSTS_REFRESH_MS = 30_000;

const HOST_ROLES = { elitedesk: 'server', win10: 'gpu', rpi: 'monitoring' };

function fmtKbps(kbps) {
  if (kbps == null) return '—';
  if (kbps >= 1024) return (kbps / 1024).toFixed(1) + 'MB/s';
  return kbps.toFixed(1) + 'KB/s';
}

function rowToMetric(row, series) {
  const data = row?.data || {};
  const topCpu = (data.top_cpu || []).slice(0, 5).map((p) => [p.name || '?', +(p.pct || 0), p.pid || 0]);
  const gpuModelsRaw = data.gpu_models_loaded || [];
  const gpuModels = gpuModelsRaw.length
    ? gpuModelsRaw.map((m) => [m.name || m.model || '?', +((m.vram_mb || m.vram || 0) / 1024).toFixed(1)])
    : null;
  return {
    cpu: row?.cpu_pct ?? null,
    mem: row?.mem_pct ?? null,
    gpu: row?.gpu_pct ?? null,
    disk: row?.disk_pct ?? null,
    net: fmtKbps((row?.net_rx_kbps || 0) + (row?.net_tx_kbps || 0)),
    gpu_temp: row?.gpu_temp_c ?? null,
    gpu_models: gpuModels,
    top_cpu: topCpu,
    cpu_s: series.map((s) => s.cpu_pct ?? 0),
    mem_s: series.map((s) => s.mem_pct ?? 0),
    gpu_s: row?.gpu_pct == null ? null : series.map((s) => s.gpu_pct ?? 0),
  };
}

function hostLagSec(row) {
  if (!row?.ts) return null;
  return Math.max(0, Math.round((Date.now() - +new Date(row.ts)) / 1000));
}

const Hosts = {
  latestByHost: {},
  seriesByHost: {},
  rangeMin: 60,
  loaded: false,
  loading: false,
  err: null,
  _refreshHandle: null,

  async loadAll(rangeMin) {
    if (this.loading) return;
    if (rangeMin) this.rangeMin = rangeMin;
    this.loading = true; this.err = null;
    try {
      const latest = await window.api('GET', '/api/metrics?latest=1');
      const latestRows = latest.rows || [];
      this.latestByHost = {};
      for (const r of latestRows) this.latestByHost[r.host] = r;

      const hostIds = latestRows.map((r) => r.host);
      const series = await Promise.all(
        hostIds.map((id) =>
          window
            .api('GET', `/api/metrics?host=${encodeURIComponent(id)}&since_min=${this.rangeMin}&limit=200`)
            .catch(() => ({ rows: [] })),
        ),
      );
      this.seriesByHost = {};
      hostIds.forEach((id, i) => {
        // Server returns DESC; reverse to oldest→newest for sparkline.
        this.seriesByHost[id] = (series[i]?.rows || []).slice().reverse();
      });
      this.loaded = true;
    } catch (e) {
      this.err = e.message;
    } finally {
      this.loading = false;
    }
    if (window.render) window.render();
  },

  byHost(id) {
    const row = this.latestByHost[id];
    const series = this.seriesByHost[id] || [];
    if (!row) return null;
    return rowToMetric(row, series);
  },

  hostsList() {
    const ids = Object.keys(this.latestByHost);
    return ids.map((id) => {
      const row = this.latestByHost[id];
      const fallback = (window.DB?.HOSTS || []).find((h) => h.id === id) || {};
      const lag = hostLagSec(row);
      return {
        id,
        role: HOST_ROLES[id] || fallback.role || 'host',
        up: fallback.up || '—',
        lag: lag ?? fallback.lag ?? 0,
        hd: lag == null ? 'stale' : lag <= 30 ? 'good' : lag <= 120 ? 'warn' : 'stale',
      };
    });
  },

  startRefresh() {
    if (this._refreshHandle) return;
    this._refreshHandle = setInterval(() => this.loadAll(), HOSTS_REFRESH_MS);
  },

  stopRefresh() {
    if (this._refreshHandle) {
      clearInterval(this._refreshHandle);
      this._refreshHandle = null;
    }
  },

  // For the Chat model picker: live VRAM-resident models on the GPU box.
  // [{name, vram}, ...] in GB, or empty list if win10 hasn't reported.
  modelsLoadedOnGpu() {
    const row = this.latestByHost.win10;
    const ml = row?.data?.gpu_models_loaded;
    if (!ml || !ml.length) return [];
    return ml.map((m) => ({ name: m.name || m.model || '?', vram: +((m.vram_mb || m.vram || 0) / 1024).toFixed(1) }));
  },
};

window.Hosts = Hosts;
