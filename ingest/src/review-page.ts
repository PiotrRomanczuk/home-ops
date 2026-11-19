import { type DecisionRow, NO_RE, normalizeOptions } from './decisions-store.ts';
import { REVIEW_CSS, REVIEW_JS } from './review-page-assets.ts';
import type { PrRef, PrReviewRow, ReviewSection } from './review-store.ts';

// The one place where a person answers a decision that merges code. Every
// section must be expanded before the buttons unlock (review-page-assets.ts);
// the pr-review verdict for this exact commit is always the first section.

export const PR_REVIEW_KEY = 'pr-review';

export interface ReviewPageModel {
  d: DecisionRow;
  pr: PrRef;
  sections: ReviewSection[];
  review: PrReviewRow | null;
  token: string | null;
  error?: string;
}

/** Every section key the person has to open before answering. */
export function requiredKeys(sections: ReviewSection[]): string[] {
  return [PR_REVIEW_KEY, ...sections.map((s) => s.key)];
}

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** "1 uwaga", "3 uwagi", "5 uwag" — Polish plural for the findings count. */
function findingsCount(n: number): string {
  const few = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14);
  return `${n} ${n === 1 ? 'uwaga' : few ? 'uwagi' : 'uwag'}`;
}

function section(key: string, title: string, source: string, inner: string): string {
  return `<details class="sec" data-key="${esc(key)}"><summary>${esc(title)} <span class="src">${esc(source)}</span></summary>${inner}</details>`;
}

function reviewSection(review: PrReviewRow | null): string {
  if (!review) {
    return section(
      PR_REVIEW_KEY,
      'Recenzja pr-review',
      'brak',
      '<p><span class="verdict none">brak recenzji tego commitu</span></p>',
    );
  }
  const findings = (review.findings ?? [])
    .map((f) => {
      const where = f.file ? `<b>${esc(f.file)}${f.line ? `:${esc(f.line)}` : ''}</b> · ` : '';
      const fix = f.suggestion ? `<br>→ ${esc(f.suggestion)}` : '';
      return `<div class="finding ${esc(f.severity)}">${where}${esc(f.problem)}${fix}</div>`;
    })
    .join('');
  const link = review.comment_url
    ? `<p><a href="${esc(review.comment_url)}" target="_blank" rel="noopener">komentarz na GitHubie →</a></p>`
    : '';
  const dropped = review.dropped ? ` · odrzucone przez weryfikację: ${review.dropped}` : '';
  return section(
    PR_REVIEW_KEY,
    'Recenzja pr-review',
    `${findingsCount(review.findings?.length ?? 0)}${dropped}`,
    `<p><span class="verdict ${esc(review.verdict)}">${esc(review.verdict)}</span> ${esc(review.summary)}</p>${findings}${link}`,
  );
}

function filedSection(s: ReviewSection): string {
  const body = s.body_md ? `<pre class="md-src">${esc(s.body_md)}</pre>` : '';
  const link = s.url ? `<p><a href="${esc(s.url)}" target="_blank" rel="noopener">otwórz →</a></p>` : '';
  return section(s.key, s.title, s.source, body + link);
}

export function reviewPage(m: ReviewPageModel): string {
  const { d, pr } = m;
  const options = normalizeOptions(d.options)
    .map(
      (o) =>
        `<button name="option" value="${esc(o.key)}" class="${NO_RE.test(o.key) ? 'no' : ''}" title="${esc(o.consequence ?? '')}" disabled>${esc(o.label)}</button>`,
    )
    .join('');
  const detail = d.detail ? `<pre>${esc(d.detail)}</pre>` : '';
  const ctx = d.context_url
    ? `<p><a href="${esc(d.context_url)}" target="_blank" rel="noopener">PR na GitHubie →</a></p>`
    : '';
  const error = m.error ? `<p class="err">${esc(m.error)}</p>` : '';
  const total = requiredKeys(m.sections).length;
  const answer =
    m.token === null
      ? '<div class="card answer"><p>Żeby podjąć decyzję, zaloguj się do konsoli i otwórz tę stronę ponownie.</p><p><a href="/login">Zaloguj →</a></p></div>'
      : `<form id="answer" class="card answer" method="post">${error}
<p>Przejrzane sekcje: <b id="seen">0/${total}</b> — przyciski odblokują się po rozwinięciu każdej.</p>
<input type="hidden" name="token" value="${esc(m.token)}"><input type="hidden" name="opened" value="">
<input name="reason" maxlength="200" placeholder="powód / notatka (wymagany przy odrzuceniu)" autocomplete="off">
<div class="btns">${options}</div></form>`;
  return `<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Przegląd: ${esc(d.question)}</title>
<style>${REVIEW_CSS}</style><script src="/static/md-lite.js"></script></head><body><div class="wrap">
<div class="card"><div class="eyebrow">${esc(d.routine)} · ${esc(pr.repo)} #${pr.number} · commit ${esc(pr.sha.slice(0, 7))}</div>
<h1>${esc(d.question)}</h1>${detail}${ctx}</div>
<div class="card">${reviewSection(m.review)}${m.sections.map(filedSection).join('')}</div>
${answer}
</div><script>${REVIEW_JS}</script></body></html>`;
}
