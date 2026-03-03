import { Box, Text, Stack, Paper, Title, ThemeIcon, ActionIcon, ScrollArea, Group } from '@mantine/core';
import { IconServer, IconBox, IconSearch, IconChevronRight, IconChevronDown } from '@tabler/icons-react';
import { useState } from 'react';

export default function TopologySidebar({ resources, loading }) {
    const [expanded, setExpanded] = useState(true);

    const onDragStart = (event, nodeData) => {
        event.dataTransfer.setData('application/reactflow', JSON.stringify(nodeData));
        event.dataTransfer.effectAllowed = 'move';
    };

    return (
        <Paper
            withBorder
            style={{
                width: expanded ? 280 : 60,
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                transition: 'width 0.2s ease',
                background: 'var(--surface)',
                overflow: 'hidden'
            }}
        >
            <Box p="md" style={{ borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: expanded ? 'space-between' : 'center' }}>
                {expanded && <Title order={6} transform="uppercase" lts="0.5px" c="dimmed">Resources</Title>}
                <ActionIcon variant="subtle" color="gray" onClick={() => setExpanded(!expanded)}>
                    {expanded ? <IconChevronRight size={16} style={{ transform: 'rotate(180deg)' }} /> : <IconChevronRight size={16} />}
                </ActionIcon>
            </Box>

            {expanded && (
                <ScrollArea style={{ flex: 1 }} p="md">
                    {loading ? (
                        <Text size="xs" c="dimmed" ta="center" py="xl">Loading resources...</Text>
                    ) : (
                        <Stack gap="xs">
                            {resources.length === 0 ? (
                                <Text size="xs" c="dimmed" ta="center" py="xl">No resources found</Text>
                            ) : (
                                resources.map((res) => (
                                    <Paper
                                        key={`${res.node}-${res.vmid}`}
                                        withBorder
                                        p="xs"
                                        draggable
                                        onDragStart={(e) => onDragStart(e, {
                                            type: res.type, // 'vm' or 'lxc'
                                            vmid: res.vmid,
                                            name: res.name || res.hostname,
                                            node: res.node,
                                            status: res.status
                                        })}
                                        style={{
                                            cursor: 'grab',
                                            background: 'rgba(255,255,255,0.03)',
                                            userSelect: 'none'
                                        }}
                                    >
                                        <Group gap="sm" wrap="nowrap">
                                            <ThemeIcon
                                                size="sm"
                                                variant="light"
                                                color={res.status === 'running' ? 'cyan' : 'gray'}
                                            >
                                                {res.type === 'vm' ? <IconServer size={14} /> : <IconBox size={14} />}
                                            </ThemeIcon>
                                            <Box style={{ flex: 1, overflow: 'hidden' }}>
                                                <Text size="xs" fw={500} truncate>{res.name || res.hostname}</Text>
                                                <Text size="10px" c="dimmed">ID: {res.vmid} • {res.node}</Text>
                                            </Box>
                                        </Group>
                                    </Paper>
                                ))
                            )}
                        </Stack>
                    )}
                </ScrollArea>
            )}
        </Paper>
    );
}
