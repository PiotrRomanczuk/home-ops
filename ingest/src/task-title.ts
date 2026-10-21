// One-line titles for vault task lines. Vault Now items grow into paragraphs
// (history, paths, PR numbers); the digest email and the "Dziś" tab show only
// the head of the line and keep the full text as a tooltip / in the vault.

/** "Deploy X to the Pi (why…) — long explanation…" → "Deploy X to the Pi" */
export function titleOf(line: string): string {
  const bare = line.replace(/\s*\([^)]*\)/g, '');
  const cut = (bare.split(/\s+[—–-]\s+|\.\s/)[0] ?? bare).replace(/`/g, '').trim();
  return cut.length > 110 ? `${cut.slice(0, 107)}…` : cut;
}

/** titleOf + vault noise: struck-out parts, bold markers, the entry date. */
export function taskTitle(line: string): string {
  const clean = line
    .replace(/~~[^~]*~~/g, '')
    .replace(/\*\*/g, '')
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, target: string, alias?: string) => (alias ?? target).trim())
    // a leading entry date, also after the class emoji / size ("🔴 S 2026-10-19 STR-10 …")
    .replace(/^((?:\S{1,3}\s+){0,3})\d{4}-\d{2}-\d{2}:?\s+/u, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  return titleOf(clean) || titleOf(line);
}
