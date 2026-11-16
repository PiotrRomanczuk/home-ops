import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { decideImport, sha256Hex } from './bpmnSync';

const A = 'a'.repeat(64);
const B = 'b'.repeat(64);
const C = 'c'.repeat(64);

describe('decideImport', () => {
  it('loads the first copy', () => {
    expect(decideImport({ incoming: A, seen: null, base: null, isDirty: false })).toBe('import');
  });

  it('ignores a refetch of the copy it already decided on', () => {
    // F1: stale refetch right after our own save must not revert the editor.
    expect(decideImport({ incoming: A, seen: A, base: B, isDirty: false })).toBe('skip');
    expect(decideImport({ incoming: A, seen: A, base: A, isDirty: true })).toBe('skip');
  });

  it('ignores the vault copy that is our own save', () => {
    expect(decideImport({ incoming: B, seen: A, base: B, isDirty: false })).toBe('skip');
    expect(decideImport({ incoming: B, seen: A, base: B, isDirty: true })).toBe('skip');
  });

  it('imports a foreign change when nothing is unsaved', () => {
    expect(decideImport({ incoming: C, seen: A, base: A, isDirty: false })).toBe('import');
  });

  it('asks instead of discarding unsaved edits (F2)', () => {
    expect(decideImport({ incoming: C, seen: A, base: A, isDirty: true })).toBe('ask');
  });
});

describe('sha256Hex', () => {
  it('matches the digest planner-sync computes over the UTF-8 bytes', async () => {
    const xml = '<bpmn:definitions>zażółć gęślą jaźń</bpmn:definitions>';
    expect(await sha256Hex(xml)).toBe(createHash('sha256').update(xml, 'utf8').digest('hex'));
  });
});
