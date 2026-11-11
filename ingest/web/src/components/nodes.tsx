// Custom React Flow nodes: project card, external service pill, and the
// cluster container (a stream in the ecosystem view, a host in the infra view).

import { Handle, type NodeProps, type NodeTypes, Position } from '@xyflow/react';
import { Layers, Server } from 'lucide-react';
import type { ClusterFlowNode, ExternalFlowNode, ProjectFlowNode } from '@/lib/flow';
import { cn } from '@/lib/utils';
import { PressureBadge, STATUS_BORDER } from './status';

const HANDLE = 'opacity-0';

function ProjectNode({ data }: NodeProps<ProjectFlowNode>) {
  const n = data.node;
  return (
    <div
      className={cn(
        'flex h-16 w-[196px] cursor-pointer flex-col justify-between rounded-md border border-l-4 bg-card px-3 py-2 font-mono text-xs shadow-sm transition-opacity',
        STATUS_BORDER[n.status ?? 'dormant'],
        data.isDimmed && 'opacity-20',
        data.isSelected && 'ring-2 ring-primary',
      )}
    >
      <Handle type="target" position={Position.Left} className={HANDLE} />
      <div className="flex items-center gap-1.5">
        <span className="truncate font-semibold text-foreground">{n.label}</span>
        <span className="ml-auto text-sm leading-none">{n.health}</span>
      </div>
      <div className="flex items-center gap-2 text-muted-foreground">
        <span>{n.status ?? '—'}</span>
        {n.dependents.length > 0 && (
          <span className="text-warn" title={`Zależy od niego: ${n.dependents.join(', ')}`}>
            ⚠ {n.dependents.length}
          </span>
        )}
        <PressureBadge value={n.pressure} className="ml-auto" />
      </div>
      <Handle type="source" position={Position.Right} className={HANDLE} />
    </div>
  );
}

function ExternalNode({ data }: NodeProps<ExternalFlowNode>) {
  const n = data.node;
  return (
    <div
      className={cn(
        'flex h-10 w-[196px] cursor-pointer items-center justify-center gap-2 rounded-full border border-dashed border-external bg-background px-3 font-mono text-xs text-muted-foreground transition-opacity',
        data.isDimmed && 'opacity-20',
        data.isSelected && 'ring-2 ring-primary',
      )}
    >
      <Handle type="target" position={Position.Left} className={HANDLE} />
      <span className="truncate">{n.label}</span>
      {n.dependents.length > 0 && <span className="shrink-0 text-warn">⚠ {n.dependents.length}</span>}
      <Handle type="source" position={Position.Right} className={HANDLE} />
    </div>
  );
}

function ClusterNode({ data }: NodeProps<ClusterFlowNode>) {
  const Icon = data.isHost ? Server : Layers;
  return (
    <div
      className={cn(
        'h-full w-full rounded-lg border border-dashed bg-card/30 transition-opacity',
        data.isHost ? 'border-warm/50' : 'border-border',
        data.isDimmed && 'opacity-30',
        data.isSelected && 'border-solid border-primary',
      )}
    >
      <div className="flex cursor-pointer items-center gap-1.5 px-3 pt-2.5 font-mono text-xs uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" />
        {data.label}
      </div>
    </div>
  );
}

export const NODE_TYPES: NodeTypes = { project: ProjectNode, external: ExternalNode, cluster: ClusterNode };
