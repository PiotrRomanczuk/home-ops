/* ============================================================
   decisions.js — Decisions tab: the approval inbox.
   One card per question a routine filed. Answer with one tap;
   a rejection asks for a one-line reason (that reason is the
   acceptance signal the digest reports per routine).
   ============================================================ */

const DEC_STATES = ['open', 'answered', 'expired', 'all'];
const DEC_NO_RE = /^(no|reject|skip|decline)$/i;

/* rel() only looks backwards; deadlines need 'in 5h' / 'in 2d'. */
function decUntil(t) {
  const s = Math.round((new Date(t) - Date.now()) / 1000);
  if (s <= 0) return 'now';
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))}m`;
  if (s < 86400) return `in ${Math.round(s / 3600)}h`;
  return `in ${Math.round(s / 86400)}d`;
}

function decFilterBar() {
  return h('div', { class: 'dec-filters' },
    ...DEC_STATES.map((s) => h('button', {
      class: 'dec-filter' + (Decisions.state === s ? ' on' : ''),
      onclick: () => Decisions.setState(s),
    }, s)),
    h('span', { class: 'spacer' }),
    h('span', { class: 'dec-hint' }, 'Routines pick answers up on their next run.'),
  );
}

function decAnswerForm(d) {
  let chosen = null;
  const reason = h('input', { class: 'dec-reason', placeholder: 'reason (required for no)', maxlength: 200 });
  const submit = () => {
    if (!chosen) return;
    const r = reason.value.trim();
    if (DEC_NO_RE.test(chosen) && !r) { reason.classList.add('bad'); reason.focus(); return; }
    Decisions.answer(d, chosen, r);
  };
  const buttons = (d.options || []).map((o) => h('button', {
    class: 'dec-opt' + (DEC_NO_RE.test(o.key) ? ' no' : ''),
    title: o.consequence || '',
    onclick: () => {
      chosen = o.key;
      if (DEC_NO_RE.test(o.key) && !reason.value.trim()) { reason.classList.add('bad'); reason.focus(); return; }
      submit();
    },
  }, o.label));
  reason.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (!chosen) chosen = 'no'; submit(); } });
  reason.addEventListener('input', () => reason.classList.remove('bad'));
  return h('div', { class: 'dec-answer' }, ...buttons, reason);
}

function decCard(d) {
  const isOpen = d.state === 'open';
  const when = isOpen ? `expires ${decUntil(d.expires_at)}` : d.answered_at ? `answered ${rel(d.answered_at)}` : `expired ${rel(d.expires_at)}`;
  const meta = h('div', { class: 'dec-meta' },
    h('span', { class: 'dec-routine' }, d.routine),
    d.slug ? h('span', { class: 'dec-slug' }, d.slug) : null,
    h('span', { class: 'dec-when' }, when),
    d.answered_via ? h('span', { class: 'dec-via' }, `via ${d.answered_via}`) : null,
  );
  const outcome = !isOpen && d.answer
    ? h('div', { class: 'dec-outcome ' + (DEC_NO_RE.test(d.answer) ? 'no' : 'yes') },
        (d.options || []).find((o) => o.key === d.answer)?.label || d.answer, d.reason ? h('span', { class: 'dec-why' }, ` · ${d.reason}`) : null)
    : !isOpen ? h('div', { class: 'dec-outcome expired' }, 'expired, no answer') : null;
  return h('article', { class: 'dec-card' + (d._pending ? ' pending' : '') + (isOpen ? '' : ' closed') },
    meta,
    h('div', { class: 'dec-q' }, d.question),
    d.detail ? h('pre', { class: 'dec-detail' }, d.detail) : null,
    d.context_url ? h('a', { class: 'dec-ctx', href: d.context_url, target: '_blank', rel: 'noopener' }, 'open context →') : null,
    d._err ? h('div', { class: 'dec-err' }, d._err) : null,
    isOpen ? decAnswerForm(d) : outcome,
  );
}

VIEWS.decisions = (st, main) => {
  if (!Decisions.loaded && !Decisions.loading) Decisions.loadAll();
  Decisions.startPolling();
  const list = Decisions.items;
  main.append(h('div', { class: 'dec-view' },
    decFilterBar(),
    Decisions.err ? h('div', { class: 'dec-err' }, Decisions.err) : null,
    list.length
      ? h('div', { class: 'dec-list' }, ...list.map(decCard))
      : h('div', { class: 'empty' }, Decisions.loaded ? `no ${Decisions.state === 'all' ? '' : Decisions.state + ' '}decisions` : 'loading…'),
  ));
};
