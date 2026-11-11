// What a BPMN lane says about the project behind it. Lane names are project
// slugs or external nodes (vault convention); anything else is "unknown".

import type { MapNode } from './api';

export interface LaneBadge {
  nodeId: string | null;
  label: string;
  status: string | null;
  health: string | null;
  pressure: number | null;
  breaks: number;
}

export function laneBadge(laneName: string, nodes: Map<string, MapNode>): LaneBadge {
  const node = nodes.get(laneName.trim().toLowerCase());
  if (!node) return { nodeId: null, label: '?', status: null, health: null, pressure: null, breaks: 0 };
  return {
    nodeId: node.id,
    label: node.kind === 'external' ? 'zewn.' : (node.status ?? '—'),
    status: node.status,
    health: node.health,
    pressure: node.pressure,
    breaks: node.dependents.length,
  };
}

export const SAVE_MESSAGE: Record<string, string> = {
  queued: 'W kolejce: planner-sync zapisze diagram do vaulta przy najbliższym przebiegu (do ok. minuty).',
  applied: 'Zapisane w vaulcie (commit planner-sync).',
  conflict: 'Konflikt: diagram zmienił się w vaulcie, odkąd go otwarto. Wczytaj ponownie i powtórz zmianę.',
  failed: 'Zapis odrzucony.',
};
