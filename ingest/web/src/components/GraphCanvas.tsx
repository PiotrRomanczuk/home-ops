// One canvas for both map views: lays the spec out with ELK, then renders it.
// Layout runs again only when the spec changes (data refresh, filter toggle)
// and each new layout re-fits the view; selection just re-flags nodes.

import '@xyflow/react/dist/style.css';
import { Background, Controls, ReactFlow } from '@xyflow/react';
import { useEffect, useMemo, useState } from 'react';
import { toFlow } from '@/lib/flow';
import type { GraphSpec } from '@/lib/graph';
import { type Box, layoutSpec } from '@/lib/layout';
import { Legend } from './Legend';
import { NODE_TYPES } from './nodes';

interface Props {
  spec: GraphSpec;
  selected: string | null;
  highlight: Set<string> | null;
  onSelect: (id: string | null) => void;
}

export function GraphCanvas({ spec, selected, highlight, onSelect }: Props) {
  const [layout, setLayout] = useState<{ spec: GraphSpec; boxes: Map<string, Box>; version: number } | null>(null);

  useEffect(() => {
    let isCurrent = true;
    layoutSpec(spec).then((boxes) => {
      if (isCurrent) setLayout((prev) => ({ spec, boxes, version: (prev?.version ?? 0) + 1 }));
    });
    return () => {
      isCurrent = false;
    };
  }, [spec]);

  const flow = useMemo(
    () => (layout ? toFlow(layout.spec, layout.boxes, highlight, selected) : null),
    [layout, highlight, selected],
  );

  if (!flow) return <div className="grid h-full place-items-center text-sm text-muted-foreground">Układam mapę…</div>;
  if (!flow.nodes.length)
    return (
      <div className="grid h-full place-items-center text-sm text-muted-foreground">Brak węzłów do pokazania.</div>
    );

  return (
    <ReactFlow
      key={layout?.version}
      nodes={flow.nodes}
      edges={flow.edges}
      nodeTypes={NODE_TYPES}
      colorMode="dark"
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.15}
      nodesDraggable={false}
      nodesConnectable={false}
      onNodeClick={(_, n) => onSelect(n.id)}
      onPaneClick={() => onSelect(null)}
    >
      <Legend />
      <Background gap={24} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
