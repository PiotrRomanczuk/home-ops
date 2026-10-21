// Pure shaping for GET /api/today: merges vault Now lines and Board Now cards
// into one list per project. planner-sync renders the Board back into the
// vault, so the same task often arrives from both sides — dedupe on text.

import { taskTitle } from './task-title.ts';

export interface TaskRow {
  slug: string;
  title: string | null;
  status: string | null;
  ord: number;
  text: string;
  is_focus?: boolean;
}

export interface TodayTask {
  text: string;
  /** one-line head of `text` for the compact list; `text` stays the tooltip */
  title: string;
  source: 'vault' | 'board';
  is_focus: boolean;
}

export interface TaskGroup {
  slug: string;
  title: string;
  status: string | null;
  tasks: TodayTask[];
}

const MAX_PER_PROJECT = 7;

export function taskKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/[\s.:;,!]+$/, '')
    .trim();
}

/** Board first (focus pinned on top), then vault lines not already on the Board. */
export function groupTasks(board: TaskRow[], vault: TaskRow[]): TaskGroup[] {
  const groups = new Map<string, TaskGroup>();
  const seen = new Set<string>();
  const add = (r: TaskRow, source: TodayTask['source']) => {
    const text = r.text.trim();
    const key = `${r.slug}\u0000${taskKey(text)}`;
    if (!text || seen.has(key)) return;
    seen.add(key);
    let g = groups.get(r.slug);
    if (!g) {
      g = { slug: r.slug, title: r.title || r.slug, status: r.status, tasks: [] };
      groups.set(r.slug, g);
    }
    if (g.tasks.length < MAX_PER_PROJECT)
      g.tasks.push({ text, title: taskTitle(text), source, is_focus: r.is_focus === true });
  };
  for (const r of board) add(r, 'board');
  for (const r of vault) add(r, 'vault');
  const rank = (s: string | null) => (s === 'hot' ? 0 : s === 'warm' ? 1 : 2);
  return [...groups.values()].sort(
    (a, b) =>
      Number(b.tasks.some((t) => t.is_focus)) - Number(a.tasks.some((t) => t.is_focus)) ||
      rank(a.status) - rank(b.status),
  );
}
