import { describe, expect, it } from 'vitest';
import { taskTitle, titleOf } from '../task-title.ts';
import { groupTasks } from '../today-model.ts';

describe('taskTitle', () => {
  it('keeps class + size, drops the entry date and everything after the dash', () => {
    expect(
      taskTitle(
        '🔴 S 2026-10-19 STR-10 Zrzut konfiguracji stosu prod do backupu — `docker inspect` (env, labels) 10 kontenerów',
      ),
    ).toBe('🔴 S STR-10 Zrzut konfiguracji stosu prod do backupu');
  });

  it('drops a plain leading date and bold markers', () => {
    expect(taskTitle('2026-10-13 **Decisions inbox + digest rewrite** — PR #48 SCALONY 2026-10-14 (migracje…)')).toBe(
      'Decisions inbox + digest rewrite',
    );
  });

  it('removes struck-out parts', () => {
    expect(taskTitle('~~2026-10-20 Sprawdzić pierwszy brief z gitem:~~ czy „Czeka na merge” pokazuje PR #2')).toBe(
      'czy „Czeka na merge” pokazuje PR #2',
    );
  });

  it('turns wikilinks into their label', () => {
    expect(taskTitle('Pipeline social → źródło treści dla [[social-hub]]')).toBe(
      'Pipeline social → źródło treści dla social-hub',
    );
    expect(taskTitle('Fokus: [[projects/Strummy/Strummy|Strummy]] przed uczniem')).toBe('Fokus: Strummy przed uczniem');
  });

  it('cuts long single sentences at 110 chars', () => {
    const t = taskTitle(`Rozważyć ${'x'.repeat(200)}`);
    expect(t.length).toBe(108);
    expect(t.endsWith('…')).toBe(true);
  });

  it('falls back to titleOf of the raw line when cleaning empties it', () => {
    expect(taskTitle('~~wszystko skreślone~~')).toBe(titleOf('~~wszystko skreślone~~'));
  });
});

describe('groupTasks', () => {
  it('carries a title next to the full text', () => {
    const [g] = groupTasks(
      [],
      [{ slug: 'a', title: 'A', status: 'hot', ord: 1, text: '2026-10-01 Fix sync — long tail' }],
    );
    expect(g?.tasks[0]).toMatchObject({ text: '2026-10-01 Fix sync — long tail', title: 'Fix sync' });
  });
});
