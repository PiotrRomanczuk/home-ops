/* ============================================================
   status-api.js — wires the Status tab to GET /api/status.
   One request per refresh; the endpoint aggregates everything.
   ============================================================ */

const STATUS_REFRESH_MS = 15_000;

const Status = {
  snap: null, // last /api/status payload
  loaded: false,
  loading: false,
  err: null,
  _refreshHandle: null,

  async load() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      this.snap = await window.api('GET', '/api/status');
      this.loaded = true;
    } catch (e) {
      this.err = e.message;
    } finally {
      this.loading = false;
    }
    if (window.render) window.render();
  },

  // seconds since a host's last event / metric, or null if never seen
  lagSec(ts) {
    if (!ts) return null;
    const nowMs = this.snap?.now ? +new Date(this.snap.now) : Date.now();
    return Math.max(0, Math.round((nowMs - +new Date(ts)) / 1000));
  },

  // 'good' | 'warn' | 'stale' — worst of event-lag and metric-lag
  hostHealth(row) {
    const m = this.lagSec(row.last_metric_ts);
    // metrics sample every 30s: <=90s good, <=5m warn, else stale
    if (m == null) return 'stale';
    return m <= 90 ? 'good' : m <= 300 ? 'warn' : 'stale';
  },

  alarmCount() {
    const lv = this.snap?.levels_1h || {};
    return (lv.error || 0) + (lv.fatal || 0);
  },

  startRefresh() {
    if (this._refreshHandle) return;
    this._refreshHandle = setInterval(() => this.load(), STATUS_REFRESH_MS);
  },

  stopRefresh() {
    if (this._refreshHandle) {
      clearInterval(this._refreshHandle);
      this._refreshHandle = null;
    }
  },
};

window.Status = Status;
