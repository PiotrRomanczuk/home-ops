// Wikilink lists from vault frontmatter (raw_frontmatter), as planner-sync sends
// them: arrays since vault_parse.py, one string before. Pure.

const WIKILINK_RE = /^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]$/;

/** `[[path/to/note|alias]]` → `note`, quotes stripped, lower-cased. */
export function linkTarget(raw: string): string {
  const s = raw.trim().replace(/^["']|["']$/g, '');
  const m = WIKILINK_RE.exec(s);
  const target = m?.[1] ? (m[1].trim().split('/').pop() ?? '') : s;
  return target.replace(/\.md$/, '').toLowerCase();
}

/** Array, `[a, "b"]` string or single value → list of link targets. */
export function asList(v: unknown): string[] {
  if (Array.isArray(v))
    return v
      .filter((x): x is string => typeof x === 'string')
      .map(linkTarget)
      .filter(Boolean);
  if (typeof v !== 'string' || !v.trim()) return [];
  const s = v.trim();
  const inner = s.startsWith('[') && s.endsWith(']') && !WIKILINK_RE.test(s) ? s.slice(1, -1) : s;
  return (inner.match(/\[\[[^\]]+\]\]|[^,]+/g) ?? []).map(linkTarget).filter(Boolean);
}
