import type { Context, Hono } from 'hono';
import { hasViewerAuth, tokenOnly } from '../auth.ts';
import { errorPage, resultPage } from '../decision-pages.ts';
import { answerDecision, type DecisionRow, getDecision, NO_RE } from '../decisions-store.ts';
import { env } from '../env.ts';
import { requiredKeys, reviewPage } from '../review-page.ts';
import {
  getPrReview,
  getSections,
  MAX_SECTION_MD,
  markReviewed,
  type PrRef,
  parseRef,
  SECTION_KEY_RE,
  sectionsVersion,
  upsertSection,
} from '../review-store.ts';
import { checkReviewToken, issueReviewToken } from '../review-token.ts';

// Review page for decisions that merge code (migration 033).
//
//   POST /api/reviews/sections  routines and CI file documentation for a PR head commit (token)
//   GET  /review/:id            the page: decision, pr-review verdict, every filed section
//   POST /review/:id            the answer — only with the page's token and every section opened

const MAX_SECTIONS = 20;

const isViewer = (c: Context) => env.AUTH_PUBLIC || hasViewerAuth(c);

async function render(c: Context, d: DecisionRow, pr: PrRef, error?: string, status: 200 | 400 | 409 = 200) {
  const [sections, review] = await Promise.all([getSections(pr), getPrReview(pr)]);
  const token = issueReviewToken(env.DECISION_SECRET, Number(d.id), pr.sha, sectionsVersion(sections));
  return c.html(reviewPage({ d, pr, sections, review, token, error }), status);
}

async function loadOpen(c: Context): Promise<Response | { d: DecisionRow; pr: PrRef }> {
  const id = Number(c.req.param('id'));
  const d = Number.isInteger(id) ? await getDecision(id) : null;
  if (!d) return c.html(errorPage('not-found'), 404);
  if (d.state !== 'open') return c.html(resultPage(d, false, `This decision is ${d.state}.`), 409);
  const pr = parseRef(d.ref);
  if (!pr) return c.html(errorPage('malformed'), 400);
  return { d, pr };
}

function cleanSection(raw: unknown, source: string) {
  const s = (raw ?? {}) as Record<string, unknown>;
  const key = typeof s.key === 'string' ? s.key : '';
  const title = typeof s.title === 'string' ? s.title.trim().slice(0, 120) : '';
  const body = typeof s.body_md === 'string' ? s.body_md.slice(0, MAX_SECTION_MD) : null;
  const url = typeof s.url === 'string' && /^https?:\/\//.test(s.url) ? s.url : null;
  if (!SECTION_KEY_RE.test(key) || !title || (!body && !url)) return null;
  const position = Number.isInteger(s.position) ? Number(s.position) : 100;
  return { key, title, position, body_md: body, url, source };
}

export function registerReviewRoutes(app: Hono): void {
  app.post('/api/reviews/sections', tokenOnly);
  app.post('/api/reviews/sections', async (c) => {
    const b = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const pr = parseRef(`${b.repo}#${b.number}@${b.head_sha}`);
    const source = typeof b.source === 'string' && SECTION_KEY_RE.test(b.source) ? b.source : '';
    if (!pr || !source) return c.json({ error: 'repo, number, head_sha (hex) and source required' }, 400);
    const raw = Array.isArray(b.sections) ? b.sections : [];
    const sections = raw.map((s) => cleanSection(s, source));
    if (!raw.length || raw.length > MAX_SECTIONS || sections.some((s) => !s)) {
      return c.json({ error: `sections: 1..${MAX_SECTIONS} of {key, title, body_md | url}` }, 400);
    }
    for (const s of sections) if (s) await upsertSection(pr, s);
    return c.json({ saved: sections.length }, 201);
  });

  app.get('/review/:id', async (c) => {
    if (!isViewer(c)) return c.redirect('/login');
    const loaded = await loadOpen(c);
    if (loaded instanceof Response) return loaded;
    await markReviewed(Number(loaded.d.id));
    return render(c, loaded.d, loaded.pr);
  });

  app.post('/review/:id', async (c) => {
    if (!isViewer(c)) return c.redirect('/login');
    const loaded = await loadOpen(c);
    if (loaded instanceof Response) return loaded;
    const { d, pr } = loaded;
    const form = (await c.req.parseBody().catch(() => ({}))) as Record<string, unknown>;
    const field = (k: string) => (typeof form[k] === 'string' ? (form[k] as string).trim() : '');
    const option = field('option');
    const reason = field('reason').slice(0, 200) || null;

    // One read serves the token's version and the opened-keys check, so a
    // section re-filed meanwhile cannot slip between them.
    const sections = await getSections(pr);
    const tok = checkReviewToken(env.DECISION_SECRET, field('token'), Number(d.id), pr.sha, sectionsVersion(sections));
    if (!tok.ok) {
      const msg = 'Strona wygasła albo nie pasuje do tego commitu lub jego dokumentacji (sekcje się zmieniły)';
      return render(c, d, pr, `${msg} — przejrzyj ją jeszcze raz.`, 409);
    }
    const opened = new Set(field('opened').split(',').filter(Boolean));
    const missing = requiredKeys(sections).filter((k) => !opened.has(k));
    if (missing.length) return render(c, d, pr, `Nierozwinięte sekcje: ${missing.join(', ')}.`, 409);
    if (NO_RE.test(option) && !reason) return render(c, d, pr, 'Przy odrzuceniu podaj powód.', 400);

    const res = await answerDecision(Number(d.id), option, reason, 'review');
    if (res.ok) return c.html(resultPage(res.decision, true, ''));
    return res.decision ? render(c, d, pr, res.error, 400) : c.html(errorPage('not-found'), 404);
  });
}
