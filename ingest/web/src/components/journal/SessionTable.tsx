// The day's Claude sessions as rows; the selected one unfolds into what
// happened inside it (prompts, commands, edits, PRs …) from /api/claude/events.

import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  clock,
  clockOn,
  EVENT_LIMIT,
  eventsNotice,
  fetchEvents,
  fmtMin,
  type JournalSession,
  today,
} from '@/lib/journal';
import { cn } from '@/lib/utils';

interface Props {
  sessions: JournalSession[];
  day: string;
  selected: string | null;
  onSelect: (sessionId: string | null) => void;
}

const num = 'text-right font-mono tabular-nums';
const KIND_LABEL: Record<string, string> = {
  prompt: 'prompt',
  bash: 'bash',
  edit: 'edycja',
  agent: 'agent',
  skill: 'skill',
  mcp: 'mcp',
  git: 'git',
  pr: 'PR',
  compact: 'kompakcja',
  summary: 'podsum.',
  error: 'błąd',
};

function Events({ host, session, day }: { host: string; session: string; day: string }) {
  const q = useQuery({ queryKey: ['events', host, session], queryFn: () => fetchEvents(host, session) });
  if (q.isLoading) return <p className="p-3 text-xs text-muted-foreground">Ładuję zdarzenia…</p>;
  if (q.error) return <p className="p-3 text-xs text-bad">Nie udało się pobrać zdarzeń: {String(q.error)}</p>;
  const all = q.data?.events ?? [];
  // A session can span days (resumed later): show what happened on this one.
  const events = all.filter((e) => today(new Date(e.ts)) === day);
  const notice = eventsNotice(all.length, events.length);
  if (notice === 'truncated-empty')
    return (
      <p className="p-3 text-xs text-bad">
        Zdarzeń z tego dnia nie ma wśród pierwszych {EVENT_LIMIT} zdarzeń sesji (lista ucięta)
      </p>
    );
  if (notice === 'empty') return <p className="p-3 text-xs text-muted-foreground">Brak zdarzeń z tego dnia</p>;
  return (
    <ol className="max-h-96 space-y-1 overflow-auto p-3 font-mono text-xs">
      {events.slice(0, 400).map((e) => (
        <li key={e.uuid} className="flex gap-2">
          <span className="w-12 shrink-0 text-muted-foreground">{clock(e.ts)}</span>
          <Badge variant={e.kind === 'error' ? 'destructive' : 'outline'} className="w-20 shrink-0 justify-center">
            {KIND_LABEL[e.kind] ?? e.kind}
          </Badge>
          <span className={cn('min-w-0 whitespace-pre-wrap break-words', e.kind === 'prompt' && 'text-foreground')}>
            {e.text.length > 400 ? `${e.text.slice(0, 400)}…` : e.text}
          </span>
        </li>
      ))}
      {notice === 'truncated' && (
        <li className="text-bad">lista ucięta, pokazano pierwsze {EVENT_LIMIT} zdarzeń sesji</li>
      )}
      {events.length > 400 && <li className="text-muted-foreground">… i {events.length - 400} więcej</li>}
    </ol>
  );
}

export function SessionTable({ sessions, day, selected, onSelect }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-28">Godziny</TableHead>
          <TableHead>Sesja</TableHead>
          <TableHead>Projekt</TableHead>
          <TableHead>Gdzie</TableHead>
          <TableHead className={num}>Prompty</TableHead>
          <TableHead className={num}>Akcje</TableHead>
          <TableHead className={num}>Aktywnie</TableHead>
          <TableHead className={num}>PR (sesja)</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sessions.flatMap((s) => {
          const open = selected === s.session_id;
          const row = (
            <TableRow
              key={`${s.host}:${s.session_id}`}
              onClick={() => onSelect(open ? null : s.session_id)}
              className={cn('cursor-pointer', open && 'bg-muted')}
            >
              <TableCell className="font-mono text-muted-foreground">
                {clockOn(s.first_ts, day)}–{clockOn(s.last_ts, day)}
              </TableCell>
              <TableCell className="max-w-md truncate">
                {s.live_status && <span className="mr-1.5 inline-block size-2 rounded-full bg-good" title="trwa" />}
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect(open ? null : s.session_id);
                  }}
                  className="max-w-full truncate text-left"
                >
                  {s.title ?? s.session_id.slice(0, 8)}
                </button>
              </TableCell>
              <TableCell className="font-mono">{s.project_slug ?? '—'}</TableCell>
              <TableCell className="font-mono text-muted-foreground">
                {s.host === 'mac' ? s.surface : `${s.host} · ${s.surface}`}
              </TableCell>
              <TableCell className={num}>{s.prompts_day}</TableCell>
              <TableCell className={num}>{s.actions_day}</TableCell>
              <TableCell className={num}>{fmtMin(s.active_min)}</TableCell>
              <TableCell className={num}>{s.prs.length || ''}</TableCell>
            </TableRow>
          );
          if (!open) return [row];
          return [
            row,
            <TableRow key={`${s.session_id}:events`} className="hover:bg-transparent">
              <TableCell colSpan={8} className="bg-background p-0">
                <Events host={s.host} session={s.session_id} day={day} />
              </TableCell>
            </TableRow>,
          ];
        })}
      </TableBody>
    </Table>
  );
}
