// ELK layered layout for a GraphSpec: groups are compound nodes, edges may
// cross groups (hierarchyHandling INCLUDE_CHILDREN). Child coordinates come
// back relative to their group — exactly what React Flow's parentId expects.

import type ELK from 'elkjs/lib/elk.bundled.js';
import type { ElkNode } from 'elkjs/lib/elk.bundled.js';
import type { GraphSpec, SpecKind } from './graph';

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const NODE_SIZE: Record<Exclude<SpecKind, 'group'>, { width: number; height: number }> = {
  project: { width: 196, height: 64 },
  external: { width: 196, height: 40 },
};

const ROOT_OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.spacing.nodeNode': '28',
  'elk.layered.spacing.nodeNodeBetweenLayers': '64',
  'elk.spacing.componentComponent': '48',
};
const GROUP_OPTIONS = { 'elk.padding': '[top=44,left=20,bottom=20,right=20]' };

// ELK is ~1.5 MB: loaded on first layout, so the pressure view never pays for it.
let elk: Promise<InstanceType<typeof ELK>> | null = null;
const getElk = () => {
  elk ??= import('elkjs/lib/elk.bundled.js').then(({ default: Elk }) => new Elk());
  return elk;
};

export async function layoutSpec(spec: GraphSpec): Promise<Map<string, Box>> {
  const groups = new Map<string, ElkNode>();
  const roots: ElkNode[] = [];
  for (const n of spec.nodes) {
    if (n.kind !== 'group') continue;
    const g: ElkNode = { id: n.id, layoutOptions: GROUP_OPTIONS, children: [] };
    groups.set(n.id, g);
    roots.push(g);
  }
  for (const n of spec.nodes) {
    if (n.kind === 'group') continue;
    const leaf: ElkNode = { id: n.id, ...NODE_SIZE[n.kind] };
    const parent = n.parent ? groups.get(n.parent) : undefined;
    (parent?.children ?? roots).push(leaf);
  }
  const graph: ElkNode = {
    id: 'root',
    layoutOptions: ROOT_OPTIONS,
    children: roots,
    edges: spec.edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  };
  const out = await (await getElk()).layout(graph);
  const boxes = new Map<string, Box>();
  const walk = (nodes: ElkNode[] | undefined) => {
    for (const n of nodes ?? []) {
      boxes.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, width: n.width ?? 0, height: n.height ?? 0 });
      walk(n.children);
    }
  };
  walk(out.children);
  return boxes;
}
