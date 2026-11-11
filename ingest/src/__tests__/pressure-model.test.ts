import { describe, expect, it } from 'vitest';
import { type PressureInput, projectPressure, type Runtime, rankPressure, WEIGHTS } from '../pressure-model.ts';
import { countPain, countTasks } from '../vault-tasks.ts';

const quiet: Runtime = { errorPatterns: new Map(), down: new Set() };
const input = (over: Partial<PressureInput> = {}): PressureInput => ({
  slug: 'strummy',
  title: 'Strummy',
  status: 'hot',
  raw_frontmatter: { verdict: 'aktywny', stream: 'nauczanie', health: '🟠' },
  now_md: null,
  next_md: null,
  pain_md: null,
  repo_meta: null,
  ...over,
});

describe('countTasks / countPain', () => {
  it('counts open tasks by the class emoji that starts them', () => {
    const now = '- [ ] 🔴 S fix RLS\n- [x] 🔴 done\n  - [ ] 💰 M invoice\n- [ ] 🧹 tidy\n- [ ] 2026-11-11 plain';
    expect(countTasks(now, '- [ ] 💡 idea 🔴 later in text')).toEqual({ red: 1, money: 1, other: 2, unclassed: 1 });
    expect(countTasks(null, null)).toEqual({ red: 0, money: 0, other: 0, unclassed: 0 });
  });

  it('counts open pain bullets, not ticked or struck ones', () => {
    expect(countPain('- slow build\n- [x] fixed\n- ~~gone~~\n* flaky e2e\ntext')).toBe(2);
  });
});

describe('projectPressure', () => {
  it('adds every source and shows the parts', () => {
    const row = projectPressure(
      input({
        now_md: '- [ ] 🔴 S a\n- [ ] 💰 M b',
        pain_md: '- one',
        repo_meta: {
          gaps: { count: 20, ids: ['SKL-1'] },
          issues: { open: 3, bugs: 1 },
          ci: { conclusion: 'failure' },
        },
      }),
      ['job-radar', 'natalia-cv'],
      { errorPatterns: new Map([['strummy', 2]]), down: new Set(['strummy']) },
    );
    // tasks 4+2, pain 2, gaps capped 15, issues 3·1 + 1·2, runtime 2·2 + 5 + 5
    expect(row?.parts.tasks.points).toBe(6);
    expect(row?.parts.gaps).toEqual({ n: 20, ids: ['SKL-1'], points: 15, hasBlueprint: true });
    expect(row?.parts.issues.points).toBe(5);
    expect(row?.parts.runtime).toEqual({ errorPatterns: 2, ciFailed: true, down: true, points: 14 });
    expect(row?.base).toBe(42);
    expect(row?.blast).toBe(1.5);
    expect(row?.score).toBe(63);
  });

  it('weights by status and drops archived / merged / deleted projects', () => {
    const dormant = projectPressure(input({ status: 'dormant', pain_md: '- x' }), [], quiet);
    expect(dormant?.score).toBe(2 * WEIGHTS.status.dormant);
    for (const verdict of WEIGHTS.excludedVerdicts)
      expect(projectPressure(input({ raw_frontmatter: { verdict } }), [], quiet)).toBeNull();
  });

  it('treats a missing repo_meta as zero, not an error', () => {
    const row = projectPressure(input(), [], quiet);
    expect(row?.score).toBe(0);
    expect(row?.parts.gaps.hasBlueprint).toBe(false);
  });
});

describe('rankPressure', () => {
  it('sorts by score, then slug, and matches dependents case-insensitively', () => {
    const rows = rankPressure(
      [
        input({ slug: 'b', pain_md: '- x' }),
        input({ slug: 'A', pain_md: '- x' }),
        input({ slug: 'home-ops', pain_md: '- x' }),
      ],
      new Map([['home-ops', ['job-radar', 'd4-build-agent']]]),
      quiet,
    );
    expect(rows.map((r) => r.slug)).toEqual(['home-ops', 'A', 'b']);
    expect(rows[0]?.dependents).toEqual(['job-radar', 'd4-build-agent']);
  });
});
