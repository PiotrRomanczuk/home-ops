import { pool } from './db.ts';

// Reads and writes for the review page (migration 033): the documentation
// filed per PR head commit, and the pr-review verdict for that same commit
// (migration 028). Both are keyed by the commit, never by the PR alone, so
// the page cannot show yesterday's documentation for today's code.

export const SECTION_KEY_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
export const MAX_SECTION_MD = 200_000;

export interface PrRef {
  repo: string;
  number: number;
  sha: string;
}

export interface ReviewSection {
  key: string;
  title: string;
  position: number;
  body_md: string | null;
  url: string | null;
  source: string;
}

export interface PrReviewRow {
  verdict: 'ok' | 'zmiany' | 'bloker';
  summary: string;
  findings: Array<Record<string, unknown>>;
  dropped: number;
  comment_url: string | null;
  created_at: string;
}

// `repo#12@<sha>` — the ref pr-decide files (pr_gate.ref_of). A legacy ref
// without a SHA cannot be reviewed: there is no commit to bind the page to.
export function parseRef(ref: string | null): PrRef | null {
  const m = /^([\w.-]+)#(\d+)@([0-9a-f]{7,40})$/.exec(ref ?? '');
  const [, repo, number, sha] = m ?? [];
  return repo && number && sha ? { repo, number: Number(number), sha } : null;
}

export async function getSections(pr: PrRef): Promise<ReviewSection[]> {
  const r = await pool.query(
    `SELECT key, title, position, body_md, url, source FROM public.review_sections
      WHERE repo = $1 AND number = $2 AND head_sha = $3
      ORDER BY position, created_at`,
    [pr.repo, pr.number, pr.sha],
  );
  return r.rows as ReviewSection[];
}

export async function getPrReview(pr: PrRef): Promise<PrReviewRow | null> {
  const r = await pool.query(
    `SELECT verdict, summary, findings, dropped, comment_url, created_at FROM public.pr_reviews
      WHERE repo = $1 AND number = $2 AND head_sha = $3`,
    [pr.repo, pr.number, pr.sha],
  );
  return (r.rows[0] as PrReviewRow | undefined) ?? null;
}

export async function upsertSection(pr: PrRef, s: ReviewSection): Promise<void> {
  await pool.query(
    `INSERT INTO public.review_sections (repo, number, head_sha, key, title, position, body_md, url, source)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
     ON CONFLICT (repo, number, head_sha, key) DO UPDATE
       SET title = EXCLUDED.title, position = EXCLUDED.position, body_md = EXCLUDED.body_md,
           url = EXCLUDED.url, source = EXCLUDED.source, created_at = now()`,
    [pr.repo, pr.number, pr.sha, s.key, s.title, s.position, s.body_md, s.url, s.source],
  );
}

export async function markReviewed(id: number): Promise<void> {
  await pool.query('UPDATE public.decisions SET reviewed_at = coalesce(reviewed_at, now()) WHERE id = $1', [id]);
}
