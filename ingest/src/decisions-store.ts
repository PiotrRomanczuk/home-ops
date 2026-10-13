import { pool } from './db.ts';
import { buildLink, isValidOption } from './decision-links.ts';
import { env } from './env.ts';

// Shared read/write helpers for decisions (migration 020), used by the JSON
// API, the signed-link pages and the digest model. Keeps the "what counts as
// a valid answer" rule in one place.

export const DECISION_COLS = `id, routine, slug, question, detail, context_url, options, ref, parent_id,
  created_at, expires_at, answer, reason, answered_at, answered_via, consumed_at,
  public.decision_state(decisions.*) AS state`;

export interface DecisionOption {
  key: string;
  label: string;
  consequence?: string;
}

export interface DecisionRow {
  id: string | number;
  routine: string;
  slug: string | null;
  question: string;
  detail: string | null;
  context_url: string | null;
  options: unknown;
  ref: string | null;
  parent_id: string | number | null;
  created_at: string;
  expires_at: string;
  answer: string | null;
  reason: string | null;
  answered_at: string | null;
  answered_via: string | null;
  consumed_at: string | null;
  state: 'open' | 'answered' | 'expired';
}

// Options may be stored as ["yes","no"] or [{key,label,consequence}].
export function normalizeOptions(raw: unknown): DecisionOption[] {
  if (!Array.isArray(raw)) return [];
  const out: DecisionOption[] = [];
  for (const o of raw) {
    if (typeof o === 'string' && isValidOption(o)) out.push({ key: o, label: o });
    else if (o && typeof o === 'object') {
      const { key, label, consequence } = o as Record<string, unknown>;
      if (typeof key === 'string' && isValidOption(key)) {
        out.push({
          key,
          label: typeof label === 'string' && label ? label : key,
          consequence: typeof consequence === 'string' ? consequence : undefined,
        });
      }
    }
  }
  return out;
}

export function linksFor(d: DecisionRow): Record<string, string> {
  const exp = Math.floor(new Date(d.expires_at).getTime() / 1000);
  const out: Record<string, string> = {};
  for (const o of normalizeOptions(d.options)) {
    out[o.key] = buildLink(env.DECISION_SECRET, env.PUBLIC_BASE_URL, { id: Number(d.id), option: o.key, exp });
  }
  return out;
}

export async function getDecision(id: number): Promise<DecisionRow | null> {
  const r = await pool.query(`SELECT ${DECISION_COLS} FROM public.decisions WHERE id = $1`, [id]);
  return (r.rows[0] as DecisionRow | undefined) ?? null;
}

export type AnswerResult =
  | { ok: true; decision: DecisionRow }
  | { ok: false; code: 404 | 409 | 400; error: string; decision?: DecisionRow };

// Records an answer exactly once. A second tap on an already-answered link
// is a 409 with the existing row, so the confirmation page can say "already
// answered: yes at 07:12" instead of silently overwriting.
export async function answerDecision(
  id: number,
  option: string,
  reason: string | null,
  via: 'link' | 'console' | 'api',
): Promise<AnswerResult> {
  const cur = await getDecision(id);
  if (!cur) return { ok: false, code: 404, error: 'not found' };
  if (!normalizeOptions(cur.options).some((o) => o.key === option)) {
    return { ok: false, code: 400, error: 'option not offered', decision: cur };
  }
  if (cur.state !== 'open') return { ok: false, code: 409, error: `decision is ${cur.state}`, decision: cur };
  const r = await pool.query(
    `UPDATE public.decisions
        SET answer = $2, reason = $3, answered_at = now(), answered_via = $4
      WHERE id = $1 AND answer IS NULL AND expires_at >= now()
      RETURNING ${DECISION_COLS}`,
    [id, option, reason, via],
  );
  if (r.rowCount === 0) {
    const again = await getDecision(id);
    return { ok: false, code: 409, error: 'decision already closed', decision: again ?? cur };
  }
  return { ok: true, decision: r.rows[0] as DecisionRow };
}
