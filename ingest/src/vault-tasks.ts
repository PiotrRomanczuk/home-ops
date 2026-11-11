// Open work in a project note's sections (now_md / next_md / pain_md), read the
// way the §8 rubric writes it: `- [ ] 🔴 S 2026-10-19 text`. Pure.

export interface TaskCounts {
  red: number;
  money: number;
  other: number;
  unclassed: number;
}

const OPEN_TASK_RE = /^\s*[-*]\s+\[ \]\s*(.*)$/;
const PAIN_RE = /^\s*[-*]\s+(?!\[[xX]\])(?!~~)\S/;
const OTHER_CLASSES = ['🎯', '🧹', '💡'];

/** Open `- [ ]` lines in Now/Next by the §8 class emoji that starts the task. */
export function countTasks(...sections: Array<string | null>): TaskCounts {
  const out: TaskCounts = { red: 0, money: 0, other: 0, unclassed: 0 };
  for (const line of sections.join('\n').split('\n')) {
    const rest = OPEN_TASK_RE.exec(line)?.[1]?.trimStart();
    if (rest === undefined) continue;
    if (rest.startsWith('🔴')) out.red++;
    else if (rest.startsWith('💰')) out.money++;
    else if (OTHER_CLASSES.some((c) => rest.startsWith(c))) out.other++;
    else out.unclassed++;
  }
  return out;
}

/** Bullets in "Pain points" that are not ticked or struck through. */
export function countPain(md: string | null): number {
  return (md ?? '').split('\n').filter((l) => PAIN_RE.test(l)).length;
}
