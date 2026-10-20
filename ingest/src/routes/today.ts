import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { HOSTS_SQL, PROBLEMS_SQL } from '../digest-sql.ts';
import { groupTasks, type TaskRow } from '../today-model.ts';
import { BOARD_NOW_SQL, FRESH_CARDS_SQL, LATEST_BRIEF_SQL, NOW_TASKS_SQL, OPEN_DECISIONS_SQL } from '../today-sql.ts';
import { type HostRow, hostStatus, MUTED } from './digest.ts';
import { QUEUE_SQL } from './queue.ts';

// GET /api/today — the console's default "Dziś" tab in one call: the latest
// day brief, the agent queue (QUEUE.md mirror), open Now tasks across
// hot/warm projects, what is broken, and what waits for an answer. Viewer-readable, so it carries no signed links.

export function registerTodayRoutes(app: Hono): void {
  app.use('/api/today', viewerOrToken);

  app.get('/api/today', async (c) => {
    const now = Date.now();
    const [brief, vault, board, hosts, problems, decisions, cards, queue] = await Promise.all([
      pool.query(LATEST_BRIEF_SQL),
      pool.query(NOW_TASKS_SQL),
      pool.query(BOARD_NOW_SQL),
      pool.query(HOSTS_SQL),
      pool.query(PROBLEMS_SQL),
      pool.query(OPEN_DECISIONS_SQL),
      pool.query(FRESH_CARDS_SQL),
      pool.query(QUEUE_SQL),
    ]);

    const hostRows = (hosts.rows as HostRow[]).map((h) => ({ ...h, status: hostStatus(h, now) }));
    const visibleProblems = problems.rows.filter((p) => !MUTED.some((re) => re.test(p.pattern)));
    const mutedProblems = problems.rows.length - visibleProblems.length;

    return c.json({
      generated_at: new Date(now).toISOString(),
      brief: brief.rows[0] ?? null,
      queue: queue.rows[0] ?? null,
      tasks: groupTasks(board.rows as TaskRow[], vault.rows as TaskRow[]),
      problems: visibleProblems,
      muted_problems: mutedProblems,
      hosts: hostRows,
      decisions: decisions.rows,
      cards: cards.rows,
    });
  });
}
