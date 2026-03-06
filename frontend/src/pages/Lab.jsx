import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Box, Group, Title, Text, LoadingOverlay, Badge, Loader, ActionIcon } from '@mantine/core';
import { IconCheck } from '@tabler/icons-react';
import {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    useReactFlow,
    applyNodeChanges,
    applyEdgeChanges,
    addEdge
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// Add custom styles for selection
const selectionStyles = `
  .react-flow__edge.selected .react-flow__edge-path {
    stroke: var(--mantine-color-cyan-6) !important;
    stroke-width: 3 !important;
    filter: drop-shadow(0 0 5px var(--mantine-color-cyan-6));
  }
  .react-flow__node.selected > div {
    border-color: var(--mantine-color-cyan-6) !important;
    box-shadow: 0 0 15px rgba(0, 188, 212, 0.4) !important;
  }
`;

import { getNodes, getVMs, getContainers } from '../api/proxmox';
import { getTopologies, getTopology, saveTopology } from '../api/topology';
import TopologySidebar from '../features/topology/components/TopologySidebar';
import ResourceNode from '../features/topology/components/nodes/ResourceNode';

const nodeTypes = {
    resource: ResourceNode
};

// Inner component to access the useReactFlow hook
function LabCanvas({ allResources, isLoading }) {
    const [nodes, setNodes] = useState([]);
    const [edges, setEdges] = useState([]);
    const { screenToFlowPosition, fitView } = useReactFlow();
    const queryClient = useQueryClient();
    const [isSaving, setIsSaving] = useState(false);
    const saveTimerRef = useRef(null);

    // 1. Load existing topology
    const { data: topologyData, isLoading: isTopoLoading } = useQuery({
        queryKey: ['topology'],
        queryFn: async () => {
            const list = await getTopologies();
            if (list.length > 0) {
                return getTopology(list[0].id);
            }
            return null;
        }
    });

    // Initialize nodes/edges from DB
    useEffect(() => {
        if (topologyData) {
            const mappedNodes = topologyData.nodes.map(n => ({
                id: n.id,
                type: n.type,
                position: { x: n.pos_x, y: n.pos_y },
                data: n.data
            }));
            const mappedEdges = topologyData.edges.map(e => ({
                id: e.id,
                source: e.source,
                target: e.target,
                sourceHandle: e.source_handle,
                targetHandle: e.target_handle,
                data: e.data,
                style: { stroke: '#ffffff', strokeWidth: 1.5 },
                interactionWidth: 20
            }));
            setNodes(mappedNodes);
            setEdges(mappedEdges);
            // Slight delay to allow nodes to render before fitting
            setTimeout(() => fitView({ padding: 0.2 }), 100);
        }
    }, [topologyData, fitView]);

    // 2. Save Mutation
    const mutation = useMutation({
        mutationFn: saveTopology,
        onSuccess: () => {
            setIsSaving(false);
            queryClient.invalidateQueries({ queryKey: ['topology'] });
        },
        onError: () => setIsSaving(false)
    });

    // 3. Auto-save trigger
    useEffect(() => {
        // Only start auto-saving after initial load
        if (isTopoLoading) return;

        // Skip if everything is empty and we don't have a record yet
        if (nodes.length === 0 && !topologyData?.id) return;

        setIsSaving(true);
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

        saveTimerRef.current = setTimeout(() => {
            const payload = {
                name: topologyData?.name || "Default Lab",
                nodes: nodes.map(n => ({
                    id: n.id,
                    pos_x: n.position.x,
                    pos_y: n.position.y,
                    data: n.data,
                    type: n.type
                })),
                edges: edges.map(e => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                    source_handle: e.sourceHandle,
                    target_handle: e.targetHandle,
                    data: e.data
                }))
            };
            mutation.mutate(payload);
        }, 1500); // 1.5s debounce

        return () => {
            if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        };
    }, [nodes, edges, isTopoLoading]);

    const onNodesChange = useCallback(
        (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
        []
    );
    const onEdgesChange = useCallback(
        (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
        []
    );
    const onConnect = useCallback(
        (params) => setEdges((eds) => addEdge({
            ...params,
            style: { stroke: '#ffffff', strokeWidth: 1.5 },
            interactionWidth: 20
        }, eds)),
        []
    );

    const onDragOver = useCallback((event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
    }, []);

    const onNodesDelete = useCallback(
        (deleted) => {
            setNodes((nds) => nds.filter((node) => !deleted.find((d) => d.id === node.id)));
        },
        []
    );

    const onEdgesDelete = useCallback(
        (deleted) => {
            setEdges((eds) => eds.filter((edge) => !deleted.find((d) => d.id === edge.id)));
        },
        []
    );

    const onDrop = useCallback(
        (event) => {
            event.preventDefault();

            const data = event.dataTransfer.getData('application/reactflow');
            if (!data) return;

            const labData = JSON.parse(data);

            // Prevent duplicate resources on canvas
            if (nodes.some(n => n.data.vmid === labData.vmid)) {
                return;
            }

            const position = screenToFlowPosition({
                x: event.clientX,
                y: event.clientY,
            });

            const newNode = {
                id: `${labData.node}-${labData.type}-${labData.vmid}-${Date.now()}`,
                type: 'resource',
                position,
                data: { ...labData },
            };

            setNodes((nds) => nds.concat(newNode));
        },
        [screenToFlowPosition, nodes]
    );

    const saveStatus = (
        <Group gap="6px">
            {isSaving ? (
                <>
                    <Loader size="8px" color="cyan" />
                    <Text size="10px" c="cyan" fw={500} lts="0.3px">SYNCING...</Text>
                </>
            ) : (
                <>
                    <IconCheck size={12} color="var(--mantine-color-green-6)" />
                    <Text size="10px" c="dimmed" fw={500} lts="0.3px">SYNCED</Text>
                </>
            )}
        </Group>
    );

    return (
        <Box style={{ display: 'flex', flex: 1, gap: 'md', position: 'relative', minHeight: 0 }}>
            <TopologySidebar
                resources={allResources}
                loading={isLoading}
            />

            <Box
                style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    border: '1px solid var(--border)',
                    borderRadius: '12px',
                    background: 'rgba(0,0,0,0.2)',
                    overflow: 'hidden',
                    position: 'relative'
                }}
            >
                <Box
                    style={{
                        position: 'absolute',
                        top: 10,
                        right: 10,
                        zIndex: 10,
                        pointerEvents: 'none'
                    }}
                >
                    {saveStatus}
                </Box>

                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodesDelete={onNodesDelete}
                    onEdgesDelete={onEdgesDelete}
                    onConnect={onConnect}
                    onDragOver={onDragOver}
                    onDrop={onDrop}
                    connectionMode="loose"
                    snapToGrid
                    snapGrid={[15, 15]}
                    fitView
                    colorMode="dark"
                >
                    <Background variant="dots" gap={15} size={1} color="rgba(255,255,255,0.1)" />
                    <Controls />
                </ReactFlow>
            </Box>
        </Box>
    );
}

export default function Lab() {
    // Fetch resources
    const nodesQ = useQuery({ queryKey: ['nodes'], queryFn: getNodes });
    const pveNodes = nodesQ.data || [];

    // For simplicity in the initial lab view, we'll fetch from the first node
    const activeNode = pveNodes[0]?.node;

    const vmsQ = useQuery({
        queryKey: ['vms', activeNode],
        queryFn: () => getVMs(activeNode),
        enabled: !!activeNode
    });
    const lxcQ = useQuery({
        queryKey: ['lxc', activeNode],
        queryFn: () => getContainers(activeNode),
        enabled: !!activeNode
    });

    const allResources = useMemo(() => {
        const vms = (vmsQ.data || []).map(vm => ({ ...vm, type: 'vm', node: activeNode }));
        const lxcs = (lxcQ.data || []).map(lxc => ({ ...lxc, type: 'lxc', node: activeNode }));
        return [...vms, ...lxcs];
    }, [vmsQ.data, lxcQ.data, activeNode]);

    const isLoading = nodesQ.isLoading || vmsQ.isLoading || lxcQ.isLoading;

    return (
        <ReactFlowProvider>
            <style>{selectionStyles}</style>
            <Box style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
                <Group justify="space-between" mb="lg">
                    <Box>
                        <Title order={2} style={{ color: 'var(--text)' }}>Lab Topology</Title>
                        <Text c="dimmed" size="sm">Design and visualize your infrastructure topology</Text>
                    </Box>
                </Group>

                <LabCanvas allResources={allResources} isLoading={isLoading} />
            </Box>
        </ReactFlowProvider>
    );
}
