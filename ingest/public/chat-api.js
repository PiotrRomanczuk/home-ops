/* ============================================================
   chat-api.js — wires the Chat tab to the real /api/jobs.

   A "conversation" is a chain of gpu_jobs sharing
   payload.conversation_id. Each prompt → one job.

   The generate handler captures `response` and `thinking` only
   on job completion (see scheduler/jobs/generate.py). There's
   no mid-flight streaming endpoint yet, so the UI shows the
   running pill until status flips to a terminal state.
   ============================================================ */

const POLL_MS = 1500;
const FETCH_LIMIT = 200;

// Pure transformation helpers live in chat-pure.js for testability.
// Browser loads chat-pure.js before this file (see index.html).
const { elapsedSec, jobToTurns, groupJobsToConversations } = window.ChatPure;

async function api(method, path, body) {
  const opts = { method, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers = { 'content-type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (r.status === 204) return null;
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}


const NON_TERMINAL = new Set(['queued', 'running', 'paused', 'cancelling']);

const Chat = {
  conversations: [],
  loaded: false,
  loading: false,
  err: null,
  _pollHandle: null,

  async loadAll() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await api('GET', `/api/jobs?limit=${FETCH_LIMIT}`);
      const chatJobs = (j.jobs || []).filter((x) => x.kind === 'generate' || x.kind === 'summarise');
      this.conversations = groupJobsToConversations(chatJobs);
      this.loaded = true;
    } catch (e) {
      this.err = e.message;
    } finally {
      this.loading = false;
    }
    if (window.render) window.render();
    this._kickPolling();
  },

  _kickPolling() {
    if (this._pollHandle) return;
    this._pollHandle = setInterval(() => this._pollActive(), POLL_MS);
  },

  _hasActive() {
    for (const c of this.conversations) if (NON_TERMINAL.has(c.status)) return true;
    return false;
  },

  async _pollActive() {
    if (!this._hasActive()) {
      if (this._pollHandle) { clearInterval(this._pollHandle); this._pollHandle = null; }
      return;
    }
    const ids = [];
    for (const c of this.conversations) {
      for (const t of c.turns) {
        if (t._job_id && NON_TERMINAL.has(t.status)) ids.push(t._job_id);
      }
    }
    let changed = false;
    for (const id of ids) {
      try {
        const r = await api('GET', '/api/jobs/' + id);
        if (r && r.job && this._applyJobUpdate(r.job)) changed = true;
      } catch { /* swallow transient errors; next tick retries */ }
    }
    if (changed && window.render) window.render();
  },

  _applyJobUpdate(job) {
    for (const c of this.conversations) {
      for (const t of c.turns) {
        if (t._job_id !== job.id) continue;
        const before = `${t.status}|${(t.text || '').length}|${(t.thinking || '').length}`;
        const r = job.result || {};
        t.status = job.status;
        if (r.response != null) t.text = r.response;
        else if (r.summary != null) t.text = r.summary;
        if (r.thinking != null) t.thinking = r.thinking;
        if (r.eval_count != null) t.tokens = r.eval_count;
        if (Array.isArray(r.sections)) {
          const p = job.payload || {};
          const total = Array.isArray(p.chunks) ? p.chunks.length : null;
          t.sections_hint = total ? `${r.sections.length}/${total} sections` : `${r.sections.length} sections`;
        }
        t.elapsed = elapsedSec(job);
        if (job.last_error) t.fail_reason = job.last_error;
        t.paused_reason = job.status === 'paused' ? 'gaming on win10 — will resume when GPU idle' : null;
        c.status = job.status;
        c.updated = job.finished_at || job.started_at || job.created_at;
        const after = `${t.status}|${(t.text || '').length}|${(t.thinking || '').length}`;
        return before !== after;
      }
    }
    return false;
  },

  _newConvId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'c-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  },

  async submit({ prompt, model, project, convId, kind }) {
    if (!prompt || !prompt.trim()) return;
    const isNew = !convId;
    const conversation_id = convId || this._newConvId();
    const payload = { prompt, model, conversation_id };
    if (project) payload.project = project;
    if (isNew) payload.title = prompt.slice(0, 40);
    const priority = kind === 'summarise' ? 5 : 10;

    // Optimistic local insert so the UI reflects the queued turn immediately.
    let conv = this.conversations.find((c) => c.id === conversation_id);
    const userTurn = { role: 'user', text: prompt };
    const assistantTurn = {
      role: 'assistant', status: 'queued', model,
      tokens: 0, elapsed: 0, text: '', thinking: null,
      _job_id: null, _pending: true,
    };
    if (!conv) {
      conv = {
        id: conversation_id, title: payload.title, model,
        project: project || null, updated: new Date().toISOString(),
        status: 'queued', turns: [userTurn, assistantTurn],
      };
      this.conversations.unshift(conv);
    } else {
      conv.turns.push(userTurn, assistantTurn);
      conv.status = 'queued';
      conv.updated = new Date().toISOString();
      conv.project = project || conv.project;
      conv.model = model || conv.model;
    }
    if (window.render) window.render();
    if (window.setState) window.setState({ conv: conversation_id });

    try {
      const r = await api('POST', '/api/jobs', { kind, payload, priority });
      const job = r.job;
      assistantTurn._job_id = job.id;
      assistantTurn._pending = false;
      conv.status = job.status;
      this._kickPolling();
    } catch (e) {
      assistantTurn.status = 'failed';
      assistantTurn.fail_reason = 'submit failed: ' + e.message;
      conv.status = 'failed';
      if (window.render) window.render();
    }
  },

  async cancel(jobId) {
    if (!jobId) return;
    // Optimistic flip; poller will reflect server truth either way.
    for (const c of this.conversations) {
      for (const t of c.turns) {
        if (t._job_id === jobId && (t.status === 'running' || t.status === 'queued' || t.status === 'paused')) {
          t.status = t.status === 'running' ? 'cancelling' : 'cancelled';
          c.status = t.status;
          if (window.render) window.render();
          break;
        }
      }
    }
    try { await api('POST', '/api/jobs/' + jobId + '/cancel'); }
    catch { /* swallow; poller catches the truth */ }
  },
};

window.Chat = Chat;
window.api = api;
