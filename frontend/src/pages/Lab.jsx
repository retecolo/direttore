import { useState, useMemo, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Box, Group, Title, Text, LoadingOverlay } from '@mantine/core';
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

import { getNodes, getVMs, getContainers } from '../api/proxmox';
import TopologySidebar from '../features/topology/components/TopologySidebar';

// Inner component to access the useReactFlow hook
function LabCanvas({ allResources, isLoading }) {
    const [nodes, setNodes] = useState([]);
    const [edges, setEdges] = useState([]);
    const { screenToFlowPosition } = useReactFlow();

    const onNodesChange = useCallback(
        (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
        []
    );
    const onEdgesChange = useCallback(
        (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
        []
    );
    const onConnect = useCallback(
        (params) => setEdges((eds) => addEdge(params, eds)),
        []
    );

    const onDragOver = useCallback((event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
    }, []);

    const onDrop = useCallback(
        (event) => {
            event.preventDefault();

            const data = event.dataTransfer.getData('application/reactflow');
            if (!data) return;

            const labData = JSON.parse(data);
            const position = screenToFlowPosition({
                x: event.clientX,
                y: event.clientY,
            });

            const newNode = {
                id: `${labData.node}-${labData.type}-${labData.vmid}-${Date.now()}`,
                type: 'default', // Using default node type for Step 3
                position,
                data: { label: `${labData.name} (ID: ${labData.vmid})` },
            };

            setNodes((nds) => nds.concat(newNode));
        },
        [screenToFlowPosition]
    );

    return (
        <Box style={{ display: 'flex', flex: 1, gap: 'md', position: 'relative' }}>
            <TopologySidebar
                resources={allResources}
                loading={isLoading}
            />

            <Box
                style={{
                    flex: 1,
                    border: '1px solid var(--border)',
                    borderRadius: '12px',
                    background: 'rgba(0,0,0,0.2)',
                    overflow: 'hidden',
                    position: 'relative'
                }}
            >
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    onDragOver={onDragOver}
                    onDrop={onDrop}
                    fitView
                    colorMode="dark"
                >
                    <Background variant="dots" gap={12} size={1} color="rgba(255,255,255,0.1)" />
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
