/* ============================================================
   progress-api.js — wires the Postęp tab to GET /api/progress:
   12 weekly columns per project (GitHub, vault ticks, routines).
   The data moves every few hours, so it refreshes every 5 min
   while the tab is visible.
   ============================================================ */

const PROGRESS_POLL_MS = 300_000;

const Progress = {
  model: null,      // { weeks: [...], projects: [{ slug, series, stalled, ... }] }
  loaded: false,
  loading: false,
  err: null,
  fetchedAt: null,
  _poll: null,

  async load() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      this.model = await window.api('GET', '/api/progress?weeks=12');
      this.loaded = true;
      this.fetchedAt = new Date();
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render && window.getState().tab === 'progress') window.render();
  },

  /* Badge: hot projects that have not moved for 14 days. */
  stalledCount() { return (this.model?.projects || []).filter((p) => p.stalled).length; },

  startPolling() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (window.getState().tab !== 'progress') { this.stopPolling(); return; }
      this.load();
    }, PROGRESS_POLL_MS);
  },
  stopPolling() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
};
window.Progress = Progress;
