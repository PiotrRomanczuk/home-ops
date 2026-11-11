import { describe, expect, it } from 'vitest';
import type { MapNode } from './api';
import { laneBadge } from './bpmn';

const node = (id: string, over: Partial<MapNode> = {}): MapNode => ({
  id,
  kind: 'project',
  label: id,
  status: 'hot',
  verdict: null,
  health: '🟢',
  stream: null,
  summary: null,
  hosts: [],
  dependents: [],
  pressure: 21.4,
  ...over,
});
const nodes = new Map([
  ['home-ops', node('home-ops', { dependents: ['job-radar', 'natalia-cv'] })],
  ['ollama', node('ollama', { kind: 'external', status: null, health: null, pressure: null })],
]);

describe('laneBadge', () => {
  it('describes a project lane, case-insensitively', () => {
    expect(laneBadge(' Home-Ops ', nodes)).toEqual({
      nodeId: 'home-ops',
      label: 'hot',
      status: 'hot',
      health: '🟢',
      pressure: 21.4,
      breaks: 2,
    });
  });

  it('marks external and unknown lanes', () => {
    expect(laneBadge('ollama', nodes).label).toBe('zewn.');
    expect(laneBadge('piotr', nodes)).toMatchObject({ nodeId: null, label: '?' });
  });
});
