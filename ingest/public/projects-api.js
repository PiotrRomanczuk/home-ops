/* ============================================================
   projects-api.js — wires the Projects tab to /api/projects.

   The server returns rows with raw markdown sections (now_md,
   next_md, later_md, pain_md). We parse them client-side into
   the shape the existing card/drill renderer expects:
     now/next/later: [[text, done], ...]
     pain: string (first paragraph of pain_md)
     spark: number[30] (illustrative; derived from commits_30d)

   errors_today / jobs_q are computed on demand from window.Logs
   and window.Chat — they update naturally as those modules load.
   ============================================================ */

const PROJECT_FETCH_MS_FRESH = 10_000; // refresh "synced N ago" label cheaply

function parseTaskList(md) {
  if (!md) return [];
  const out = [];
  for (const raw of md.split('\n')) {
    const m = raw.match(/^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$/);
    if (m) out.push([m[2], m[1].toLowerCase() === 'x']);
  }
  return out;
}

function parsePain(md) {
  if (!md) return '';
  // First paragraph — up to the first blank line.
  const i = md.indexOf('\n\n');
  return (i >= 0 ? md.slice(0, i) : md).trim();
}

function makeSpark(commits_30d, slug) {
  // Illustrative only — real per-day counts would come from a server
  // aggregate. Deterministic per slug so the bars don't jitter on rerender.
  if (!commits_30d) return new Array(30).fill(0);
  let h = 2166136261;
  for (let i = 0; i < slug.length; i++) {
    h = Math.imul(h ^ slug.charCodeAt(i), 16777619) >>> 0;
  }
  const base = commits_30d / 30;
  const out = [];
  let total = 0;
  for (let i = 0; i < 30; i++) {
    h = (Math.imul(h, 1664525) + 1013904223) >>> 0;
    const noise = ((h % 1000) / 1000 - 0.5) * base * 1.4;
    const v = Math.max(0, Math.round(base + noise));
    out.push(v);
    total += v;
  }
  // Rescale to actually hit commits_30d (rounding drift).
  if (total > 0 && total !== commits_30d) {
    const factor = commits_30d / total;
    for (let i = 0; i < 30; i++) out[i] = Math.round(out[i] * factor);
  }
  return out;
}

function parseProject(row) {
  const slug = row.slug;
  return {
    slug,
    title: row.title || slug,
    status: row.status || 'dormant',
    path: row.path || '',
    last_commit: row.last_commit || row.updated_at || new Date().toISOString(),
    commits_30d: row.commits_30d || 0,
    updated_at: row.updated_at || row.synced_at || new Date().toISOString(),
    synced_at: row.synced_at,
    now: parseTaskList(row.now_md),
    next: parseTaskList(row.next_md),
    later: parseTaskList(row.later_md),
    pain: parsePain(row.pain_md),
    spark: makeSpark(row.commits_30d || 0, slug),
    raw_frontmatter: row.raw_frontmatter || {},
    // Reactive counts — recomputed via getters on each access so they pick
    // up Logs/Chat as those modules populate.
    get errors_today() {
      const rows = window.Logs?.rows || [];
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      return rows.filter((l) =>
        l.source === 'app:' + slug &&
        (LV_ORDER[l.level] || 0) >= 3 &&
        new Date(l.ts).getTime() >= cutoff,
      ).length;
    },
    get jobs_q() {
      const convs = window.Chat?.conversations || [];
      return convs.filter((c) => c.project === slug && (c.status === 'queued' || c.status === 'running' || c.status === 'paused')).length;
    },
  };
}

const Projects = {
  items: [],
  loaded: false,
  loading: false,
  err: null,
  syncedAt: null,

  async loadAll() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await window.api('GET', '/api/projects');
      this.items = (j.projects || []).map(parseProject);
      this.loaded = true;
      // Most recent synced_at across all rows == when the worker last ran.
      this.syncedAt = this.items.reduce(
        (acc, p) => (p.synced_at && (!acc || p.synced_at > acc) ? p.synced_at : acc),
        null,
      );
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render) window.render();
  },

  bySlug(slug) {
    return this.items.find((p) => p.slug === slug) || null;
  },

  async refreshOne(slug) {
    try {
      const j = await window.api('GET', '/api/projects/' + encodeURIComponent(slug));
      if (j && j.project) {
        const parsed = parseProject(j.project);
        const i = this.items.findIndex((p) => p.slug === slug);
        if (i >= 0) this.items[i] = parsed;
        else this.items.unshift(parsed);
        if (window.render) window.render();
      }
    } catch { /* swallow */ }
  },
};

window.Projects = Projects;
window._projectsFreshAt = PROJECT_FETCH_MS_FRESH;
