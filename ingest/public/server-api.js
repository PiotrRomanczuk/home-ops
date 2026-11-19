/* ============================================================
   server-api.js — wires the Serwer tab (and the Dziś card) to
   /api/activity/*: the latest "right now" snapshot + 24 h summary,
   the run list for the chosen range, and one run's log on demand.
   Refreshed every 15 s while the tab is visible.
   ============================================================ */

const SERVER_POLL_MS = 15_000;

const Server = {
  now: null,        // { hosts: [{host, ts, snapshot}], summary_24h }
  runs: [],
  rangeH: 24,
  logs: {},         // run id → log_tail (fetched once, on expand)
  loaded: false,
  loading: false,
  err: null,
  fetchedAt: null,
  _poll: null,

  snapshot() { return this.now?.hosts?.[0] || null; },

  async loadNow() {
    try { this.now = await window.api('GET', '/api/activity/now'); } catch (e) { this.err = e.message; }
  },

  async load() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const [now, runs] = await Promise.all([
        window.api('GET', '/api/activity/now'),
        window.api('GET', `/api/activity/runs?since_h=${this.rangeH}&limit=3000`),
      ]);
      this.now = now;
      this.runs = runs.runs || [];
      this.loaded = true;
      this.fetchedAt = new Date();
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render && window.getState().tab === 'server') window.render();
  },

  setRange(hours) {
    if (hours === this.rangeH) return;
    this.rangeH = hours;
    this.load();
  },

  async loadLog(id) {
    if (this.logs[id]) return;
    this.logs[id] = { loading: true };
    try {
      const r = await window.api('GET', `/api/activity/runs/${id}`);
      this.logs[id] = { lines: r.run?.log_tail || [] };
    } catch (e) { this.logs[id] = { err: e.message }; }
    window.render();
  },

  /* Badge: units failing in the last 24 h. */
  failingCount() { return this.now?.summary_24h?.failing_units?.length || 0; },

  startPolling() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (window.getState().tab !== 'server') { this.stopPolling(); return; }
      this.load();
    }, SERVER_POLL_MS);
  },
  stopPolling() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
};
window.Server = Server;
