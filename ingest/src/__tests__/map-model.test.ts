import { describe, expect, it } from 'vitest';
import { buildMap, dependentsOf, type MapProjectRow } from '../map-model.ts';
import { asList, linkTarget } from '../vault-links.ts';

const project = (slug: string, fm: Record<string, unknown>, status = 'hot'): MapProjectRow => ({
  slug,
  title: slug,
  status,
  raw_frontmatter: fm,
});

describe('linkTarget / asList', () => {
  it('strips wikilinks, paths, aliases, quotes and case', () => {
    expect(linkTarget('"[[1-Projekty/Job-Radar|JR]]"')).toBe('job-radar');
    expect(linkTarget('[[Strummy#Now]]')).toBe('strummy');
    expect(linkTarget('ollama')).toBe('ollama');
  });

  it('accepts arrays and the old one-string list shape', () => {
    expect(asList(['home-ops', '[[Ollama]]'])).toEqual(['home-ops', 'ollama']);
    expect(asList('["[[supabase-studentproduction]]", "[[ollama]]"]')).toEqual([
      'supabase-studentproduction',
      'ollama',
    ]);
    expect(asList('[mac, uwh]')).toEqual(['mac', 'uwh']);
    expect(asList('[]')).toEqual([]);
    expect(asList('[[home-ops]]')).toEqual(['home-ops']);
    expect(asList(null)).toEqual([]);
  });
});

describe('dependentsOf', () => {
  it('walks depends_on transitively and survives cycles', () => {
    const deps = dependentsOf([
      { from: 'natalia-cv', to: 'job-radar', kind: 'depends_on' },
      { from: 'job-radar', to: 'home-ops', kind: 'depends_on' },
      { from: 'home-ops', to: 'job-radar', kind: 'depends_on' },
      { from: 'strummy', to: 'home-ops', kind: 'feeds' },
    ]);
    expect(deps.get('home-ops')).toEqual(['job-radar', 'natalia-cv']);
    expect(deps.get('job-radar')).toEqual(['home-ops', 'natalia-cv']);
    expect(deps.get('strummy')).toBeUndefined();
  });
});

describe('buildMap', () => {
  const map = buildMap(
    [
      project('strummy', {
        depends_on: ['supabase-studentproduction', 'ollama'],
        feeds: ['home-ops'],
        hosts: ['uwh', 'vercel'],
        health: '🟠',
        verdict: 'aktywny',
        stream: 'nauczanie',
      }),
      project('job-radar', { depends_on: '["[[home-ops]]"]', feeds: ['vectordigital'], hosts: '[mac, uwh]' }),
      project('natalia-cv', { depends_on: ['job-radar'] }, 'warm'),
      project('home-ops', { hosts: ['uwh'] }),
      project('Vectordigital', {}),
    ],
    [{ slug: 'lead-pipeline', title: 'Leady', lanes: ['Job-Radar', 'vectordigital'], warnings: ['x', 3] }],
  );
  const node = (id: string) => map.nodes.find((n) => n.id === id);

  it('turns unknown targets into external nodes and hosts into host nodes', () => {
    expect(node('ollama')?.kind).toBe('external');
    expect(node('host:uwh')?.kind).toBe('host');
    expect(node('vectordigital')?.kind).toBe('project');
    expect(map.nodes.filter((n) => n.kind === 'external').map((n) => n.id)).toEqual([
      'ollama',
      'supabase-studentproduction',
    ]);
  });

  it('carries frontmatter fields onto project nodes', () => {
    expect(node('strummy')).toMatchObject({
      health: '🟠',
      verdict: 'aktywny',
      stream: 'nauczanie',
      hosts: ['uwh', 'vercel'],
    });
    expect(node('job-radar')?.hosts).toEqual(['mac', 'uwh']);
  });

  it('computes blast radius from depends_on only', () => {
    expect(node('home-ops')?.dependents).toEqual(['job-radar', 'natalia-cv']);
    expect(node('ollama')?.dependents).toEqual(['strummy']);
    expect(node('strummy')?.dependents).toEqual([]);
  });

  it('keeps edge kinds and normalises process lanes', () => {
    expect(map.edges).toContainEqual({ from: 'job-radar', to: 'vectordigital', kind: 'feeds' });
    expect(map.edges).toContainEqual({ from: 'strummy', to: 'host:vercel', kind: 'runs_on' });
    expect(map.processes).toEqual([
      { slug: 'lead-pipeline', title: 'Leady', lanes: ['job-radar', 'vectordigital'], warnings: ['x'] },
    ]);
  });
});
