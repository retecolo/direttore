import { Box, Paper, Text, Group, ThemeIcon, Badge, rem } from '@mantine/core';
import { Handle, Position } from '@xyflow/react';
import { IconServer, IconBox } from '@tabler/icons-react';

export default function ResourceNode({ data }) {
    const isRunning = data.status === 'running';

    return (
        <Paper
            withBorder
            shadow="md"
            p="sm"
            radius="md"
            style={{
                minWidth: 180,
                background: 'var(--surface)',
                border: isRunning ? '1px solid var(--mantine-color-cyan-filled)' : '1px solid var(--border)',
                boxShadow: isRunning ? '0 0 10px rgba(0, 188, 212, 0.2)' : 'none',
                position: 'relative',
            }}
        >
            <Handle type="target" position={Position.Left} style={{ background: '#555' }} />

            <Group gap="sm" wrap="nowrap">
                <ThemeIcon
                    size="lg"
                    variant="light"
                    color={isRunning ? 'cyan' : 'gray'}
                    radius="md"
                >
                    {data.type === 'vm' ? <IconServer size={20} /> : <IconBox size={20} />}
                </ThemeIcon>

                <Box style={{ flex: 1, overflow: 'hidden' }}>
                    <Text size="sm" fw={700} truncate>{data.name}</Text>
                    <Group gap={4} mt={2}>
                        <Badge size="xs" color={isRunning ? 'green' : 'gray'} variant="dot">
                            {data.status}
                        </Badge>
                        <Text size="10px" c="dimmed">ID: {data.vmid}</Text>
                    </Group>
                </Box>
            </Group>

            <Handle type="source" position={Position.Right} style={{ background: '#555' }} />
        </Paper>
    );
}
