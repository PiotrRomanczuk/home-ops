// GraphSpec + ELK boxes + current selection → React Flow nodes and edges.
// Dimming and selection are plain data flags; the node components turn them
// into Tailwind classes.

import { type Edge, MarkerType, type Node } from '@xyflow/react';
import type { MapNode } from './api';
import type { GraphSpec } from './graph';
import type { Box } from './layout';

export interface LeafData extends Record<string, unknown> {
  node: MapNode;
  isDimmed: boolean;
  isSelected: boolean;
}

export interface ClusterData extends Record<string, unknown> {
  label: string;
  isHost: boolean;
  isDimmed: boolean;
  isSelected: boolean;
}

export type ProjectFlowNode = Node<LeafData, 'project'>;
export type ExternalFlowNode = Node<LeafData, 'external'>;
export type ClusterFlowNode = Node<ClusterData, 'cluster'>;
export type FlowNode = ProjectFlowNode | ExternalFlowNode | ClusterFlowNode;

/** depends_on = amber (risk), feeds = blue (data flow) — same hues as the legend. */
export const EDGE_COLOR = { depends_on: '#d29922', feeds: '#58a6ff' } as const;

const ZERO: Box = { x: 0, y: 0, width: 0, height: 0 };

export function toFlow(
  spec: GraphSpec,
  boxes: Map<string, Box>,
  highlight: Set<string> | null,
  selected: string | null,
): { nodes: FlowNode[]; edges: Edge[] } {
  const isLit = (id: string) => !highlight || highlight.has(id);
  const litGroups = new Set(spec.nodes.filter((n) => n.parent && isLit(n.id)).map((n) => n.parent));
  const nodes: FlowNode[] = spec.nodes.map((n): FlowNode => {
    const box = boxes.get(n.id) ?? ZERO;
    const position = { x: box.x, y: box.y };
    if (n.kind === 'group') {
      return {
        id: n.id,
        type: 'cluster',
        position,
        width: box.width,
        height: box.height,
        zIndex: 0,
        data: {
          label: n.label,
          isHost: n.id.startsWith('host:'),
          isDimmed: !isLit(n.id) && !litGroups.has(n.id),
          isSelected: selected === n.id,
        },
      };
    }
    const data: LeafData = { node: n.node as MapNode, isDimmed: !isLit(n.id), isSelected: selected === n.id };
    const base = { id: n.id, position, data, zIndex: 1, ...(n.parent ? { parentId: n.parent } : {}) };
    return n.kind === 'external' ? { ...base, type: 'external' } : { ...base, type: 'project' };
  });
  const edges: Edge[] = spec.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    animated: e.kind === 'feeds',
    zIndex: 2,
    className: `edge-${e.kind}${isLit(e.source) && isLit(e.target) ? '' : ' edge-dim'}`,
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: EDGE_COLOR[e.kind] },
  }));
  return { nodes, edges };
}
