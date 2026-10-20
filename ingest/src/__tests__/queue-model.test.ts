import { describe, expect, it } from 'vitest';
import { parseQueue, parseTicket } from '../queue-model.ts';

const ticket = (extra: Record<string, unknown> = {}) => ({
  done: false,
  cls: 'risk',
  size: 'S',
  flags: ['unblocks'],
  project: 'Strummy',
  id: 'STR-10',
  text: 'zrzut konfiguracji',
  model: 'sonnet → sonnet',
  meta: 'start 2026-10-19',
  brief: null,
  hours: null,
  date: null,
  ...extra,
});

const body = (extra: Record<string, unknown> = {}) => ({
  window_from: '2026-10-19',
  window_to: '2026-10-25',
  capacity_hours: 6,
  focus: 'Strummy',
  rules: '1 bilet w toku',
  sections: { in_progress: [ticket()], queue: [], done: [ticket({ done: true, hours: 0.5 })] },
  summary: { in_progress: 1, done: 1, done_hours: 0.5 },
  source_hash: 'abc',
  ...extra,
});

describe('parseTicket', () => {
  it('accepts the planner-sync shape and defaults the optional fields', () => {
    const t = parseTicket({ text: 'x' });
    expect(t).toEqual({
      done: false,
      cls: null,
      size: null,
      flags: [],
      project: null,
      id: null,
      text: 'x',
      model: null,
      meta: null,
      brief: null,
      hours: null,
      date: null,
    });
  });

  it('rejects unknown classes, sizes, flags and bad dates', () => {
    expect(parseTicket(ticket({ cls: 'urgent' }))).toMatch(/cls/);
    expect(parseTicket(ticket({ size: 'XXL' }))).toMatch(/size/);
    expect(parseTicket(ticket({ flags: ['gpu'] }))).toMatch(/flags/);
    expect(parseTicket(ticket({ date: '2026-02-30' }))).toMatch(/date/);
    expect(parseTicket(ticket({ hours: -1 }))).toMatch(/hours/);
    expect(parseTicket(ticket({ text: 'x'.repeat(601) }))).toMatch(/text/);
  });
});

describe('parseQueue', () => {
  it('returns the clean queue with only known sections', () => {
    const q = parseQueue({ ...body(), sections: { ...body().sections, bogus: [ticket()] } });
    expect(typeof q).toBe('object');
    if (typeof q === 'string') return;
    expect(Object.keys(q.sections)).toEqual(['in_progress', 'queue', 'done']);
    expect(q.capacity_hours).toBe(6);
    expect(q.summary.done_hours).toBe(0.5);
  });

  it('names the failing ticket', () => {
    expect(parseQueue(body({ sections: { queue: [ticket(), ticket({ cls: 'nope' })] } }))).toBe(
      'sections.queue[1]: cls must be risk|money|focus|clean|idea',
    );
  });

  it('rejects malformed headers and oversized sections', () => {
    expect(parseQueue(body({ window_to: '25.10.2026' }))).toMatch(/window/);
    expect(parseQueue(body({ capacity_hours: 'six' }))).toMatch(/capacity/);
    expect(parseQueue(body({ sections: { queue: Array(51).fill(ticket()) } }))).toMatch(/at most 50/);
    expect(parseQueue(body({ sections: 'x' }))).toMatch(/sections/);
    expect(parseQueue('nope')).toMatch(/object/);
  });
});
