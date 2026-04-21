import { useMemo } from 'react';
import { ReactFlow, Background, Controls, ReactFlowProvider } from '@xyflow/react';
import { Handle, Position } from '@xyflow/react';
import { Paper, Text, Badge, Group } from '@mantine/core';
import '@xyflow/react/dist/style.css';
import jsYaml from 'js-yaml';

// ─── Clab node shape ────────────────────────────────────────────────────────
function ClabNode({ data }) {
  return (
    <Paper
      withBorder
      p="xs"
      radius="sm"
      style={{
        minWidth: 130,
        background: 'var(--mantine-color-dark-7)',
        borderColor: 'var(--mantine-color-cyan-8)',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: '#555' }} />
      <Group gap={4} justify="center" wrap="nowrap">
        <Text size="xs" fw={600} truncate style={{ maxWidth: 110 }}>{data.label}</Text>
      </Group>
      {data.kind && (
        <Badge size="xs" variant="dot" color="cyan" mt={2} display="block" ta="center">
          {data.kind}
        </Badge>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: '#555' }} />
    </Paper>
  );
}

const NODE_TYPES = { clabNode: ClabNode };

// ─── Layout: arrange nodes in a circle ──────────────────────────────────────
function circleLayout(nodeIds, radius = 220) {
  const n = nodeIds.length;
  const cx = radius + 80;
  const cy = radius + 40;
  return nodeIds.map((id, i) => ({
    id,
    x: cx + radius * Math.cos((2 * Math.PI * i) / n - Math.PI / 2),
    y: cy + radius * Math.sin((2 * Math.PI * i) / n - Math.PI / 2),
  }));
}

// ─── Parse clab YAML into React Flow nodes + edges ──────────────────────────
function parseTopology(yamlText) {
  let doc;
  try {
    doc = jsYaml.load(yamlText);
  } catch {
    return { nodes: [], edges: [] };
  }

  const topo = doc?.topology;
  if (!topo) return { nodes: [], edges: [] };

  const nodeMap = topo.nodes || {};
  const links = topo.links || [];
  const nodeIds = Object.keys(nodeMap);
  const positions = circleLayout(nodeIds);
  const posMap = Object.fromEntries(positions.map(p => [p.id, { x: p.x, y: p.y }]));

  const rfNodes = nodeIds.map(id => ({
    id,
    type: 'clabNode',
    position: posMap[id],
    data: {
      label: id,
      kind: nodeMap[id]?.kind ?? '',
    },
  }));

  const rfEdges = [];
  links.forEach((link, i) => {
    const endpoints = link.endpoints || [];
    if (endpoints.length >= 2) {
      const src = endpoints[0].split(':')[0];
      const tgt = endpoints[1].split(':')[0];
      const srcIface = endpoints[0].split(':')[1] ?? '';
      const tgtIface = endpoints[1].split(':')[1] ?? '';
      rfEdges.push({
        id: `e${i}`,
        source: src,
        target: tgt,
        label: srcIface && tgtIface ? `${srcIface} ↔ ${tgtIface}` : undefined,
        style: { stroke: 'var(--mantine-color-cyan-7)', strokeWidth: 1.5 },
        labelStyle: { fill: '#aaa', fontSize: 10 },
        labelBgStyle: { fill: 'var(--mantine-color-dark-7)' },
      });
    }
  });

  return { nodes: rfNodes, edges: rfEdges };
}

// ─── Public component ────────────────────────────────────────────────────────
export function TopologyGraph({ yamlContent, height = 420 }) {
  const { nodes, edges } = useMemo(() => parseTopology(yamlContent || ''), [yamlContent]);

  if (!nodes.length) {
    return (
      <Text size="sm" c="dimmed" ta="center" py="xl">
        No topology nodes found. Ensure the YAML has a <code>topology.nodes</code> section.
      </Text>
    );
  }

  return (
    <ReactFlowProvider>
      <div style={{ height, background: 'var(--mantine-color-dark-8)', borderRadius: 6, overflow: 'hidden' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          colorMode="dark"
          nodesConnectable={false}
          nodesDraggable={true}
          elementsSelectable={false}
        >
          <Background variant="dots" gap={16} size={1} color="rgba(255,255,255,0.07)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </ReactFlowProvider>
  );
}
