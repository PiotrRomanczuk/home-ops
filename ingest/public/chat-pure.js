/* ============================================================
   chat-pure.js — pure helpers for chat-api.js.

   No fetch, no setInterval, no window state. Side-effect-free
   functions that transform job rows ↔ conversation turns. Lives
   in a separate file so vitest can import + test without dragging
   in the browser-only Chat singleton.

   Surface (exposed via globalThis.ChatPure for chat-api.js):
     elapsedSec(job)              → integer seconds since started_at
     jobToTurns(job)              → [userTurn, assistantTurn] objects
     groupJobsToConversations(jobs) → conversation[] sorted by updated DESC

   Browser loads this BEFORE chat-api.js via <script>.
   Tests do `import './chat-pure.js'` then read globalThis.ChatPure.
   ============================================================ */

(() => {
  function elapsedSec(job) {
    if (!job.started_at) return 0;
    const start = +new Date(job.started_at);
    const end = job.finished_at ? +new Date(job.finished_at) : Date.now();
    return Math.max(0, Math.round((end - start) / 1000));
  }

  function jobToTurns(job) {
    const p = job.payload || {};
    const r = job.result || {};
    // generate returns {response, thinking}; summarise returns {summary, sections}.
    const text = r.response || r.summary || '';
    const sections = Array.isArray(r.sections) ? r.sections : null;
    const totalChunks = Array.isArray(p.chunks) ? p.chunks.length : null;
    const sectionsHint = sections && totalChunks ? `${sections.length}/${totalChunks} sections` : null;
    // Cron-queued summarise jobs have no human prompt — fall back to title.
    const userText = p.prompt || p.title || (totalChunks ? `summarise ${totalChunks} chunks` : '');
    return [
      { role: 'user', text: userText },
      {
        role: 'assistant',
        status: job.status,
        model: p.model || 'unknown',
        tokens: r.eval_count ?? 0,
        elapsed: elapsedSec(job),
        started: job.started_at,
        thinking: r.thinking || null,
        text,
        sections_hint: sectionsHint,
        fail_reason: job.last_error || null,
        paused_reason: job.status === 'paused' ? 'gaming on win10 — will resume when GPU idle' : null,
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

  // Expose for chat-api.js (browser) AND for vitest (no window).
  const target = typeof window !== 'undefined' ? window : globalThis;
  target.ChatPure = { elapsedSec, jobToTurns, groupJobsToConversations };
})();
