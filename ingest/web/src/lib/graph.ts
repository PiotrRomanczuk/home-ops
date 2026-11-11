// Turns GET /api/map into what each view draws. Pure, unit-tested.
//   ecosystem — projects grouped by `stream`, externals in their own group,
//               depends_on + feeds edges (UML-component-like)
//   infra     — projects inside their primary host, depends_on edges
//               (UML-deployment-like)
// Quiet projects (dormant / archived / idea) are hidden unless a relation
// still ties them to the rest — job-radar's dependency on olx-scraper stays.

import type { MapEdge, MapNode, MapResponse } from './api';

export type SpecKind = 'project' | 'external' | 'group';

export interface NodeSpec {
  id: string;
  kind: SpecKind;
  label: string;
  parent: string | null;
  node: MapNode | null;
}

export interface EdgeSpec {
  id: string;
  source: string;
  target: string;
  kind: 'depends_on' | 'feeds';
}

export interface GraphSpec {
  nodes: NodeSpec[];
  edges: EdgeSpec[];
}

/** Where code is written, not where it runs — never a "primary" host. */
export const WORK_PLACES = new Set(['mac', 'github']);
const SERVER_ORDER = ['uwh', 'wfh', 'rpi', 'nas', 'vercel'];
const QUIET_VERDICTS = new Set(['archiwum', 'usunięty', 'scalany', 'pomysł']);
export const EXTERNAL_GROUP = 'group:zewnętrzne';

export const isQuiet = (n: MapNode): boolean =>
  n.kind === 'project' && (n.status === 'dormant' || QUIET_VERDICTS.has(n.verdict ?? ''));

const relations = (map: MapResponse): MapEdge[] => map.edges.filter((e) => e.kind !== 'runs_on');

export function visibleIds(map: MapResponse, showQuiet: boolean): Set<string> {
  const connected = new Set(relations(map).flatMap((e) => [e.from, e.to]));
  const ids = new Set<string>();
  for (const n of map.nodes) {
    if (n.kind === 'host') continue;
    if (n.kind === 'external' && !connected.has(n.id)) continue;
    if (n.kind === 'project' && !showQuiet && isQuiet(n) && !connected.has(n.id)) continue;
    ids.add(n.id);
  }
  return ids;
}

export function primaryHost(n: MapNode): string {
  return (
    SERVER_ORDER.find((h) => n.hosts.includes(h)) ??
    n.hosts.find((h) => !WORK_PLACES.has(h)) ??
    n.hosts[0] ??
    'bez hosta'
  );
}

function assemble(
  map: MapResponse,
  showQuiet: boolean,
  groupOf: (n: MapNode) => { id: string; label: string } | null,
  kinds: EdgeSpec['kind'][],
): GraphSpec {
  const ids = visibleIds(map, showQuiet);
  const groups = new Map<string, NodeSpec>();
  const leaves: NodeSpec[] = [];
  for (const n of map.nodes) {
    if (!ids.has(n.id)) continue;
    const g = n.kind === 'external' ? { id: EXTERNAL_GROUP, label: 'usługi zewnętrzne' } : groupOf(n);
    if (g && !groups.has(g.id)) groups.set(g.id, { id: g.id, kind: 'group', label: g.label, parent: null, node: null });
    leaves.push({
      id: n.id,
      kind: n.kind === 'external' ? 'external' : 'project',
      label: n.label,
      parent: g?.id ?? null,
      node: n,
    });
  }
  const edges = map.edges
    .filter((e): e is MapEdge & { kind: EdgeSpec['kind'] } => (kinds as string[]).includes(e.kind))
    .filter((e) => ids.has(e.from) && ids.has(e.to))
    .map((e) => ({ id: `${e.from}>${e.to}>${e.kind}`, source: e.from, target: e.to, kind: e.kind }));
  // React Flow wants parents before their children.
  return { nodes: [...groups.values(), ...leaves], edges };
}

export const ecosystemSpec = (map: MapResponse, showQuiet: boolean): GraphSpec =>
  assemble(map, showQuiet, (n) => (n.stream ? { id: `group:${n.stream}`, label: n.stream } : null), [
    'depends_on',
    'feeds',
  ]);

export const infraSpec = (map: MapResponse, showQuiet: boolean): GraphSpec =>
  assemble(
    map,
    showQuiet,
    (n) => {
      const h = primaryHost(n);
      return { id: `host:${h}`, label: h };
    },
    ['depends_on'],
  );

/** What lights up when something is selected: the node, its direct relations
 *  and everyone who breaks with it. A host selects everything running there. */
export function impactOf(map: MapResponse, id: string): Set<string> {
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  const out = new Set<string>([id]);
  const addWithDependents = (nid: string) => {
    out.add(nid);
    for (const d of byId.get(nid)?.dependents ?? []) out.add(d);
  };
  if (id.startsWith('host:')) {
    // A server takes down everything that lists it; mac/github only their own group.
    const host = id.slice(5);
    const runsThere = (n: MapNode) => (WORK_PLACES.has(host) ? primaryHost(n) === host : n.hosts.includes(host));
    for (const n of map.nodes) if (n.kind === 'project' && runsThere(n)) addWithDependents(n.id);
    return out;
  }
  addWithDependents(id);
  for (const e of relations(map)) {
    if (e.from === id) out.add(e.to);
    if (e.to === id) out.add(e.from);
  }
  return out;
}

export interface Relations {
  dependsOn: string[];
  feeds: string[];
  fedBy: string[];
  neededBy: string[];
}

export function relationsOf(map: MapResponse, id: string): Relations {
  const r: Relations = { dependsOn: [], feeds: [], fedBy: [], neededBy: [] };
  for (const e of relations(map)) {
    if (e.from === id) (e.kind === 'depends_on' ? r.dependsOn : r.feeds).push(e.to);
    if (e.to === id) (e.kind === 'depends_on' ? r.neededBy : r.fedBy).push(e.from);
  }
  return r;
}
