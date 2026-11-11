// "Presja" — which project needs attention most (Mapa tab). Pure, unit-tested.
//
//   score = base × blast × status weight
//   base  = vault tasks (by §8 class) + pain points + open blueprint gaps
//         + GitHub issues + runtime (error patterns 24 h, failed CI, deploy down)
//   blast = 1 + perDependent × projects that transitively depend_on this one
//
// Every part is returned so the UI shows why a project ranks where it does.
// It suggests, QUEUE.md decides. Weights live in one place to tune by eye.

import { countPain, countTasks, type TaskCounts } from './vault-tasks.ts';

export const WEIGHTS = {
  red: 4,
  money: 2,
  otherClassed: 1,
  unclassed: 0.25,
  pain: 2,
  gap: 1,
  gapCap: 15,
  bug: 3,
  issue: 1,
  errorPattern: 2,
  ciFailed: 5,
  down: 5,
  perDependent: 0.25,
  status: { hot: 1, warm: 0.7, stalled: 0.8, dormant: 0.3 },
  excludedVerdicts: ['archiwum', 'usunięty', 'scalany'],
};

export interface PressureInput {
  slug: string;
  title: string | null;
  status: string | null;
  raw_frontmatter: Record<string, unknown> | null;
  now_md: string | null;
  next_md: string | null;
  pain_md: string | null;
  repo_meta: Record<string, unknown> | null;
}

export interface Runtime {
  errorPatterns: Map<string, number>;
  down: Set<string>;
}

export interface PressureRow {
  slug: string;
  title: string;
  status: string | null;
  verdict: string | null;
  stream: string | null;
  health: string | null;
  score: number;
  base: number;
  blast: number;
  statusWeight: number;
  dependents: string[];
  parts: {
    tasks: TaskCounts & { points: number };
    pain: { n: number; points: number };
    gaps: { n: number; ids: string[]; points: number; hasBlueprint: boolean };
    issues: { open: number; bugs: number; points: number };
    runtime: { errorPatterns: number; ciFailed: boolean; down: boolean; points: number };
  };
}

const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);
const round1 = (n: number): number => Math.round(n * 10) / 10;

export function projectPressure(p: PressureInput, dependents: string[], rt: Runtime): PressureRow | null {
  const fm = rec(p.raw_frontmatter);
  const verdict = str(fm.verdict);
  if (verdict && WEIGHTS.excludedVerdicts.includes(verdict)) return null;
  const meta = rec(p.repo_meta);
  const W = WEIGHTS;
  const t = countTasks(p.now_md, p.next_md);
  const taskPts = W.red * t.red + W.money * t.money + W.otherClassed * t.other + W.unclassed * t.unclassed;
  const painN = countPain(p.pain_md);
  const gaps = rec(meta.gaps);
  const gapIds = Array.isArray(gaps.ids) ? gaps.ids.filter((x): x is string => typeof x === 'string') : [];
  const gapN = num(gaps.count);
  const issues = rec(meta.issues);
  const bugs = num(issues.bugs);
  const open = num(issues.open);
  const slug = p.slug.toLowerCase();
  const errorPatterns = rt.errorPatterns.get(slug) ?? 0;
  const ciFailed = str(rec(meta.ci).conclusion) === 'failure';
  const down = rt.down.has(slug);
  const runtimePts = W.errorPattern * errorPatterns + (ciFailed ? W.ciFailed : 0) + (down ? W.down : 0);
  const parts = {
    tasks: { ...t, points: taskPts },
    pain: { n: painN, points: W.pain * painN },
    gaps: { n: gapN, ids: gapIds, points: W.gap * Math.min(gapN, W.gapCap), hasBlueprint: !!meta.gaps },
    issues: { open, bugs, points: W.bug * bugs + W.issue * Math.max(0, open - bugs) },
    runtime: { errorPatterns, ciFailed, down, points: runtimePts },
  };
  const base = Object.values(parts).reduce((s, x) => s + x.points, 0);
  const blast = 1 + W.perDependent * dependents.length;
  const statusWeight = (W.status as Record<string, number | undefined>)[p.status ?? ''] ?? W.status.dormant;
  return {
    slug: p.slug,
    title: p.title || p.slug,
    status: p.status,
    verdict,
    stream: str(fm.stream),
    health: str(fm.health),
    score: round1(base * blast * statusWeight),
    base: round1(base),
    blast,
    statusWeight,
    dependents,
    parts,
  };
}

export function rankPressure(projects: PressureInput[], dependents: Map<string, string[]>, rt: Runtime): PressureRow[] {
  return projects
    .map((p) => projectPressure(p, dependents.get(p.slug.toLowerCase()) ?? [], rt))
    .filter((r): r is PressureRow => r !== null)
    .sort((a, b) => b.score - a.score || a.slug.localeCompare(b.slug));
}
