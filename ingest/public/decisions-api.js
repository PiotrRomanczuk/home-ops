/* ============================================================
   decisions-api.js — wires the Decisions tab to /api/decisions.

   The inbox of questions routines filed (migration 020). Answers
   are optimistic with rollback, same pattern as Board. Routines
   consume answers on their next run, so nothing here triggers
   side effects directly.
   ============================================================ */

const DECISIONS_POLL_MS = 30_000;

const Decisions = {
  items: [],
  state: 'open',       // open | answered | expired | all
  loaded: false,
  loading: false,
  err: null,
  _poll: null,

  async loadAll() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await window.api('GET', `/api/decisions?state=${encodeURIComponent(this.state)}&limit=100`);
      this.items = j.decisions || [];
      this.loaded = true;
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render) window.render();
  },

  openCount() { return this.items.filter((d) => d.state === 'open').length; },

  setState(state) {
    if (state === this.state) return;
    this.state = state; this.loaded = false;
    this.loadAll();
  },

  async answer(d, option, reason) {
    const snapshot = { ...d };
    Object.assign(d, { answer: option, reason: reason || null, answered_at: new Date().toISOString(), state: 'answered', _pending: true });
    if (window.render) window.render();
    try {
      const j = await window.api('POST', `/api/decisions/${d.id}/answer`, { option, reason: reason || undefined });
      Object.assign(d, j.decision, { _pending: false });
    } catch (e) {
      Object.assign(d, snapshot, { _pending: false, _err: e.message });
    }
    if (window.render) window.render();
  },

  startPolling() {
    this.stopPolling();
    this._poll = setInterval(() => { if (document.visibilityState === 'visible') this.loadAll(); }, DECISIONS_POLL_MS);
  },
  stopPolling() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
};
window.Decisions = Decisions;
