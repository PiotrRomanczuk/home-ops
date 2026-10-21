/* ============================================================
   today-brief.js — the day brief on "Dziś", folded.
   The brief is 2–4 k chars; mornings need three lines of it.
   `## ` sections become rows: the action sections (Top 3,
   Propozycja, Na jutro, Wniosek) open, the rest closed with a
   count. The open/closed choice per heading survives the 60 s
   re-render (memory) and reloads (localStorage, best effort).
   ============================================================ */

const TB_OPEN_BY_DEFAULT = /top\s*3|propozycj|na jutro|wniosek/i;
const TB_KEY = 'td-brief-open';
const TB_STATE = (() => { try { return JSON.parse(localStorage.getItem(TB_KEY) || '{}'); } catch { return {}; } })();

function tbSave() { try { localStorage.setItem(TB_KEY, JSON.stringify(TB_STATE)); } catch { /* private mode */ } }

/* "intro\n## A\n- x\n## B\n…" → [{ heading: null, body: 'intro' }, { heading: 'A', body: '- x' }, …] */
function tbSplit(md) {
  const out = [];
  let cur = { heading: null, lines: [] };
  for (const line of String(md || '').split('\n')) {
    const m = /^##\s+(.+?)\s*$/.exec(line);
    if (m) { out.push(cur); cur = { heading: m[1], lines: [] }; } else cur.lines.push(line);
  }
  out.push(cur);
  return out
    .map((s) => ({ heading: s.heading, body: s.lines.join('\n').trim() }))
    .filter((s) => s.heading || s.body);
}

const tbItems = (body) => body.split('\n').filter((l) => /^\s{0,1}(?:[-*]|\d+\.)\s/.test(l)).length;

function tbSection(s) {
  const isOpen = s.heading in TB_STATE ? TB_STATE[s.heading] : TB_OPEN_BY_DEFAULT.test(s.heading);
  const n = tbItems(s.body);
  const el = h('details', { class: 'tb-sec', open: isOpen },
    h('summary', { class: 'tb-sum' },
      h('span', { class: 'tb-h' }, s.heading),
      n ? h('span', { class: 'tb-n num' }, String(n)) : null),
    h('div', { class: 'td-md', html: window.MdLite.render(s.body) }));
  el.addEventListener('toggle', () => { TB_STATE[s.heading] = el.open; tbSave(); });
  return el;
}

/* Section for the left column of "Dziś". */
function tdBrief(b) {
  if (!b) {
    return h('section', { class: 'td-sec' },
      h('h2', { class: 'td-h' }, 'Brief'),
      h('div', { class: 'td-empty' }, 'Brak briefu — brief-pull jeszcze nic nie pobrał.'));
  }
  const meta = [
    `${TD_SLOT[b.slot] || b.slot}`,
    b.is_today ? null : `z ${TD_DAY.format(new Date(b.brief_date + 'T12:00:00'))}`,
    b.generated_at ? `${TD_TIME.format(new Date(b.generated_at))}` : null,
  ].filter(Boolean).join(' · ');
  const parts = tbSplit(b.body_md);
  const intro = parts.find((p) => !p.heading);
  return h('section', { class: 'td-sec td-brief' + (b.is_today ? '' : ' stale'), title: `źródła: ${(b.sources || []).join(', ')}` },
    h('h2', { class: 'td-h' }, b.title || 'Brief'),
    h('div', { class: 'td-meta' }, meta),
    intro ? h('div', { class: 'td-md', html: window.MdLite.render(intro.body) }) : null,
    h('div', { class: 'tb-list' }, ...parts.filter((p) => p.heading).map(tbSection)));
}
window.tdBrief = tdBrief;
window.tbSplit = tbSplit;
