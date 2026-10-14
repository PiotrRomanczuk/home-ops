import type { Hono } from 'hono';
import { hasIngestToken, tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { verifyLink } from '../decision-links.ts';
import { confirmPage, errorPage, resultPage } from '../decision-pages.ts';
import {
  answerDecision,
  DECISION_COLS,
  type DecisionRow,
  getDecision,
  linksFor,
  normalizeOptions,
} from '../decisions-store.ts';
import { env } from '../env.ts';

// Decisions inbox (migration 021). Routines file questions with the ingest
// token; Piotr answers from the console, the API, or a signed link in the
// digest email (/d/...). Signed links are only handed out to token callers
// (the digest), never to anonymous console viewers.

const ROUTINE_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const STATES = new Set(['open', 'answered', 'expired', 'all']);
const MAX_QUESTION = 300;
const MAX_REASON = 200;

function withLinks(rows: DecisionRow[], include: boolean) {
  return rows.map((d) => ({ ...d, options: normalizeOptions(d.options), links: include ? linksFor(d) : undefined }));
}

export function registerDecisionsRoutes(app: Hono): void {
  app.use('/api/decisions', viewerOrToken);
  app.use('/api/decisions/*', viewerOrToken);
  app.post('/api/decisions', tokenOnly);
  app.post('/api/decisions/:id/consume', tokenOnly);

  app.get('/api/decisions', async (c) => {
    const state = c.req.query('state') || 'open';
    if (!STATES.has(state)) return c.json({ error: 'state must be open|answered|expired|all' }, 400);
    const routine = c.req.query('routine') || null;
    if (routine && !ROUTINE_RE.test(routine)) return c.json({ error: 'invalid routine' }, 400);
    const limit = Math.min(Number(c.req.query('limit') || 50), 200);
    const r = await pool.query(
      `SELECT ${DECISION_COLS} FROM public.decisions
        WHERE ($1 = 'all' OR public.decision_state(decisions.*) = $1)
          AND ($2::text IS NULL OR routine = $2)
        ORDER BY (answer IS NULL) DESC, created_at DESC
        LIMIT $3`,
      [state, routine, limit],
    );
    return c.json({ decisions: withLinks(r.rows as DecisionRow[], hasIngestToken(c)) });
  });

  app.post('/api/decisions', async (c) => {
    const b = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const routine = typeof b.routine === 'string' ? b.routine : '';
    if (!ROUTINE_RE.test(routine)) return c.json({ error: 'routine required (slug-like)' }, 400);
    const question = typeof b.question === 'string' ? b.question.trim() : '';
    if (!question || question.length > MAX_QUESTION)
      return c.json({ error: `question required (1..${MAX_QUESTION})` }, 400);
    const options = normalizeOptions(b.options === undefined ? ['yes', 'no'] : b.options);
    if (options.length < 2 || options.length > 4) return c.json({ error: 'options: 2..4 slug-like keys' }, 400);
    const slug = b.slug == null ? null : String(b.slug);
    if (slug !== null && !ROUTINE_RE.test(slug)) return c.json({ error: 'invalid slug' }, 400);
    const contextUrl = b.context_url == null ? null : String(b.context_url);
    if (contextUrl !== null && !/^https?:\/\//.test(contextUrl))
      return c.json({ error: 'context_url must be http(s)' }, 400);
    const detail = typeof b.detail === 'string' ? b.detail.slice(0, 4000) : null;
    const ref = b.ref == null ? null : String(b.ref).slice(0, 120);
    const parentId = b.parent_id == null ? null : Number(b.parent_id);
    if (parentId !== null && !Number.isInteger(parentId)) return c.json({ error: 'invalid parent_id' }, 400);
    const expiresHours = b.expires_hours === undefined ? 72 : Number(b.expires_hours);
    if (!Number.isFinite(expiresHours) || expiresHours < 1 || expiresHours > 24 * 30) {
      return c.json({ error: 'expires_hours must be 1..720' }, 400);
    }
    const r = await pool.query(
      `INSERT INTO public.decisions (routine, slug, question, detail, context_url, options, ref, parent_id, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, now() + make_interval(hours => $9::int))
       RETURNING ${DECISION_COLS}`,
      [routine, slug, question, detail, contextUrl, JSON.stringify(options), ref, parentId, expiresHours],
    );
    return c.json({ decision: withLinks(r.rows as DecisionRow[], true)[0] }, 201);
  });

  app.post('/api/decisions/:id/answer', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const b = (await c.req.json().catch(() => ({}))) as { option?: unknown; reason?: unknown };
    const option = typeof b.option === 'string' ? b.option : '';
    const reason = typeof b.reason === 'string' ? b.reason.trim().slice(0, MAX_REASON) || null : null;
    const res = await answerDecision(id, option, reason, hasIngestToken(c) ? 'api' : 'console');
    if (!res.ok) return c.json({ error: res.error, decision: res.decision }, res.code);
    return c.json({ decision: res.decision });
  });

  // The routine acknowledges it acted on the answer.
  app.post('/api/decisions/:id/consume', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const r = await pool.query(
      `UPDATE public.decisions SET consumed_at = now()
        WHERE id = $1 AND answer IS NOT NULL AND consumed_at IS NULL RETURNING ${DECISION_COLS}`,
      [id],
    );
    if (r.rowCount === 0) return c.json({ error: 'not answered or already consumed' }, 409);
    return c.json({ decision: r.rows[0] });
  });

  // Signed links from the email. GET only shows a confirmation; POST records.
  const verified = (c: { req: { param: (k: string) => string } }) =>
    verifyLink(env.DECISION_SECRET, {
      id: c.req.param('id'),
      option: c.req.param('option'),
      exp: c.req.param('exp'),
      sig: c.req.param('sig'),
    });

  app.get('/d/:id/:option/:exp/:sig', async (c) => {
    const v = verified(c);
    if (!v.ok) return c.html(errorPage(v.reason), 403);
    const d = await getDecision(v.parts.id);
    if (!d) return c.html(errorPage('not-found'), 404);
    if (d.state !== 'open') return c.html(resultPage(d, false, `This decision is ${d.state}.`), 409);
    return c.html(confirmPage(d, v.parts.option));
  });

  app.post('/d/:id/:option/:exp/:sig', async (c) => {
    const v = verified(c);
    if (!v.ok) return c.html(errorPage(v.reason), 403);
    const form = await c.req.parseBody().catch(() => ({}) as Record<string, unknown>);
    const reason = typeof form.reason === 'string' ? form.reason.trim().slice(0, MAX_REASON) || null : null;
    const res = await answerDecision(v.parts.id, v.parts.option, reason, 'link');
    if (res.ok) return c.html(resultPage(res.decision, true, ''));
    if (!res.decision) return c.html(errorPage('not-found'), 404);
    return c.html(resultPage(res.decision, false, res.error), res.code);
  });
}
