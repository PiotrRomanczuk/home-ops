// Shapes of GET /api/map and GET /api/pressure (ingest/src/map-model.ts,
// pressure-model.ts). Same origin: the viewer cookie from the console login
// rides along; a 401 sends the browser to that login.

export type NodeKind = 'project' | 'external' | 'host';
export type EdgeKind = 'depends_on' | 'feeds' | 'runs_on';

export interface MapNode {
  id: string;
  kind: NodeKind;
  label: string;
  status: string | null;
  verdict: string | null;
  health: string | null;
  stream: string | null;
  summary: string | null;
  hosts: string[];
  dependents: string[];
  pressure: number | null;
}

export interface MapEdge {
  from: string;
  to: string;
  kind: EdgeKind;
}

export interface MapProcess {
  slug: string;
  title: string;
  lanes: string[];
  warnings: string[];
}

export interface MapResponse {
  nodes: MapNode[];
  edges: MapEdge[];
  processes: MapProcess[];
}

export interface PressureRow {
  slug: string;
  title: string;
  status: string | null;
  verdict: string | null;
  stream: string | null;
  health: string | null;
  score: number;
  base: number;
  blast: number;
  statusWeight: number;
  dependents: string[];
  parts: {
    tasks: { red: number; money: number; other: number; unclassed: number; points: number };
    pain: { n: number; points: number };
    gaps: { n: number; ids: string[]; points: number; hasBlueprint: boolean };
    issues: { open: number; bugs: number; points: number };
    runtime: { errorPatterns: number; ciFailed: boolean; down: boolean; points: number };
  };
}

export interface PressureResponse {
  projects: PressureRow[];
  weights: Record<string, unknown>;
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: 'same-origin' });
  if (r.status === 401) {
    window.location.href = '/login';
    throw new Error('unauthorized');
  }
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const fetchMap = () => getJson<MapResponse>('/api/map');
export const fetchPressure = () => getJson<PressureResponse>('/api/pressure');
