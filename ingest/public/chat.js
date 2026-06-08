/* ============================================================
   chat.js — primary surface. Wraps gpu_jobs (generate/summarise)
   as a chat UX. Conversation = chain of job rows.
   ============================================================ */

/* tiny markdown: code fences, inline code, **bold**. Escapes HTML. */
function md(s) {
  if (!s) return '';
  const esc = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const blocks = s.split(/```/);
  let out = '';
  blocks.forEach((b, i) => {
    if (i % 2 === 1) {
      const nl = b.indexOf('\n');
      const code = nl >= 0 ? b.slice(nl + 1) : b;
      out += `<pre><code>${esc(code.replace(/\n$/, ''))}</code></pre>`;
    } else {
      let t = esc(b);
      t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
      t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out += t;
    }
  });
  return out;
}
window.md = md;

function statusOf(c) { return c.turns[c.turns.length - 1]?.status || c.status; }

function convRow(c, active) {
  const st = statusOf(c);
  return h('button', { class: 'crow' + (active ? ' on' : ''), onclick: () => { setState({ conv: c.id }); closeSheet(); } },
    h('div', { class: 'crow-top' },
      h('span', { class: 'cd', style: { background: `var(--s-${st})` } }),
      h('span', { class: 'crow-title' }, c.title),
    ),
    h('div', { class: 'crow-meta' },
      h('span', { class: 'm-model' }, c.model),
      h('span', { class: 'grow', style: { flex: '1' } }),
      c.project ? h('span', { class: 'crow-proj' }, c.project) : null,
      h('span', { class: 'num' }, window.__abs ? abs(c.updated) : relShort(c.updated)),
    ),
  );
}

function thinkBlock(turn, streaming) {
  const wrap = h('div', { class: 'think' });
  const chars = turn.thinking ? turn.thinking.length : 0;
  const hd = h('button', { class: 'think-hd', onclick: () => wrap.classList.toggle('open') },
    h('span', { class: 'caret' }, '▶'),
    'thinking',
    h('span', { class: 'tw num' }, `${chars} chars${streaming ? ' · streaming' : ''}`),
  );
  const body = h('div', { class: 'think-body' });
  body.innerHTML = md(turn.thinking || '') + (streaming ? '<span class="cursor"></span>' : '');
  wrap.append(hd, body);
  return wrap;
}

function turnEl(c, turn, idx) {
  const isUser = turn.role === 'user';
  const el = h('div', { class: 'turn ' + (isUser ? 'user' : 'assistant') });
  const hd = h('div', { class: 'turn-hd' },
    h('span', { class: 'turn-who' },
      h('span', { class: 'glyph' }, isUser ? '›' : '◆'),
      isUser ? 'you' : turn.model,
    ),
    h('span', { class: 'grow' }),
  );

  if (!isUser) {
    const st = turn.status;
    hd.append(h('span', { class: 'pill ' + st }, h('span', { class: 'pd' }), st));
    if (st === 'running' || st === 'cancelling' || st === 'done' || st === 'paused') {
      const stat = h('span', { class: 'turn-stat' });
      if (turn.tokens != null) stat.append(h('span', { class: 'num' }, turn.tokens + ' tok'));
      if (turn.elapsed != null) stat.append(h('span', { class: 'num' }, turn.elapsed + 's'));
      hd.append(stat);
    }
    if (st === 'running' || st === 'cancelling') {
      hd.append(h('button', { class: 'cancel-btn', onclick: () => cancelTurn(c, turn) },
        st === 'cancelling' ? '◴ cancelling' : '■ cancel'));
    }
  } else {
    // fork affordance on user turns
    hd.append(h('button', { class: 'iconbtn', title: 'fork conversation from here', style: { padding: '1px 6px', fontSize: '10px' }, onclick: () => forkFrom(c, idx) }, '⑂ fork'));
  }
  el.append(hd);

  if (!isUser && turn.thinking) el.append(thinkBlock(turn, turn.status === 'running'));

  if (turn.status === 'paused' && turn.paused_reason)
    el.append(h('div', { class: 'paused-note' }, '⏸ ', turn.paused_reason));
  if (turn.status === 'failed' && turn.fail_reason)
    el.append(h('div', { class: 'fail-note' }, '✕ ', turn.fail_reason));

  if (turn.text || turn.status === 'running') {
    const body = h('div', { class: 'turn-body' });
    body.innerHTML = md(turn.text || '') + (turn.status === 'running' ? '<span class="cursor"></span>' : '');
    el.append(body);
  }
  return el;
}

function cancelTurn(c, turn) {
  if (turn._job_id) Chat.cancel(turn._job_id);
}

function forkFrom(c, idx) {
  // Local fork: clone turns up to idx as a new conversation. The next submit
  // gets a fresh conversation_id, so the new chain stays independent
  // server-side. The cloned turns have no _job_id and don't poll.
  const nc = {
    id: Chat._newConvId(),
    title: 'fork: ' + c.title,
    model: c.model,
    project: c.project,
    updated: new Date().toISOString(),
    status: 'done',
    turns: c.turns.slice(0, idx + 1).map((t) => ({ ...t, _job_id: null })),
  };
  Chat.conversations.unshift(nc);
  setState({ conv: nc.id });
}

/* ---------- composer ---------- */
let DRAFT = { model: 'qwen3:8b', project: null };
function composer(c) {
  const ta = h('textarea', { class: 'comp-ta', placeholder: 'message qwen3 · / for commands · ⏎ to send, ⇧⏎ newline',
    rows: 1,
    oninput: (e) => { e.target.style.height = 'auto'; e.target.style.height = Math.min(180, e.target.scrollHeight) + 'px'; updateSend(); },
    onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); } },
  });
  const sendBtn = h('button', { class: 'send-btn', disabled: true, onclick: doSend }, 'send ', h('kbd', { style: { borderColor: 'rgba(0,0,0,0.3)', color: '#06101f' } }, '↵'));
  function updateSend() { sendBtn.disabled = !ta.value.trim(); }
  function doSend() {
    const v = ta.value.trim(); if (!v) return;
    // v1: route everything through kind=generate. /summarise and /embed have
    // different payload/result shapes; their handlers are wired separately.
    Chat.submit({
      prompt: v,
      model: DRAFT.model,
      project: DRAFT.project,
      convId: c && c.id ? c.id : null,
      kind: 'generate',
    });
    ta.value = '';
    ta.style.height = 'auto';
    updateSend();
  }

  const modelBtn = pickerModel();
  const projBtn = pickerProject();

  const box = h('div', { class: 'comp-box' }, ta,
    h('div', { class: 'comp-bar' },
      modelBtn, projBtn,
      h('span', { class: 'grow' }),
      h('span', { class: 'comp-hint' }, h('span', { class: 'cmd' }, '/summarise'), h('span', { class: 'cmd' }, '/embed')),
      sendBtn,
    ),
  );
  setTimeout(() => { if (getState().focusComposer) ta.focus(); }, 30);
  return h('div', { class: 'composer' }, box);
}

function pickerModel() {
  const cur = DB.MODELS_LOADED.find(m => m.name === DRAFT.model) || { name: DRAFT.model, vram: 0 };
  const pct = Math.min(100, (cur.vram / 8) * 100);
  const btn = h('button', { class: 'picker-btn' },
    h('span', { class: 'resident', style: { width: '6px', height: '6px', borderRadius: '50%', background: DB.MODELS_LOADED.some(m => m.name === DRAFT.model) ? 'var(--good)' : 'var(--fg-faint)' } }),
    DRAFT.model,
    h('span', { class: 'vbar' }, h('i', { style: { width: pct + '%' } })),
    h('span', { class: 'caret' }, '▲'),
  );
  const wrap = h('div', { class: 'picker' }, btn);
  btn.onclick = () => {
    if ($('.menu', wrap)) { $('.menu', wrap).remove(); return; }
    const m = h('div', { class: 'menu' },
      h('div', { class: 'menu-sec' }, 'resident in vram', h('span', {}, DB.MODELS_LOADED.reduce((a, x) => a + x.vram, 0).toFixed(1) + 'GB')),
      ...DB.MODELS_LOADED.map(mm => h('button', { class: 'menu-item' + (mm.name === DRAFT.model ? ' on' : ''), onclick: () => { DRAFT.model = mm.name; render(); } },
        h('span', { class: 'resident' }), mm.name, h('span', { class: 'ld' }, h('span', { class: 'vbar' }, h('i', { style: { width: (mm.vram / 8 * 100) + '%' } })), mm.vram + 'GB'))),
      h('div', { class: 'menu-sec' }, 'load other…'),
      ...DB.MODEL_LIBRARY.filter(n => !DB.MODELS_LOADED.some(r => r.name === n)).map(n =>
        h('button', { class: 'menu-item', onclick: () => { DRAFT.model = n; render(); } }, h('span', { class: 'ghost' }), n, h('span', { class: 'ld' }, 'load'))),
    );
    wrap.append(m);
    closeOnOutside(m, wrap);
  };
  return wrap;
}

function pickerProject() {
  const btn = h('button', { class: 'picker-btn', title: 'tag conversation with project → writes payload.project' },
    h('span', { style: { color: DRAFT.project ? 'var(--accent)' : 'var(--fg-faint)' } }, '#'),
    DRAFT.project || 'no project',
    h('span', { class: 'caret' }, '▲'),
  );
  const wrap = h('div', { class: 'picker' }, btn);
  btn.onclick = () => {
    if ($('.menu', wrap)) { $('.menu', wrap).remove(); return; }
    const m = h('div', { class: 'menu' },
      h('div', { class: 'menu-sec' }, 'tag → project'),
      h('button', { class: 'menu-item' + (!DRAFT.project ? ' on' : ''), onclick: () => { DRAFT.project = null; render(); } }, h('span', { class: 'ghost' }), 'no project'),
      ...DB.PROJECTS.map(p => h('button', { class: 'menu-item' + (DRAFT.project === p.slug ? ' on' : ''), onclick: () => { DRAFT.project = p.slug; render(); } },
        h('span', { class: 'pd', style: { width: '6px', height: '6px', borderRadius: '50%', background: `var(--p-${p.status})` } }), p.slug)),
    );
    wrap.append(m);
    closeOnOutside(m, wrap);
  };
  return wrap;
}

function closeOnOutside(menu, wrap) {
  const f = (e) => { if (!wrap.contains(e.target)) { menu.remove(); document.removeEventListener('mousedown', f); } };
  setTimeout(() => document.addEventListener('mousedown', f), 0);
}

function closeSheet() { $('.crail')?.classList.remove('sheet-open'); }

/* ---------- empty state ---------- */
const EX = [
  ['debug', 'why is the live tail re-layouting on every append?'],
  ['/summarise', "today's app:guitar-crm errors — common cause?"],
  ['/embed', 'the 4 Now items from home-ops'],
  ['ask', 'exponential backoff with full jitter, vanilla JS'],
];
function emptyState() {
  const wrap = h('div', { class: 'chat-empty' },
    h('div', { class: 'ascii' }, '  ◆ ◆ ◆\n ──┼──┼──\n  qwen3 · local · gaming-aware'),
    h('div', { class: 'heading' }, 'New conversation — runs on wfh, pauses when you game.'),
    h('div', { class: 'examples' }, ...EX.map(([k, t]) =>
      h('button', { class: 'ex-chip', onclick: () => { const ta = $('.comp-ta'); if (ta) { ta.value = (k.startsWith('/') ? k + ' ' : '') + t; ta.dispatchEvent(new Event('input')); ta.focus(); } } },
        h('span', { class: 'k' }, k), t))),
  );
  return wrap;
}

/* ---------- view ---------- */
VIEWS.chat = function (st, main) {
  if (!Chat.loaded && !Chat.loading && !Chat.err) Chat.loadAll();
  const focus = st.chat === 'focus';
  const wrap = h('div', { class: 'chat' + (focus ? ' focus' : '') });

  // rail
  const listKids = Chat.conversations.map(c => convRow(c, String(c.id) === st.conv));
  if (!listKids.length) {
    listKids.push(h('div', { class: 'crail-empty mut', style: { padding: '14px 16px', fontSize: '11.5px' } },
      Chat.loading ? 'loading…' : Chat.err ? '✕ ' + Chat.err : 'no conversations yet'));
  }
  const list = h('div', { class: 'crail-list' }, ...listKids);
  const rail = h('aside', { class: 'crail' },
    h('div', { class: 'crail-hd' },
      h('span', { class: 'lbl' }, 'conversations ', h('span', { class: 'faint num', style: { fontWeight: 400 } }, Chat.conversations.length)),
      h('button', { class: 'crail-new', onclick: () => { setState({ conv: null, focusComposer: 1 }); } }, '+ new'),
    ),
    list,
  );
  wrap.append(rail);

  // conversation pane
  const c = Chat.conversations.find(x => String(x.id) === st.conv);
  const pane = h('section', { class: 'conv' });

  const hd = h('div', { class: 'conv-hd' });
  // mobile sheet toggle
  hd.append(h('button', { class: 'iconbtn mobile-only', onclick: () => $('.crail').classList.toggle('sheet-open'), title: 'conversations' }, '☰'));
  if (c) {
    hd.append(h('span', { class: 'ct-title' }, c.title));
    hd.append(h('span', { class: 'chip' }, c.model));
    if (c.project) hd.append(h('button', { class: 'chip src', onclick: () => setState({ tab: 'projects', slug: c.project, conv: null }) }, '#' + c.project));
  } else {
    hd.append(h('span', { class: 'ct-title' }, 'new conversation'));
  }
  hd.append(h('span', { class: 'grow' }));
  hd.append(h('button', { class: 'iconbtn' + (!focus ? ' on' : ''), onclick: () => setState({ chat: focus ? null : 'split' }), title: 'split view (rail + conversation)' }, '◫ split'));
  hd.append(h('button', { class: 'iconbtn' + (focus ? ' on' : ''), onclick: () => setState({ chat: 'focus' }), title: 'focus view (full-bleed conversation)' }, '▭ focus'));
  pane.append(hd);

  if (c) {
    const turns = h('div', { class: 'turns' }, ...c.turns.map((t, i) => turnEl(c, t, i)));
    pane.append(turns);
    setTimeout(() => { turns.scrollTop = turns.scrollHeight; }, 0);
  } else {
    pane.append(emptyState());
  }
  pane.append(composer(c));
  wrap.append(pane);
  main.append(wrap);
};

/* chat-local keymap: n = new */
window.VIEW_KEYS = window.VIEW_KEYS || {};
window.VIEW_KEYS.chat = (e) => { if (e.key === 'n') setState({ conv: null, focusComposer: 1 }); };
