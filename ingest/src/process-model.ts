// Contract for POST /api/processes/sync (migration 029). planner-sync sends the
// full set of BPMN process notes every tick. Pure (no DB) so it is unit-testable.

export const MAX_PROCESSES = 100;
export const MAX_BPMN_CHARS = 512 * 1024;

export interface ProcessRecord {
  slug: string;
  title: string;
  trigger: string | null;
  schedule: string | null;
  summary: string | null;
  projects: string[];
  lanes: string[];
  bpmn_xml: string | null;
  bpmn_hash: string | null;
  path: string | null;
  warnings: string[];
}

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
const SLUG_RE = /^[\w.-]{1,128}$/;
const strOrNull = (v: unknown, max = 500): string | null | undefined =>
  v == null || v === '' ? null : typeof v === 'string' && v.length <= max ? v : undefined;
const strList = (v: unknown, max = 50): string[] | undefined =>
  v == null
    ? []
    : Array.isArray(v) && v.length <= max && v.every((x) => typeof x === 'string' && x.length <= 500)
      ? v
      : undefined;

function parseOne(r: unknown, i: number): ProcessRecord | string {
  if (!isRec(r) || typeof r.slug !== 'string' || !SLUG_RE.test(r.slug)) return `process ${i}: invalid slug`;
  const title = strOrNull(r.title) ?? r.slug;
  const [trigger, schedule, summary, path, hash] = [r.trigger, r.schedule, r.summary, r.path, r.bpmn_hash].map((v) =>
    strOrNull(v),
  );
  const xml = strOrNull(r.bpmn_xml, MAX_BPMN_CHARS);
  if ([trigger, schedule, summary, path, hash].includes(undefined)) return `process ${i}: invalid text field`;
  if (xml === undefined) return `process ${i}: bpmn_xml too large or not a string`;
  const projects = strList(r.projects);
  const lanes = strList(r.lanes);
  const warnings = strList(r.warnings);
  if (!projects || !lanes || !warnings) return `process ${i}: projects/lanes/warnings must be string arrays`;
  return {
    slug: r.slug,
    title: title as string,
    trigger: trigger ?? null,
    schedule: schedule ?? null,
    summary: summary ?? null,
    projects,
    lanes,
    bpmn_xml: xml,
    bpmn_hash: hash ?? null,
    path: path ?? null,
    warnings,
  };
}

export function parseProcessesBody(body: unknown): ProcessRecord[] | string {
  if (!isRec(body) || !Array.isArray(body.processes)) return 'processes must be an array';
  if (body.processes.length > MAX_PROCESSES) return `at most ${MAX_PROCESSES} processes`;
  const out: ProcessRecord[] = [];
  const seen = new Set<string>();
  for (const [i, raw] of body.processes.entries()) {
    const rec = parseOne(raw, i);
    if (typeof rec === 'string') return rec;
    if (seen.has(rec.slug)) return `process ${i}: duplicate slug ${rec.slug}`;
    seen.add(rec.slug);
    out.push(rec);
  }
  return out;
}
