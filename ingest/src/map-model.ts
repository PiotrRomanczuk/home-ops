import { asList } from './vault-links.ts';

// GET /api/map — the project ecosystem as a graph. Pure (no DB), unit-tested.
//
// Source of truth is the vault frontmatter mirrored into projects.raw_frontmatter:
//   depends_on: [[x]]  → this project stops working when x is down (blast radius)
//   feeds:      [[x]]  → this project sends data / logs / leads to x
//   hosts:      [uwh]  → where it runs
// A target that is not a project note (ollama, instagram-api…) becomes an
// "external" node. Older planner-sync builds sent lists as one string, so
// both shapes are accepted.

export type NodeKind = 'project' | 'external' | 'host';
export type EdgeKind = 'depends_on' | 'feeds' | 'runs_on';

export interface MapProjectRow {
  slug: string;
  title: string | null;
  status: string | null;
  raw_frontmatter: Record<string, unknown> | null;
}

export interface MapProcessRow {
  slug: string;
  title: string;
  lanes: string[];
  warnings: unknown;
}

export interface MapNode {
  id: string;
  kind: NodeKind;
  label: string;
  status: string | null;
  verdict: string | null;
  health: string | null;
  stream: string | null;
  summary: string | null;
  hosts: string[];
  /** Everything that transitively depends_on this node (who breaks if it goes down). */
  dependents: string[];
  /** Pressure score (pressure-model.ts); null for external / host nodes. */
  pressure: number | null;
}

export interface MapEdge {
  from: string;
  to: string;
  kind: EdgeKind;
}

export interface MapResponse {
  nodes: MapNode[];
  edges: MapEdge[];
  processes: Array<{ slug: string; title: string; lanes: string[]; warnings: string[] }>;
}

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);

function blankNode(id: string, kind: NodeKind, label: string): MapNode {
  return {
    id,
    kind,
    label,
    status: null,
    verdict: null,
    health: null,
    stream: null,
    summary: null,
    hosts: [],
    dependents: [],
    pressure: null,
  };
}

/** Reverse BFS over depends_on: node → every node that (transitively) needs it. */
export function dependentsOf(edges: MapEdge[]): Map<string, string[]> {
  const needs = new Map<string, string[]>(); // target → direct dependents
  for (const e of edges) if (e.kind === 'depends_on') needs.set(e.to, [...(needs.get(e.to) ?? []), e.from]);
  const out = new Map<string, string[]>();
  for (const start of needs.keys()) {
    const seen = new Set<string>([start]);
    const queue = [start];
    for (let cur = queue.shift(); cur !== undefined; cur = queue.shift()) {
      for (const d of needs.get(cur) ?? []) {
        if (seen.has(d)) continue;
        seen.add(d);
        queue.push(d);
      }
    }
    seen.delete(start);
    out.set(start, [...seen].sort());
  }
  return out;
}

export function buildMap(projects: MapProjectRow[], processes: MapProcessRow[] = []): MapResponse {
  const nodes = new Map<string, MapNode>();
  for (const p of projects) {
    const fm = p.raw_frontmatter ?? {};
    const id = p.slug.toLowerCase();
    nodes.set(id, {
      ...blankNode(id, 'project', p.title || p.slug),
      status: p.status,
      verdict: str(fm.verdict),
      health: str(fm.health),
      stream: str(fm.stream),
      summary: str(fm.summary),
      hosts: asList(fm.hosts),
    });
  }
  const edges: MapEdge[] = [];
  const seen = new Set<string>();
  const add = (from: string, to: string, kind: EdgeKind, make: () => MapNode) => {
    if (from === to || seen.has(`${from}>${to}>${kind}`)) return;
    seen.add(`${from}>${to}>${kind}`);
    if (!nodes.has(to)) nodes.set(to, make());
    edges.push({ from, to, kind });
  };
  for (const p of projects) {
    const fm = p.raw_frontmatter ?? {};
    const id = p.slug.toLowerCase();
    for (const kind of ['depends_on', 'feeds'] as const)
      for (const t of asList(fm[kind])) add(id, t, kind, () => blankNode(t, 'external', t));
    for (const h of asList(fm.hosts)) add(id, `host:${h}`, 'runs_on', () => blankNode(`host:${h}`, 'host', h));
  }
  const deps = dependentsOf(edges);
  for (const n of nodes.values()) n.dependents = deps.get(n.id) ?? [];
  return {
    nodes: [...nodes.values()].sort((a, b) => a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id)),
    edges,
    processes: processes.map((p) => ({
      slug: p.slug,
      title: p.title,
      lanes: p.lanes.map((l) => l.toLowerCase()),
      warnings: Array.isArray(p.warnings) ? p.warnings.filter((w): w is string => typeof w === 'string') : [],
    })),
  };
}
