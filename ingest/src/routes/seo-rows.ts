// Row validation + upsert SQL for POST /api/seo/ingest, one entry per source
// table (migration 017). Kept apart from the route so each kind's contract is
// readable in one place: required fields, column order, conflict target.

export type SeoKind = 'gsc' | 'ga4' | 'places';

interface KindSpec {
  table: string;
  columns: string[];
  conflict: string[];
  validate: (r: Record<string, unknown>) => string | null;
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

const isText = (v: unknown, max = 2048): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const isCount = (v: unknown): v is number => Number.isInteger(v) && (v as number) >= 0;
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isDay = (v: unknown): v is string => typeof v === 'string' && DAY_RE.test(v);

export const SPECS: Record<SeoKind, KindSpec> = {
  gsc: {
    table: 'seo_gsc_daily',
    columns: ['site', 'day', 'query', 'page', 'clicks', 'impressions', 'ctr', 'position'],
    conflict: ['site', 'day', 'query', 'page'],
    validate: (r) => {
      if (!isText(r.site, 256) || !isDay(r.day)) return 'invalid site/day';
      if (!isText(r.query) || !isText(r.page)) return 'invalid query/page';
      if (!isCount(r.clicks) || !isCount(r.impressions)) return 'invalid clicks/impressions';
      if (!isNum(r.ctr) || !isNum(r.position)) return 'invalid ctr/position';
      return null;
    },
  },
  ga4: {
    table: 'seo_ga4_daily',
    columns: ['site', 'day', 'source_medium', 'sessions', 'users', 'events'],
    conflict: ['site', 'day', 'source_medium'],
    validate: (r) => {
      if (!isText(r.site, 256) || !isDay(r.day) || !isText(r.source_medium, 512))
        return 'invalid site/day/source_medium';
      if (!isCount(r.sessions) || !isCount(r.users)) return 'invalid sessions/users';
      if (r.events !== undefined && (typeof r.events !== 'object' || r.events === null || Array.isArray(r.events)))
        return 'invalid events';
      return null;
    },
  },
  places: {
    table: 'seo_places_daily',
    columns: ['place_id', 'day', 'label', 'name', 'is_self', 'rating', 'review_count'],
    conflict: ['place_id', 'day'],
    validate: (r) => {
      if (!isText(r.place_id, 512) || !isDay(r.day)) return 'invalid place_id/day';
      if (!isText(r.label, 64) || !isText(r.name, 512)) return 'invalid label/name';
      if (r.rating !== null && r.rating !== undefined && !isNum(r.rating)) return 'invalid rating';
      if (r.review_count !== null && r.review_count !== undefined && !isCount(r.review_count))
        return 'invalid review_count';
      return null;
    },
  },
};

export function isSeoKind(k: unknown): k is SeoKind {
  // hasOwn, not `in` — `'toString' in SPECS` is true via the prototype.
  return typeof k === 'string' && Object.hasOwn(SPECS, k);
}

function cell(col: string, r: Record<string, unknown>): unknown {
  if (col === 'events') return JSON.stringify(r.events ?? {});
  if (col === 'is_self') return r.is_self === true;
  return r[col] ?? null;
}

/** Multi-row INSERT … ON CONFLICT DO UPDATE for one chunk of validated rows. */
export function buildUpsert(kind: SeoKind, rows: Record<string, unknown>[]): { sql: string; params: unknown[] } {
  const spec = SPECS[kind];
  const params: unknown[] = [];
  const tuples = rows.map((r) => {
    const ph = spec.columns.map((col) => {
      params.push(cell(col, r));
      return col === 'events' ? `$${params.length}::jsonb` : `$${params.length}`;
    });
    return `(${ph.join(', ')})`;
  });
  const updates = spec.columns
    .filter((c) => !spec.conflict.includes(c))
    .map((c) => `${c} = EXCLUDED.${c}`)
    .concat('fetched_at = now()');
  const sql = `INSERT INTO public.${spec.table} (${spec.columns.join(', ')}) VALUES ${tuples.join(', ')}
    ON CONFLICT (${spec.conflict.join(', ')}) DO UPDATE SET ${updates.join(', ')}`;
  return { sql, params };
}
