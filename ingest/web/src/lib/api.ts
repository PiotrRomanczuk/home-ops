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

// BPMN processes (migration 029) and saves back to the vault (030).
export interface ProcessDetail {
  slug: string;
  title: string;
  trigger: string | null;
  schedule: string | null;
  summary: string | null;
  projects: string[];
  lanes: string[];
  bpmn_xml: string | null;
  bpmn_hash: string | null;
  path: string | null;
  warnings: string[];
}

export type WriteStatus = 'queued' | 'applied' | 'conflict' | 'failed';

export interface ProcessWrite {
  id: number;
  slug: string;
  status: WriteStatus;
  error: string | null;
}

export const fetchProcess = (slug: string) =>
  getJson<{ process: ProcessDetail }>(`/api/processes/${encodeURIComponent(slug)}`).then((r) => r.process);

export const fetchWrite = (slug: string, id: number) =>
  getJson<{ write: ProcessWrite }>(`/api/processes/${encodeURIComponent(slug)}/writes/${id}`).then((r) => r.write);

export async function saveProcess(slug: string, bpmnXml: string, baseHash: string): Promise<ProcessWrite> {
  const r = await fetch(`/api/processes/${encodeURIComponent(slug)}/writes`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bpmn_xml: bpmnXml, base_hash: baseHash }),
  });
  const body = (await r.json().catch(() => ({}))) as { write?: ProcessWrite; error?: string };
  if (!r.ok || !body.write) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body.write;
}
