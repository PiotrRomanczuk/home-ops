// Gap column formatting: null (GitHub API failed) and partial reads must never
// look like "no blueprint" / "no gaps" (false calm).

import type { PressureRow } from '@/lib/api';

type Gaps = PressureRow['parts']['gaps'];

export const GITHUB_UNAVAILABLE = 'GitHub API niedostępne';

export function gapsDetail(gaps: Gaps): string {
  if (gaps.hasBlueprint === null) return GITHUB_UNAVAILABLE;
  if (!gaps.hasBlueprint) return 'brak blueprintu';
  const list = gaps.ids.length ? `: ${gaps.ids.join(', ')}` : '';
  return `${gaps.n} otwartych${list}${gaps.partial ? ' (częściowo)' : ''}`;
}

export function gapsCell(gaps: Gaps): { text: string; title?: string } {
  if (gaps.hasBlueprint === null) return { text: '?', title: GITHUB_UNAVAILABLE };
  if (!gaps.hasBlueprint) return { text: '—' };
  if (gaps.partial) return { text: `${gaps.n}*`, title: 'odczyt częściowy' };
  return { text: String(gaps.n) };
}
