// Tolerant date coercion for vault frontmatter in POST /api/projects/sync.
// The vault is hand-edited: `last_commit: 2026-09-27 (080f85a)` or a bare
// hash `efaf7a9` used to abort the whole sync transaction (Postgres `date`
// cast) and froze every project for a week (2026-10-10 → 10-17). One bad
// field must cost that field, not the sync — so we coerce and warn instead.

export interface DateField {
  value: string | null;
  warning: string | null;
}

const LEADING_DATE_RE = /^\s*(\d{4})-(\d{2})-(\d{2})(?!\d)/;

function isRealDate(y: number, m: number, d: number): boolean {
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

/** `date` column: keep a leading YYYY-MM-DD, else NULL with a warning. */
export function coerceDate(raw: unknown, field: string, slug: string): DateField {
  if (raw === undefined || raw === null || raw === '') return { value: null, warning: null };
  const s = String(raw);
  const m = LEADING_DATE_RE.exec(s);
  if (m && isRealDate(Number(m[1]), Number(m[2]), Number(m[3]))) {
    const value = `${m[1]}-${m[2]}-${m[3]}`;
    const trimmed = s.trim();
    // Postgres accepts a full ISO timestamp for a date; only flag real junk.
    const isClean = trimmed === value || /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(trimmed);
    return { value, warning: isClean ? null : `${slug}: ${field} "${s.slice(0, 60)}" trimmed to ${value}` };
  }
  return { value: null, warning: `${slug}: ${field} "${s.slice(0, 60)}" is not a date, stored NULL` };
}

/** `timestamptz` column: anything Date.parse understands, else NULL (→ now()). */
export function coerceTimestamp(raw: unknown, field: string, slug: string): DateField {
  if (raw === undefined || raw === null || raw === '') return { value: null, warning: null };
  const s = String(raw);
  if (/^\d{4}-\d{2}-\d{2}/.test(s.trim()) && !Number.isNaN(Date.parse(s))) return { value: s, warning: null };
  return { value: null, warning: `${slug}: ${field} "${s.slice(0, 60)}" is not a timestamp, ignored` };
}
