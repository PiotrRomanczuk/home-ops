/* ============================================================
   today-queue.js — the "Kolejka" card on the "Dziś" tab.
   Renders queue_state (vault QUEUE.md mirrored by planner-sync):
   window + capacity bar, the ticket in progress, the next three,
   and one line of counts. Read-only; the vault stays the editor.
   ============================================================ */

const TQ_CLASS = { risk: 'ryzyko', money: 'przychód', focus: 'fokus', clean: 'higiena', idea: 'pomysł' };
const TQ_FLAG = { unblocks: 'odblokowuje', local: 'lokalny', paused: 'wstrzymany', experiment: 'eksperyment' };
const TQ_BUDGET_H = { S: 1, M: 3, L: 8, XL: 8 };
const TQ_NEXT = 3;
const TQ_DATE = new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'numeric' });

const tqHours = (n) => `${String(Math.round(n * 10) / 10).replace('.', ',')} h`;
const tqDay = (iso) => (iso ? TQ_DATE.format(new Date(`${iso}T12:00:00`)) : '?');

function tqChips(t) {
  return [
    t.cls ? h('span', { class: `tq-chip tq-c-${t.cls}` }, TQ_CLASS[t.cls] || t.cls) : null,
    t.size ? h('span', { class: 'tq-chip tq-size' }, t.size) : null,
    ...(t.flags || []).map((f) => h('span', { class: 'tq-chip' }, TQ_FLAG[f] || f)),
  ];
}

function tqRow(t, cls) {
  return h('li', { class: `tq-row ${cls || ''}`, title: t.brief || '' },
    ...tqChips(t),
    h('span', { class: 'tq-text' },
      t.project ? h('span', { class: 'tq-proj' }, `${t.project} `) : null,
      t.id ? h('b', {}, `${t.id} `) : null,
      t.text.replace(/`/g, '')),
    t.model ? h('span', { class: 'tq-meta' }, t.model) : null);
}

function tqBar(q, inProgress) {
  const cap = q.capacity_hours || 0;
  const used = q.summary?.done_hours || 0;
  const budget = inProgress.reduce((n, t) => n + (TQ_BUDGET_H[t.size] || 0), 0);
  if (!cap) return null;
  const pct = (n) => `${Math.min(100, Math.round((n / cap) * 100))}%`;
  return h('div', { class: 'tq-cap' },
    h('div', { class: 'tq-bar' },
      h('i', { class: 'used', style: { width: pct(used) } }),
      h('i', { class: 'budget', style: { width: pct(budget) } })),
    h('div', { class: 'tq-cap-l' },
      h('span', {}, `zrobione ${tqHours(used)}${budget ? ` · w toku do ${tqHours(budget)}` : ''}`),
      h('span', {}, `pojemność ${tqHours(cap)} · napełniaj do ${tqHours(cap * 0.7)}`)));
}

/* Section for the right column of "Dziś"; null until planner-sync has synced once. */
function tdQueue(q) {
  if (!q) return null;
  const s = q.sections || {};
  const inProgress = (s.in_progress || []).filter((t) => !t.done);
  const next = (s.queue || []).filter((t) => !t.done).slice(0, TQ_NEXT);
  const counts = [
    `czeka na Piotra: ${(s.waiting || []).filter((t) => !t.done).length}`,
    `tor lokalny: ${(s.local || []).filter((t) => !t.done).length}`,
    `zrobione w oknie: ${(s.done || []).length}`,
  ].join(' · ');
  const rows = [
    ...inProgress.map((t) => tqRow(t, 'wip')),
    inProgress.length ? null : h('li', { class: 'tq-row tq-empty' }, 'nic w toku — następny bilet z kolejki:'),
    ...next.map((t) => tqRow(t)),
  ].filter(Boolean);
  return h('section', { class: 'td-sec tq' },
    h('h2', { class: 'td-h' }, 'Kolejka',
      h('span', { class: 'td-ct num' }, `${inProgress.length} w toku`),
      h('span', { class: 'spacer' }),
      h('span', { class: 'td-meta' }, `okno ${tqDay(q.window_from)} → ${tqDay(q.window_to)}${q.focus ? ` · fokus ${q.focus}` : ''}`)),
    tqBar(q, inProgress),
    rows.length ? h('ul', { class: 'tq-list' }, ...rows) : h('div', { class: 'td-empty' }, 'Kolejka pusta.'),
    h('div', { class: 'td-meta' }, counts));
}
window.tdQueue = tdQueue;
