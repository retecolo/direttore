import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Box, Group, Title, Text, LoadingOverlay } from '@mantine/core';

// Note: React Flow imports removed until Step 3 to prevent build errors
import { getNodes, getVMs, getContainers } from '../api/proxmox';
import TopologySidebar from '../features/topology/components/TopologySidebar';

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
        <Box style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
            <Group justify="space-between" mb="lg">
                <Box>
                    <Title order={2} style={{ color: 'var(--text)' }}>Lab Topology</Title>
                    <Text c="dimmed" size="sm">Design and visualize your infrastructure topology</Text>
                </Box>
            </Group>

            <Box style={{ display: 'flex', flex: 1, gap: 'md', position: 'relative' }}>
                <LoadingOverlay visible={nodesQ.isLoading && !activeNode} />

                <TopologySidebar
                    resources={allResources}
                    loading={isLoading}
                />

                <Box
                    style={{
                        flex: 1,
                        border: '1px dashed var(--border)',
                        borderRadius: '12px',
                        background: 'rgba(0,0,0,0.1)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center'
                    }}
                >
                    <Text c="dimmed">React Flow Canvas will be initialized here in Step 3</Text>
                </Box>
            </Box>
        </Box>
    );
}
