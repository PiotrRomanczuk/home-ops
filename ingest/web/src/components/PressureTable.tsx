// "Presja" — projects ranked by attention needed. A row opens the side sheet;
// the info button shows the score breakdown in place.

import { Info } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { PressureRow } from '@/lib/api';
import { cn } from '@/lib/utils';
import { PressureBreakdown } from './PressureBreakdown';
import { PressureBadge, StatusDot } from './status';

interface Props {
  rows: PressureRow[];
  selected: string | null;
  onSelect: (id: string) => void;
}

const num = 'text-right font-mono tabular-nums';

export function PressureTable({ rows, selected, onSelect }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">#</TableHead>
          <TableHead>Projekt</TableHead>
          <TableHead className={num}>Wynik</TableHead>
          <TableHead className={num}>🔴 / 💰</TableHead>
          <TableHead className={num}>Pain</TableHead>
          <TableHead className={num}>Luki</TableHead>
          <TableHead className={num}>Issues</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead className={num}>Blast</TableHead>
          <TableHead className="w-10" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => {
          const { tasks, pain, gaps, issues, runtime } = r.parts;
          return (
            <TableRow
              key={r.slug}
              onClick={() => onSelect(r.slug.toLowerCase())}
              className={cn('cursor-pointer', selected === r.slug.toLowerCase() && 'bg-muted')}
            >
              <TableCell className="font-mono text-muted-foreground">{i + 1}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2 font-mono">
                  <StatusDot status={r.status} />
                  <span className="font-medium text-foreground">{r.slug}</span>
                  <span>{r.health}</span>
                  {r.stream && <span className="text-xs text-muted-foreground">{r.stream}</span>}
                </div>
              </TableCell>
              <TableCell className={num}>
                <PressureBadge value={r.score} />
                {!r.score && <span className="text-muted-foreground">0</span>}
              </TableCell>
              <TableCell className={num}>
                {tasks.red} / {tasks.money}
              </TableCell>
              <TableCell className={num}>{pain.n || '—'}</TableCell>
              <TableCell className={num}>{gaps.hasBlueprint ? gaps.n : '—'}</TableCell>
              <TableCell className={num}>
                {issues.open || '—'}
                {issues.bugs > 0 && <span className="text-bad"> ({issues.bugs} bug)</span>}
              </TableCell>
              <TableCell className="space-x-1.5 text-xs">
                {runtime.ciFailed && <span className="text-bad">CI ✗</span>}
                {runtime.down && <span className="text-bad">DOWN</span>}
                {runtime.errorPatterns > 0 && <span className="text-warn">{runtime.errorPatterns} błędy</span>}
              </TableCell>
              <TableCell className={num}>{r.blast > 1 ? `×${r.blast}` : '—'}</TableCell>
              <TableCell onClick={(e) => e.stopPropagation()}>
                <Popover>
                  <PopoverTrigger className="text-muted-foreground hover:text-foreground" aria-label="Rozbicie wyniku">
                    <Info className="size-4" />
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-96">
                    <PressureBreakdown row={r} />
                  </PopoverContent>
                </Popover>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
