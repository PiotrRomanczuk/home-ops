import { describe, expect, it } from 'vitest';
import { MAX_BPMN_CHARS, parseProcessesBody } from '../process-model.ts';

const ok = {
  slug: 'lead-pipeline',
  title: 'Leady VD',
  trigger: 'cron',
  schedule: null,
  summary: 'Leady',
  projects: ['job-radar', 'vectordigital'],
  lanes: ['job-radar', 'vectordigital'],
  bpmn_xml: '<bpmn:definitions/>',
  bpmn_hash: 'abc',
  path: '2-Obszary/mapy/procesy/lead-pipeline.md',
  warnings: [],
};

describe('parseProcessesBody', () => {
  it('accepts a full record and normalises empty strings to null', () => {
    const r = parseProcessesBody({ processes: [{ ...ok, schedule: '' }] });
    expect(r).toEqual([{ ...ok, schedule: null }]);
  });

  it('accepts an empty set (all process notes deleted)', () => {
    expect(parseProcessesBody({ processes: [] })).toEqual([]);
  });

  it('falls back to the slug as title', () => {
    const r = parseProcessesBody({ processes: [{ slug: 'x' }] });
    expect(r).toEqual([
      {
        slug: 'x',
        title: 'x',
        trigger: null,
        schedule: null,
        summary: null,
        projects: [],
        lanes: [],
        bpmn_xml: null,
        bpmn_hash: null,
        path: null,
        warnings: [],
      },
    ]);
  });

  it('rejects bad shapes with a reason', () => {
    expect(parseProcessesBody({})).toBe('processes must be an array');
    expect(parseProcessesBody({ processes: [{ slug: 'a b' }] })).toBe('process 0: invalid slug');
    expect(parseProcessesBody({ processes: [{ ...ok, lanes: 'job-radar' }] })).toMatch(/string arrays/);
    expect(parseProcessesBody({ processes: [{ ...ok, trigger: 5 }] })).toMatch(/invalid text field/);
    expect(parseProcessesBody({ processes: [ok, ok] })).toMatch(/duplicate slug/);
    expect(parseProcessesBody({ processes: [{ ...ok, bpmn_xml: 'x'.repeat(MAX_BPMN_CHARS + 1) }] })).toMatch(
      /too large/,
    );
  });
});
