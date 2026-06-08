/* ============================================================
   logs-api.js — wires the Logs tab to the real /api/logs +
   /api/sources. Filter state lives in the URL fragment; this
   module turns it into query params and keeps a windowed view
   of host_logs rows for the table.
   ============================================================ */

const LOG_FETCH_LIMIT = 300;
const LOG_TAIL_MS = 2000;
const LOG_BUFFER_CAP = 600;

function mapLogRow(r) {
  return {
    id: r.id,
    ts: r.ts,
    host: r.host,
    source: r.source,
    level: r.level,
    msg: r.message,
    data: r.data || {},
  };
}

const Logs = {
  rows: [],
  latestId: 0,
  hosts: [],
  loaded: false,
  loading: false,
  err: null,
  _key: null,
  _tailHandle: null,

  _buildParams(st, opts = {}) {
    const p = new URLSearchParams();
    if (st.host && st.host !== 'all') p.append('host', st.host);
    if (st.source) p.append('source', st.source);
    if (st.level_min) p.set('level_min', st.level_min);
    if (st.grep) p.set('grep', st.grep);
    if (opts.after) p.set('after', String(opts.after));
    else p.set('since_min', String(st.since_min || 60));
    p.set('limit', String(opts.limit || LOG_FETCH_LIMIT));
    return p.toString();
  },

  filterKey(st) {
    return [
      st.host || '',
      st.source || '',
      st.level_min || '',
      st.grep || '',
      st.since_min || '',
    ].join('|');
  },

  async loadFor(st) {
    const key = this.filterKey(st);
    if (this.loading && key === this._key) return;
    this._key = key;
    this.loading = true;
    this.err = null;
    try {
      const r = await window.api('GET', '/api/logs?' + this._buildParams(st));
      this.rows = (r.rows || []).map(mapLogRow);
      this.latestId = r.latest_id || (this.rows[0]?.id ?? 0);
      this.loaded = true;
      // Sync the global now-anchor so relative times in the table read against
      // wall-clock now, not the data.js mock anchor.
      if (window.DB) DB.NOW = new Date();
    } catch (e) {
      this.err = e.message;
    } finally {
      this.loading = false;
    }
    if (window.render) window.render();
  },

  async loadSourcesOnce() {
    if (this.hosts.length) return;
    try {
      const r = await window.api('GET', '/api/sources');
      this.hosts = r.hosts || [];
    } catch { /* swallow — table still works without the source picker */ }
  },

  startTail(st) {
    this.stopTail();
    this._tailHandle = setInterval(() => this._tailTick(st), LOG_TAIL_MS);
  },

  stopTail() {
    if (this._tailHandle) {
      clearInterval(this._tailHandle);
      this._tailHandle = null;
    }
  },

  async _tailTick(st) {
    if (!this.latestId) return;
    try {
      const r = await window.api(
        'GET',
        '/api/logs?' + this._buildParams(st, { after: this.latestId, limit: 500 }),
      );
      const incoming = (r.rows || []).map(mapLogRow);
      if (!incoming.length) return;
      // Server returns ASC when after>0. Unshift each so newest ends up at
      // index 0, preserving the table's newest-first ordering.
      for (const row of incoming) {
        this.rows.unshift(row);
        if (Number(row.id) > this.latestId) this.latestId = Number(row.id);
      }
      if (this.rows.length > LOG_BUFFER_CAP) this.rows.length = LOG_BUFFER_CAP;
      if (window.render) window.render();
    } catch { /* swallow; next tick retries */ }
  },
};

window.Logs = Logs;
