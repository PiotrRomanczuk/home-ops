// Contract for POST /api/storage/sync — the vault storage register
// (2-Obszary/mapy/miejsca/*.md) mirrored by planner-sync
// (agents/elitedesk/storage_md.py). Pure validation, no DB, so it is
// unit-testable without Postgres. See docs/adr/2026-11-12-storage-places.md.

export const STANY = ['aktywne', 'usuniete'] as const;
export const PORZADEK = ['ok', 'do-poprawy', 'problem', 'niesprawdzone'] as const;
export const BACKUP = ['ok', 'do-poprawy', 'problem', 'niesprawdzone', 'nie-wymaga', 'brak-oceny'] as const;

const MAX_PLACES = 500;
const MAX_ID = 9999;
const MAX_NAME = 200;
const MAX_TEXT = 1000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export interface PlaceInput {
  id: number;
  nazwa: string;
  gdzie: string | null;
  sciezka: string | null;
  rola: string | null;
  stan: (typeof STANY)[number];
  porzadek: (typeof PORZADEK)[number];
  backup: (typeof BACKUP)[number];
  sprawdzone: string | null;
  test_odtworzenia: string | null;
  sprawdzenie: string | null;
  problem: string | null;
  note_path: string;
  updated_at: string | null;
  raw_frontmatter: Record<string, unknown>;
}

export interface PlacesPayload {
  places: PlaceInput[];
  rejected: Array<{ index: number; reason: string }>;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

function isRealDate(s: string): boolean {
  return DATE_RE.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
}

/** Missing or empty → null; wrong type or too long → undefined (reject). */
function optText(v: unknown, max: number): string | null | undefined {
  if (v === undefined || v === null || v === '') return null;
  if (typeof v !== 'string' || v.length > max) return undefined;
  return v.trim() || null;
}

function optDate(v: unknown): string | null | undefined {
  if (v === undefined || v === null || v === '') return null;
  return typeof v === 'string' && isRealDate(v) ? v : undefined;
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[], fallback: T): T | undefined {
  if (v === undefined || v === null || v === '') return fallback;
  return allowed.includes(v as T) ? (v as T) : undefined;
}

/** Returns the valid place, or the reason it was rejected. */
export function parsePlace(raw: unknown): PlaceInput | string {
  if (!isObj(raw)) return 'not an object';
  const id = raw.id;
  if (typeof id !== 'number' || !Number.isInteger(id) || id < 1 || id > MAX_ID) return 'bad id';
  const nazwa = optText(raw.nazwa, MAX_NAME);
  if (!nazwa) return 'nazwa required';
  const notePath = optText(raw.note_path, MAX_NAME);
  if (!notePath) return 'note_path required';
  const stan = oneOf(raw.stan, STANY, 'aktywne');
  const porzadek = oneOf(raw.porzadek, PORZADEK, 'niesprawdzone');
  const backup = oneOf(raw.backup, BACKUP, 'brak-oceny');
  if (!stan || !porzadek || !backup) return 'bad status value';
  const texts = {
    gdzie: optText(raw.gdzie, MAX_NAME),
    sciezka: optText(raw.sciezka, MAX_TEXT),
    rola: optText(raw.rola, MAX_TEXT),
    sprawdzenie: optText(raw.sprawdzenie, MAX_TEXT),
    problem: optText(raw.problem, MAX_TEXT),
  };
  if (Object.values(texts).includes(undefined)) return 'bad text field';
  const dates = {
    sprawdzone: optDate(raw.sprawdzone),
    test_odtworzenia: optDate(raw.test_odtworzenia),
    updated_at: optDate(raw.updated_at),
  };
  if (Object.values(dates).includes(undefined)) return 'bad date';
  return {
    id,
    nazwa,
    stan,
    porzadek,
    backup,
    note_path: notePath,
    ...(texts as Record<keyof typeof texts, string | null>),
    ...(dates as Record<keyof typeof dates, string | null>),
    raw_frontmatter: isObj(raw.raw_frontmatter) ? raw.raw_frontmatter : {},
  };
}

/** The whole POST body: `{places: [...]}`. A string is a 400-level error. */
export function parsePlaces(body: unknown): PlacesPayload | string {
  const raw = isObj(body) ? body.places : undefined;
  if (!Array.isArray(raw)) return 'places array required';
  if (raw.length > MAX_PLACES) return `too many places (max ${MAX_PLACES})`;
  const places: PlaceInput[] = [];
  const rejected: PlacesPayload['rejected'] = [];
  const seen = new Set<number>();
  raw.forEach((item, index) => {
    const place = parsePlace(item);
    if (typeof place === 'string') rejected.push({ index, reason: place });
    else if (seen.has(place.id)) rejected.push({ index, reason: `duplicate id ${place.id}` });
    else {
      seen.add(place.id);
      places.push(place);
    }
  });
  return { places, rejected };
}
