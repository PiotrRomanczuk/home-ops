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

function elapsedSec(job) {
  if (!job.started_at) return 0;
  const start = +new Date(job.started_at);
  const end = job.finished_at ? +new Date(job.finished_at) : Date.now();
  return Math.max(0, Math.round((end - start) / 1000));
}

function jobToTurns(job) {
  const p = job.payload || {};
  const r = job.result || {};
  return [
    { role: 'user', text: p.prompt || '' },
    {
      role: 'assistant',
      status: job.status,
      model: p.model || 'unknown',
      tokens: r.eval_count ?? 0,
      elapsed: elapsedSec(job),
      started: job.started_at,
      thinking: r.thinking || null,
      text: r.response || '',
      fail_reason: job.last_error || null,
      paused_reason: job.status === 'paused' ? 'gaming on wfh — will resume when GPU idle' : null,
      _job_id: job.id,
    },
  ];
}

function groupJobsToConversations(jobs) {
  const groups = new Map();
  for (const job of jobs) {
    const key = (job.payload && job.payload.conversation_id) || `job-${job.id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(job);
  }
  const convs = [];
  for (const [key, js] of groups) {
    js.sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
    const first = js[0];
    const last = js[js.length - 1];
    const fp = first.payload || {};
    const lp = last.payload || {};
    convs.push({
      id: key,
      title: fp.title || (fp.prompt || '').slice(0, 40) || `job ${first.id}`,
      model: lp.model || fp.model || 'qwen3:8b',
      project: fp.project || lp.project || null,
      updated: last.finished_at || last.started_at || last.created_at,
      status: last.status,
      turns: js.flatMap(jobToTurns),
    });
  }
  convs.sort((a, b) => +new Date(b.updated) - +new Date(a.updated));
  return convs;
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
        if (r.thinking != null) t.thinking = r.thinking;
        if (r.eval_count != null) t.tokens = r.eval_count;
        t.elapsed = elapsedSec(job);
        if (job.last_error) t.fail_reason = job.last_error;
        t.paused_reason = job.status === 'paused' ? 'gaming on wfh — will resume when GPU idle' : null;
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
