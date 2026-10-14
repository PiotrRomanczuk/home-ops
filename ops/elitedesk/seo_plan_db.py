"""seo_plan_db.py — seo_plan / seo_findings / seo_page_snapshot persistence.

All writes go through psql -v variables (seo_db.psql_exec). The LLM's plan
updates are validated here: unknown actions, missing fields and status moves
that would skip a stage are dropped, not applied.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date
from typing import Any

from seo_db import psql_exec, psql_json

ALLOWED_METRICS = ('impressions', 'clicks', 'ctr', 'position')


def load_plan(site: str) -> list[dict[str, Any]]:
    return psql_json(f"SELECT id, title, change, rationale, target_queries, target_pages, metric, status, priority, "
                     f"observe_days, source, pr_url, shipped_at::text, baseline, verdict FROM seo_plan "
                     f"WHERE site = '{site}' AND status <> 'retired' ORDER BY priority DESC, id")


def save_verdict(h_id: int, verdict: dict[str, Any], status: str | None) -> None:
    psql_exec("UPDATE seo_plan SET verdict = :'v'::jsonb, baseline = (:'v'::jsonb)->'baseline', "
              "status = COALESCE(NULLIF(:'s', ''), status), updated_at = now() WHERE id = :'id'::int;",
              {'v': json.dumps(verdict), 's': status or '', 'id': str(h_id)})


def mark_shipped_if_merged(h: dict[str, Any]) -> date | None:
    """in_pr → shipped when the PR is merged (gh on this host). Returns the merge date."""
    if h.get('status') != 'in_pr' or not h.get('pr_url'):
        return None
    try:
        out = subprocess.run(['gh', 'pr', 'view', h['pr_url'], '--json', 'mergedAt', '--jq', '.mergedAt // ""'],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 — gh missing/offline: try again tomorrow
        return None
    if not out:
        return None
    merged = date.fromisoformat(out[:10])
    psql_exec("UPDATE seo_plan SET status = 'shipped', shipped_at = :'d', updated_at = now() WHERE id = :'id'::int;",
              {'d': merged.isoformat(), 'id': str(h['id'])})
    return merged


def propose(site: str, u: dict[str, Any], source: str = 'llm') -> bool:
    need = ('title', 'change', 'target_queries')
    if not all(u.get(k) for k in need[:2]) or u.get('metric', 'impressions') not in ALLOWED_METRICS:
        return False
    pages = u.get('target_pages') or []
    if not isinstance(pages, list) or not (u.get('target_queries') or pages):
        return False
    psql_exec("INSERT INTO seo_plan (site, title, change, rationale, target_queries, target_pages, metric, priority, source) "
              "VALUES (:'site', :'title', :'change', :'why', :'q', :'pages'::text[], :'metric', :'prio'::int, :'src') "
              "ON CONFLICT (site, title) DO NOTHING;",
              {'site': site, 'title': str(u['title'])[:140], 'change': str(u['change'])[:1000], 'why': str(u.get('rationale', ''))[:1000],
               'q': str(u.get('target_queries', '')), 'pages': '{' + ','.join(f'"{p}"' for p in pages) + '}',
               'metric': u.get('metric', 'impressions'), 'prio': str(int(u.get('priority', 50))), 'src': source})
    return True


def apply_updates(site: str, updates: list[dict[str, Any]], plan: list[dict[str, Any]]) -> dict[str, int]:
    """LLM plan updates: propose | reprioritize | ready | retire (only pre-ship rows)."""
    ids = {h['id']: h for h in plan}
    n = {'propose': 0, 'reprioritize': 0, 'ready': 0, 'retire': 0, 'dropped': 0}
    for u in updates:
        act, h = u.get('action'), ids.get(u.get('id'))
        if act == 'propose' and propose(site, u):
            n['propose'] += 1
        elif act == 'reprioritize' and h and isinstance(u.get('priority'), int):
            psql_exec("UPDATE seo_plan SET priority = :'p'::int, updated_at = now() WHERE id = :'id'::int;",
                      {'p': str(max(0, min(100, u['priority']))), 'id': str(h['id'])})
            n['reprioritize'] += 1
        elif act in ('ready', 'retire') and h and h['status'] in ('proposed', 'ready'):
            psql_exec("UPDATE seo_plan SET status = :'s', rationale = COALESCE(NULLIF(:'why', ''), rationale), "
                      "updated_at = now() WHERE id = :'id'::int;",
                      {'s': 'ready' if act == 'ready' else 'retired', 'why': str(u.get('reason', ''))[:500], 'id': str(h['id'])})
            n[act] += 1
        else:
            n['dropped'] += 1
    return n


def save_snapshots(site: str, day: date, snaps: list[dict[str, Any]]) -> None:
    for s in snaps:
        psql_exec("INSERT INTO seo_page_snapshot (site, day, path, status_code, title, description, canonical, robots, "
                  "has_jsonld, words, cta_links, internal_links, h1) VALUES (:'site', :'day', :'path', :'st'::int, "
                  "NULLIF(:'t',''), NULLIF(:'d',''), NULLIF(:'c',''), NULLIF(:'r',''), :'j'::bool, :'w'::int, :'cta'::int, :'il'::int, NULLIF(:'h1','')) "
                  "ON CONFLICT (site, day, path) DO UPDATE SET status_code = EXCLUDED.status_code, title = EXCLUDED.title, "
                  "description = EXCLUDED.description, canonical = EXCLUDED.canonical, robots = EXCLUDED.robots, "
                  "has_jsonld = EXCLUDED.has_jsonld, words = EXCLUDED.words, cta_links = EXCLUDED.cta_links, "
                  "internal_links = EXCLUDED.internal_links, h1 = EXCLUDED.h1, fetched_at = now();",
                  {'site': site, 'day': day.isoformat(), 'path': s['path'], 'st': str(s['status_code']), 't': s.get('title') or '',
                   'd': s.get('description') or '', 'c': s.get('canonical') or '', 'r': s.get('robots') or '',
                   'j': 'true' if s.get('has_jsonld') else 'false', 'w': str(s.get('words', 0)), 'cta': str(s.get('cta_links', 0)),
                   'il': str(s.get('internal_links', 0)), 'h1': s.get('h1') or ''})


def previous_snapshots(site: str, day: date) -> dict[str, dict[str, Any]]:
    rows = psql_json(f"SELECT DISTINCT ON (path) path, title, description FROM seo_page_snapshot "
                     f"WHERE site = '{site}' AND day < '{day}' ORDER BY path, day DESC")
    return {r['path']: r for r in rows}


def sync_findings(site: str, day: date, found: list[dict[str, str]]) -> dict[str, int]:
    """Upsert today's hits (re-open if resolved), auto-resolve open ones not seen today."""
    for f in found:
        psql_exec("INSERT INTO seo_findings (site, path, rule, severity, detail, status, first_seen, last_seen) "
                  "VALUES (:'site', :'path', :'rule', :'sev', :'detail', 'open', :'day', :'day') "
                  "ON CONFLICT (site, path, rule) DO UPDATE SET last_seen = EXCLUDED.last_seen, detail = EXCLUDED.detail, "
                  "status = CASE WHEN seo_findings.status = 'dismissed' THEN 'dismissed' ELSE 'open' END, resolved_at = NULL;",
                  {'site': site, 'path': f['path'], 'rule': f['rule'], 'sev': f['severity'], 'detail': f['detail'][:500], 'day': day.isoformat()})
    psql_exec("UPDATE seo_findings SET status = 'resolved', resolved_at = :'day' WHERE site = :'site' AND status = 'open' "
              "AND last_seen < :'day';", {'site': site, 'day': day.isoformat()})
    open_rows = psql_json(f"SELECT path, rule, severity, detail, first_seen::text FROM seo_findings WHERE site = '{site}' "
                          f"AND status = 'open' ORDER BY severity, path")
    return {'raised': len(found), 'open': len(open_rows)}


def open_findings(site: str) -> list[dict[str, Any]]:
    return psql_json(f"SELECT path, rule, severity, detail, first_seen::text FROM seo_findings WHERE site = '{site}' "
                     f"AND status = 'open' ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, path")
