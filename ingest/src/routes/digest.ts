import type { Hono } from 'hono';
import { tokenOnly } from '../auth.ts';
import { pool } from '../db.ts';
import { DECISION_COLS, type DecisionRow, linksFor, normalizeOptions } from '../decisions-store.ts';
import {
  ACCEPTANCE_SQL,
  CARDS_SQL,
  FOCUS_SQL,
  HOSTS_SQL,
  NARRATIVE_SQL,
  NEXT_SQL,
  PROBLEMS_SQL,
  SITES_SQL,
} from '../digest-sql.ts';

// GET /api/digest — the whole morning/evening email as one JSON model.
// ops/elitedesk/render-digest.py turns it into HTML; nothing in the renderer
// needs the database. Token-only because the model carries signed links.

// Known-noise patterns the digest hides from "needs attention". Each entry
// is a decision already taken (the GPU lane was switched off 2026-07-16).
export const MUTED = [/gpu queue stalled/i];

const SILENT_AFTER_MIN = 5;
const DISK_WARN_PCT = 90;

export interface HostRow {
  host: string;
  last_metric_ts: string | null;
  last_event_ts: string | null;
  cpu_pct: number | null;
  mem_pct: number | null;
  disk_pct: number | null;
}

export function hostStatus(h: HostRow, now: number): 'ok' | 'warn' | 'bad' | 'off' {
  if (!h.last_metric_ts) return 'off';
  const silentMin = (now - new Date(h.last_metric_ts).getTime()) / 60_000;
  if (silentMin > SILENT_AFTER_MIN) return 'bad';
  if ((h.disk_pct ?? 0) >= DISK_WARN_PCT) return 'warn';
  return 'ok';
}

function titleOf(line: string): string {
  // "Deploy X to the Pi (why…) — long explanation…" → "Deploy X to the Pi"
  const bare = line.replace(/\s*\([^)]*\)/g, '');
  const cut = (bare.split(/\s+[—–-]\s+|\.\s/)[0] ?? bare).replace(/`/g, '').trim();
  return cut.length > 110 ? `${cut.slice(0, 107)}…` : cut;
}

export function registerDigestRoutes(app: Hono): void {
  app.use('/api/digest', tokenOnly);

  app.get('/api/digest', async (c) => {
    const mode = c.req.query('mode') === 'evening' ? 'evening' : 'morning';
    const slug = c.req.query('slug') || 'home-ops';
    const now = Date.now();
    const [hosts, problems, sites, focus, next, cards, acceptance, decisions, narrative] = await Promise.all([
      pool.query(HOSTS_SQL),
      pool.query(PROBLEMS_SQL),
      pool.query(SITES_SQL),
      pool.query(FOCUS_SQL, [slug]),
      pool.query(NEXT_SQL, [slug]),
      pool.query(CARDS_SQL),
      pool.query(ACCEPTANCE_SQL),
      pool.query(`SELECT ${DECISION_COLS} FROM public.decisions
                   WHERE answer IS NULL AND expires_at >= now() ORDER BY created_at LIMIT 10`),
      mode === 'morning' ? pool.query(NARRATIVE_SQL) : Promise.resolve({ rows: [] as { summary: string }[] }),
    ]);

    const hostRows = (hosts.rows as HostRow[]).map((h) => ({ ...h, status: hostStatus(h, now) }));
    const visibleProblems = problems.rows.filter((p) => !MUTED.some((re) => re.test(p.pattern)));
    const mutedCount = problems.rows.length - visibleProblems.length;
    const nextLines = next.rows.map((r) => titleOf(r.text));
    const focusText = focus.rows[0]?.text ? titleOf(focus.rows[0].text) : (nextLines[0] ?? null);
    const openDecisions = (decisions.rows as DecisionRow[]).map((d) => ({
      ...d,
      options: normalizeOptions(d.options),
      links: linksFor(d),
    }));

    const attention = visibleProblems.length + hostRows.filter((h) => h.status === 'warn' || h.status === 'bad').length;
    const verdict =
      attention === 0 && openDecisions.length === 0
        ? 'All quiet. Nothing needs you.'
        : attention === 0
          ? `All quiet. ${openDecisions.length} ${openDecisions.length === 1 ? 'decision waits' : 'decisions wait'} for you.`
          : `${attention} ${attention === 1 ? 'thing needs' : 'things need'} you${openDecisions.length ? ` and ${openDecisions.length} ${openDecisions.length === 1 ? 'decision waits' : 'decisions wait'}` : ''}.`;

    return c.json({
      generated_at: new Date(now).toISOString(),
      mode,
      slug,
      verdict,
      hosts: hostRows,
      problems: visibleProblems,
      muted_problems: mutedCount,
      sites: sites.rows,
      focus: focusText,
      next: nextLines.filter((t) => t !== focusText).slice(0, 3),
      cards: cards.rows,
      acceptance: acceptance.rows,
      decisions: openDecisions,
      narrative: narrative.rows[0]?.summary ?? null,
    });
  });
}
