// What ran on the Mac: processes mac-watcher flagged (background jobs left by
// Claude sessions, CPU hogs, heavy downloads) and the day's top apps by CPU
// time, network and memory.

import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { clockOn, fmtSec, type JournalDay } from '@/lib/journal';

const REASON: Record<string, string> = { claude: 'z sesji Claude', cpu: 'CPU', net: 'sieć' };
const num = 'text-right font-mono tabular-nums';

function TopList({ title, rows }: { title: string; rows: { name: string; value: string }[] }) {
  return (
    <div className="min-w-0 flex-1 rounded-lg border bg-card p-3">
      <h4 className="mb-2 text-xs font-medium">{title}</h4>
      {rows.length ? (
        <ol className="space-y-1 font-mono text-xs">
          {rows.map((r) => (
            <li key={r.name} className="flex justify-between gap-2">
              <span className="truncate">{r.name}</span>
              <span className="shrink-0 text-muted-foreground tabular-nums">{r.value}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-xs text-muted-foreground">brak próbek</p>
      )}
    </div>
  );
}

export function ProcessPanel({ day }: { day: JournalDay }) {
  const { apps, procs } = day;
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 md:flex-row">
        <TopList
          title="CPU (czas procesora)"
          rows={apps.cpu.slice(0, 6).map((a) => ({ name: a.name, value: fmtSec(a.cpu_s) }))}
        />
        <TopList
          title="Sieć"
          rows={apps.net.slice(0, 6).map((a) => ({ name: a.name, value: `${a.mb.toFixed(1)} MB` }))}
        />
        <TopList
          title="Pamięć (szczyt)"
          rows={apps.mem.slice(0, 6).map((a) => ({ name: a.name, value: `${Math.round(a.rss_mb)} MB` }))}
        />
      </div>
      <div className="rounded-lg border bg-card">
        <h4 className="px-3 pt-3 text-xs font-medium">W tle i ciężkie procesy</h4>
        {procs.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-36">Godziny</TableHead>
                <TableHead>Proces</TableHead>
                <TableHead>Dlaczego</TableHead>
                <TableHead>Sesja</TableHead>
                <TableHead className={num}>CPU</TableHead>
                <TableHead className={num}>Sieć</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {procs.map((p) => (
                <TableRow key={`${p.name}:${p.started}`}>
                  <TableCell className="font-mono text-muted-foreground">
                    {clockOn(p.started, day.day)}–{p.ended ? clockOn(p.ended, day.day) : 'trwa'}
                  </TableCell>
                  <TableCell className="max-w-lg">
                    <div className="font-mono">{p.name}</div>
                    <div className="truncate font-mono text-xs text-muted-foreground" title={p.cmd}>
                      {p.cmd}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{REASON[p.reason] ?? p.reason}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {p.session_name || p.session_id?.slice(0, 8) || '—'}
                  </TableCell>
                  <TableCell className={num}>{p.cpu_s == null ? '—' : fmtSec(p.cpu_s)}</TableCell>
                  <TableCell className={num}>{p.net_mb ? `${p.net_mb} MB` : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="p-3 text-xs text-muted-foreground">
            Nic nie działało w tle dłużej niż 2 min ani nie zajmowało mocno CPU/sieci.
          </p>
        )}
      </div>
    </div>
  );
}
