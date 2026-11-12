import { describe, expect, it } from 'vitest';
import { parsePlace, parsePlaces } from '../storage-model.ts';

const place = (extra: Record<string, unknown> = {}) => ({
  id: 8,
  nazwa: 'Google Drive',
  gdzie: 'Google Drive',
  porzadek: 'problem',
  backup: 'problem',
  sprawdzone: '2026-11-12',
  note_path: '2-Obszary/mapy/miejsca/08-google-drive.md',
  ...extra,
});

describe('parsePlace', () => {
  it('accepts a full place and defaults the missing statuses', () => {
    const p = parsePlace(place({ stan: undefined, test_odtworzenia: '' }));
    expect(typeof p).toBe('object');
    if (typeof p === 'string') return;
    expect(p.stan).toBe('aktywne');
    expect(p.porzadek).toBe('problem');
    expect(p.test_odtworzenia).toBeNull();
    expect(p.raw_frontmatter).toEqual({});
  });

  it('rejects ids, names and paths it cannot store', () => {
    expect(parsePlace(place({ id: 0 }))).toBe('bad id');
    expect(parsePlace(place({ id: '8' }))).toBe('bad id');
    expect(parsePlace(place({ nazwa: '' }))).toBe('nazwa required');
    expect(parsePlace(place({ note_path: undefined }))).toBe('note_path required');
  });

  it('rejects status values outside the vault legend', () => {
    expect(parsePlace(place({ porzadek: '🟢' }))).toBe('bad status value');
    expect(parsePlace(place({ backup: 'tak' }))).toBe('bad status value');
    expect(parsePlace(place({ stan: 'archiwum' }))).toBe('bad status value');
  });

  it('rejects impossible dates and over-long text', () => {
    expect(parsePlace(place({ sprawdzone: '2026-02-30' }))).toBe('bad date');
    expect(parsePlace(place({ problem: 'x'.repeat(1001) }))).toBe('bad text field');
  });
});

describe('parsePlaces', () => {
  it('needs a places array', () => {
    expect(parsePlaces({})).toBe('places array required');
    expect(parsePlaces({ places: Array(501).fill(place()) })).toBe('too many places (max 500)');
  });

  it('keeps the first of two notes with the same id and reports the rest', () => {
    const r = parsePlaces({ places: [place(), place({ nazwa: 'kopia' }), place({ id: 0 })] });
    if (typeof r === 'string') throw new Error(r);
    expect(r.places.map((p) => p.nazwa)).toEqual(['Google Drive']);
    expect(r.rejected).toEqual([
      { index: 1, reason: 'duplicate id 8' },
      { index: 2, reason: 'bad id' },
    ]);
  });
});
