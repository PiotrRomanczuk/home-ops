import { describe, expect, it } from 'vitest';
import type { MapNode, MapResponse } from './api';
import { toFlow } from './flow';
import { EXTERNAL_GROUP, ecosystemSpec, impactOf, infraSpec, primaryHost, relationsOf, visibleIds } from './graph';
import { layoutSpec } from './layout';

const node = (id: string, over: Partial<MapNode> = {}): MapNode => ({
  id,
  kind: 'project',
  label: id,
  status: 'hot',
  verdict: 'aktywny',
  health: null,
  stream: null,
  summary: null,
  hosts: [],
  dependents: [],
  pressure: null,
  ...over,
});

const MAP: MapResponse = {
  nodes: [
    node('strummy', { hosts: ['mac', 'uwh', 'vercel'], stream: 'nauczanie' }),
    node('job-radar', { hosts: ['mac', 'uwh', 'github'], dependents: ['natalia-cv'] }),
    node('natalia-cv', { hosts: ['mac', 'uwh'], status: 'warm' }),
    node('home-ops', { hosts: ['mac', 'uwh', 'wfh'], dependents: ['job-radar', 'natalia-cv'] }),
    node('olx-scraper', {
      hosts: ['mac'],
      status: 'dormant',
      verdict: 'scalany',
      dependents: ['job-radar', 'natalia-cv'],
    }),
    node('inborr', { hosts: ['vercel'], status: 'dormant', verdict: 'portfolio' }),
    node('ollama', { kind: 'external', status: null, verdict: null, dependents: ['strummy'] }),
    node('unused-ext', { kind: 'external', status: null, verdict: null }),
    node('host:uwh', { kind: 'host', label: 'uwh', status: null, verdict: null }),
  ],
  edges: [
    { from: 'strummy', to: 'ollama', kind: 'depends_on' },
    { from: 'strummy', to: 'home-ops', kind: 'feeds' },
    { from: 'job-radar', to: 'home-ops', kind: 'depends_on' },
    { from: 'job-radar', to: 'olx-scraper', kind: 'depends_on' },
    { from: 'natalia-cv', to: 'job-radar', kind: 'depends_on' },
    { from: 'strummy', to: 'host:uwh', kind: 'runs_on' },
  ],
  processes: [],
};

describe('visibility', () => {
  it('hides quiet projects unless a relation still ties them in, and unused externals', () => {
    const ids = visibleIds(MAP, false);
    expect(ids.has('olx-scraper')).toBe(true); // dormant + merged, but job-radar depends on it
    expect(ids.has('inborr')).toBe(false);
    expect(ids.has('unused-ext')).toBe(false);
    expect(ids.has('host:uwh')).toBe(false);
    expect(visibleIds(MAP, true).has('inborr')).toBe(true);
  });
});

describe('specs', () => {
  it('ecosystem: stream groups, externals grouped, parents first, no runs_on edges', () => {
    const spec = ecosystemSpec(MAP, false);
    const groupIds = spec.nodes.filter((n) => n.kind === 'group').map((n) => n.id);
    expect(groupIds).toEqual(['group:nauczanie', EXTERNAL_GROUP]);
    expect(spec.nodes.findIndex((n) => n.kind !== 'group')).toBe(2);
    expect(spec.nodes.find((n) => n.id === 'job-radar')?.parent).toBeNull();
    expect(spec.edges.map((e) => e.kind).sort()).toEqual([
      'depends_on',
      'depends_on',
      'depends_on',
      'depends_on',
      'feeds',
    ]);
  });

  it('infra: projects inside their primary server host, depends_on only', () => {
    const spec = infraSpec(MAP, false);
    expect(spec.nodes.find((n) => n.id === 'strummy')?.parent).toBe('host:uwh');
    expect(spec.nodes.find((n) => n.id === 'olx-scraper')?.parent).toBe('host:mac');
    expect(spec.edges.every((e) => e.kind === 'depends_on')).toBe(true);
    expect(primaryHost(node('x', { hosts: ['mac', 'github', 'vercel'] }))).toBe('vercel');
    expect(primaryHost(node('x', { hosts: [] }))).toBe('bez hosta');
  });
});

describe('impact and relations', () => {
  it('a node lights up itself, its neighbours and everyone who breaks with it', () => {
    expect([...impactOf(MAP, 'home-ops')].sort()).toEqual(['home-ops', 'job-radar', 'natalia-cv', 'strummy']);
  });

  it('a server host lights up every project listing it, plus their dependents', () => {
    const lit = impactOf(MAP, 'host:wfh');
    expect([...lit].sort()).toEqual(['home-ops', 'host:wfh', 'job-radar', 'natalia-cv']);
  });

  it('splits relations by direction and kind', () => {
    expect(relationsOf(MAP, 'job-radar')).toEqual({
      dependsOn: ['home-ops', 'olx-scraper'],
      feeds: [],
      fedBy: [],
      neededBy: ['natalia-cv'],
    });
  });
});

describe('layout + flow', () => {
  it('positions every node, children inside their group, and flags dimming', async () => {
    const spec = ecosystemSpec(MAP, false);
    const boxes = await layoutSpec(spec);
    for (const n of spec.nodes) expect(boxes.has(n.id)).toBe(true);
    const group = boxes.get(EXTERNAL_GROUP);
    const ollama = boxes.get('ollama');
    expect(ollama && group && ollama.x + ollama.width <= group.width).toBe(true);
    const flow = toFlow(spec, boxes, impactOf(MAP, 'strummy'), 'strummy');
    const byId = new Map(flow.nodes.map((n) => [n.id, n]));
    expect(byId.get('ollama')?.parentId).toBe(EXTERNAL_GROUP);
    expect(byId.get('natalia-cv')?.data.isDimmed).toBe(true);
    expect(byId.get('strummy')?.data.isSelected).toBe(true);
    expect(flow.edges.find((e) => e.id === 'job-radar>home-ops>depends_on')?.className).toContain('edge-dim');
  });
});
