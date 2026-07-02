/* ============================================================
   evals-api.js — wires the Evals board to /api/eval_tasks.

   Cards live in eval_tasks (server-side, authoritative for what
   eval-tick runs). Stage moves are optimistic with rollback, same
   pattern as the Projects task toggle. Results stats come joined
   from the server (eval_scores via rationale = name).
   ============================================================ */

const EVAL_STAGES = ['idea', 'building', 'testing', 'active', 'paused', 'retired'];
const EVAL_POLL_MS = 60_000; // ticks are 6-hourly; a lazy poll is plenty

const Evals = {
  items: [],
  loaded: false,
  loading: false,
  err: null,
  _poll: null,

  async loadAll() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await window.api('GET', '/api/eval_tasks');
      this.items = j.tasks || [];
      this.loaded = true;
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render) window.render();
  },

  byId(id) {
    return this.items.find((t) => t.id === Number(id)) || null;
  },

  async create(name, kind, notes) {
    const j = await window.api('POST', '/api/eval_tasks', { name, kind, notes });
    if (j.task) this.items.push(j.task);
    if (window.render) window.render();
    return j.task;
  },

  async setStage(item, stage) {
    const prev = item.stage;
    item.stage = stage;            // optimistic
    item._pending = true;
    if (window.render) window.render();
    try {
      const j = await window.api('POST', `/api/eval_tasks/${item.id}/stage`, { stage });
      Object.assign(item, j.task, { _pending: false });
    } catch (e) {
      item.stage = prev;           // rollback
      item._pending = false;
      item._error = e.message || 'stage move failed';
      setTimeout(() => { delete item._error; if (window.render) window.render(); }, 3500);
    }
    if (window.render) window.render();
  },

  async update(item, patch) {
    const j = await window.api('POST', `/api/eval_tasks/${item.id}/update`, patch);
    Object.assign(item, j.task);
    if (window.render) window.render();
  },

  async loadScores(item) {
    if (item._scoresLoading) return;
    item._scoresLoading = true;
    try {
      const j = await window.api('GET', `/api/eval_tasks/${item.id}/scores`);
      item._scores = j.scores || [];
    } catch { item._scores = []; }
    finally { item._scoresLoading = false; }
    if (window.render) window.render();
  },

  startPoll() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if ((window.getState?.() || {}).tab === 'evals') this.loadAll();
      else this.stopPoll();
    }, EVAL_POLL_MS);
  },

  stopPoll() {
    if (this._poll) { clearInterval(this._poll); this._poll = null; }
  },
};

window.Evals = Evals;
window.EVAL_STAGES = EVAL_STAGES;
