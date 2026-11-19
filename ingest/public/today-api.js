/* ============================================================
   today-api.js — wires the "Dziś" tab to GET /api/today.

   One call returns the whole page model: latest day brief,
   open Now tasks (hot/warm projects + Board), problems, hosts,
   open decisions and fresh routine cards. Read-only; refreshed
   every 60 s while the tab is visible.
   ============================================================ */

const TODAY_POLL_MS = 60_000;

const Today = {
  model: null,
  loaded: false,
  loading: false,
  err: null,
  fetchedAt: null,
  _poll: null,

  async load() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      this.model = await window.api('GET', '/api/today');
      this.loaded = true;
      this.fetchedAt = new Date();
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render && window.getState().tab === 'today') window.render();
  },

  /* Badge: open Now tasks across projects. */
  openCount() {
    return (this.model?.tasks || []).reduce((n, g) => n + g.tasks.length, 0);
  },

  startPolling() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (window.getState().tab !== 'today') { this.stopPolling(); return; }
      this.load();
    }, TODAY_POLL_MS);
  },
  stopPolling() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
};
window.Today = Today;
