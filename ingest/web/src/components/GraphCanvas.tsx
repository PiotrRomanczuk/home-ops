// One canvas for both map views: lays the spec out with ELK, then renders it.
// Layout runs again only when the graph's structure changes (filter toggle,
// new or removed nodes) and then re-fits the view; a data refresh that only
// moves pressure / health, or a selection, just re-flags the existing boxes.

import '@xyflow/react/dist/style.css';
import { Background, Controls, ReactFlow } from '@xyflow/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { structureKeyOf, toFlow } from '@/lib/flow';
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
  const [layout, setLayout] = useState<{ key: string; boxes: Map<string, Box>; version: number } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const structureKey = structureKeyOf(spec);
  const specRef = useRef(spec);
  specRef.current = spec;

  useEffect(() => {
    let isCurrent = true;
    setLayoutError(null);
    layoutSpec(specRef.current)
      .then((boxes) => {
        if (isCurrent) setLayout((prev) => ({ key: structureKey, boxes, version: (prev?.version ?? 0) + 1 }));
      })
      .catch((err: unknown) => {
        if (isCurrent) setLayoutError(String(err));
      });
    return () => {
      isCurrent = false;
    };
  }, [structureKey]);

  const flow = useMemo(
    () => (layout?.key === structureKey ? toFlow(spec, layout.boxes, highlight, selected) : null),
    [layout, structureKey, spec, highlight, selected],
  );

  if (layoutError)
    return (
      <div className="grid h-full place-items-center text-sm text-bad">Nie udało się ułożyć mapy: {layoutError}</div>
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
