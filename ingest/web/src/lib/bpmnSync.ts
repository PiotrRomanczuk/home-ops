// When does a vault copy arriving from the API replace what the editor shows?
// Pure, so the rules are testable without bpmn-js.

export type ImportAction = 'import' | 'ask' | 'skip';

export interface ImportInput {
  /** bpmn_hash of the copy that just arrived. */
  incoming: string;
  /** Last bpmn_hash this editor has already decided on (null before the first load). */
  seen: string | null;
  /** Hash of the vault version the editor's content derives from (loaded or saved by us). */
  base: string | null;
  /** Unsaved edits in the editor. */
  isDirty: boolean;
}

export function decideImport({ incoming, seen, base, isDirty }: ImportInput): ImportAction {
  if (incoming === seen) return 'skip'; // a refetch of what we already looked at
  if (incoming === base) return 'skip'; // our own save has reached the vault
  return isDirty ? 'ask' : 'import';
}

/** sha256 hex of the text as UTF-8 — the same digest planner-sync stores as `bpmn_hash`. */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}
