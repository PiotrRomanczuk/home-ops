import { describe, expect, it } from 'vitest';
import { gapsCell, gapsDetail } from './gaps';

const base = { n: 2, ids: ['G1', 'G2'], points: 1 };

describe('gapsDetail', () => {
  it('true', () => expect(gapsDetail({ ...base, hasBlueprint: true, partial: false })).toBe('2 otwartych: G1, G2'));
  it('false', () => expect(gapsDetail({ ...base, hasBlueprint: false, partial: false })).toBe('brak blueprintu'));
  it('null', () => expect(gapsDetail({ ...base, hasBlueprint: null, partial: false })).toBe('GitHub API niedostępne'));
  it('partial', () =>
    expect(gapsDetail({ ...base, hasBlueprint: true, partial: true })).toBe('2 otwartych: G1, G2 (częściowo)'));
});

describe('gapsCell', () => {
  it('true', () => expect(gapsCell({ ...base, hasBlueprint: true, partial: false })).toEqual({ text: '2' }));
  it('false', () => expect(gapsCell({ ...base, hasBlueprint: false, partial: false })).toEqual({ text: '—' }));
  it('null', () =>
    expect(gapsCell({ ...base, hasBlueprint: null, partial: false })).toEqual({
      text: '?',
      title: 'GitHub API niedostępne',
    }));
  it('partial', () => expect(gapsCell({ ...base, hasBlueprint: true, partial: true }).text).toBe('2*'));
});
