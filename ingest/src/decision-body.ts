import { normalizeOptions, REVIEW_ROUTINES } from './decisions-store.ts';

// Validation of the body of POST /api/decisions, kept out of the route so the
// route stays a thin handler.

export const ROUTINE_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const MAX_QUESTION = 300;

export interface NewDecision {
  routine: string;
  slug: string | null;
  question: string;
  detail: string | null;
  contextUrl: string | null;
  options: ReturnType<typeof normalizeOptions>;
  ref: string | null;
  parentId: number | null;
  expiresHours: number;
  requiresReview: boolean;
}

export function parseDecisionBody(b: Record<string, unknown>): { error: string } | { value: NewDecision } {
  const routine = typeof b.routine === 'string' ? b.routine : '';
  if (!ROUTINE_RE.test(routine)) return { error: 'routine required (slug-like)' };
  const question = typeof b.question === 'string' ? b.question.trim() : '';
  if (!question || question.length > MAX_QUESTION) return { error: `question required (1..${MAX_QUESTION})` };
  const options = normalizeOptions(b.options === undefined ? ['yes', 'no'] : b.options);
  if (options.length < 2 || options.length > 4) return { error: 'options: 2..4 slug-like keys' };
  const slug = b.slug == null ? null : String(b.slug);
  if (slug !== null && !ROUTINE_RE.test(slug)) return { error: 'invalid slug' };
  const contextUrl = b.context_url == null ? null : String(b.context_url);
  if (contextUrl !== null && !/^https?:\/\//.test(contextUrl)) return { error: 'context_url must be http(s)' };
  const parentId = b.parent_id == null ? null : Number(b.parent_id);
  if (parentId !== null && !Number.isInteger(parentId)) return { error: 'invalid parent_id' };
  const expiresHours = b.expires_hours === undefined ? 72 : Number(b.expires_hours);
  if (!Number.isFinite(expiresHours) || expiresHours < 1 || expiresHours > 24 * 30) {
    return { error: 'expires_hours must be 1..720' };
  }
  return {
    value: {
      routine,
      slug,
      question,
      detail: typeof b.detail === 'string' ? b.detail.slice(0, 4000) : null,
      contextUrl,
      options,
      ref: b.ref == null ? null : String(b.ref).slice(0, 120),
      parentId,
      expiresHours,
      // Merging code is answered from the review page only (migration 033);
      // the server decides for the known routines, not the caller's flag.
      requiresReview: b.requires_review === true || REVIEW_ROUTINES.has(routine),
    },
  };
}
