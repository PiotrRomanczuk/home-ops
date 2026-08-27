/* ============================================================
   eval-scores-api.js — wires the Scores tab to /api/eval_scores.

   Read-only scoreboard for the strummy_eval_* harness (local-LLM
   reconstruction runs on the 7700 XT, 6h eval-tick). Separate data
   source from the Evals board — that manages eval_tasks lifecycle;
   this only reads strummy_eval_scores results. Lazy 60s poll while
   the tab is open (ticks are 6-hourly, no need to hammer).
   ============================================================ */

const SCORES_POLL_MS = 60_000;

const EvalScores = {
  available: true,
  matrix: [],
  recent: [],
  overall: null,
  config: null,
  loaded: false,
  loading: false,
  err: null,
  _poll: null,

  async load() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await window.api('GET', '/api/eval_scores');
      this.available = j.available !== false;
      this.matrix = j.matrix || [];
      this.recent = j.recent || [];
      this.overall = j.overall || null;
      this.config = j.config || null;
      this.loaded = true;
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render) window.render();
  },

  startPoll() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if ((window.getState?.() || {}).tab === 'scores') this.load();
      else this.stopPoll();
    }, SCORES_POLL_MS);
  },

  stopPoll() {
    if (this._poll) { clearInterval(this._poll); this._poll = null; }
  },
};

window.EvalScores = EvalScores;
