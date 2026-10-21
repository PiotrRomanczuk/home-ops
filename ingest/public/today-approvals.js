/* ============================================================
   today-approvals.js — "Do akceptacji" on top of "Dziś".
   Everything that waits for Piotr in one block:
   - questions routines filed (decisions), answered in place
     with the same card as the Decisions history view;
   - the brief's "Czeka na merge" section (PRs and branches the
     cloud brief found), taken out of the brief so it is not
     read twice.
   The Decisions tab is off the strip; its history (answered /
   expired) stays reachable from the link here.
   ============================================================ */

const TA_BRIEF_RE = /czeka na merge|do akceptacji/i;

function taBriefPart(b) {
  if (!b) return null;
  return window.tbSplit(b.body_md).find((p) => p.heading && TA_BRIEF_RE.test(p.heading)) || null;
}

function tdApprovals(brief) {
  if (Decisions.state !== 'open') { Decisions.state = 'open'; Decisions.loaded = false; }
  if (!Decisions.loaded && !Decisions.loading && !Decisions.err) Decisions.loadAll();
  const open = Decisions.items.filter((d) => d.state === 'open' || d._pending);
  const part = taBriefPart(brief);
  const nBrief = part ? part.body.split('\n').filter((l) => /^\s{0,1}[-*]\s/.test(l)).length : 0;
  const body = [];
  if (open.length) body.push(h('div', { class: 'ta-decs' }, ...open.map(window.decCard)));
  if (part) {
    body.push(h('div', { class: 'ta-sub', title: 'tekst z briefu, w ciągu dnia się nie odświeża' },
      `${part.heading} · z briefu ${brief.generated_at ? TD_TIME.format(new Date(brief.generated_at)) : ''} · stan z rana`),
      h('div', { class: 'td-md ta-brief', html: window.MdLite.render(part.body) }));
  }
  if (!body.length) body.push(h('div', { class: 'td-empty ok' }, 'Nic nie czeka na Twoją decyzję.'));
  if (Decisions.err) body.push(h('div', { class: 'td-err' }, `decyzje: ${Decisions.err}`));
  return h('section', { class: 'td-sec ta-sec' },
    h('h2', { class: 'td-h' }, 'Do akceptacji',
      open.length + nBrief ? h('span', { class: 'td-ct num' }, String(open.length + nBrief)) : null,
      h('span', { class: 'spacer' }),
      h('button', { class: 'td-link ta-hist', onclick: () => setState({ tab: 'decisions' }) }, 'historia →')),
    ...body);
}
window.tdApprovals = tdApprovals;
window.TA_BRIEF_RE = TA_BRIEF_RE;
