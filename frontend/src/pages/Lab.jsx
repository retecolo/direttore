import { Title, Text, Box } from '@mantine/core';

export default function Lab() {
    return (
        <Box>
            <Title order={2} mb="md">Lab Topology</Title>
            <Text c="dimmed">Canvas for resource visualization and connectivity management goes here.</Text>

            {/* React Flow canvas will be initialized here in Step 3 */}
            <Box
                mt="xl"
                style={{
                    height: '70vh',
                    border: '1px dashed var(--border)',
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: 'rgba(0,0,0,0.05)'
                }}
            >
                <Text size="sm" c="dimmed">Topology Canvas Placeholder</Text>
            </Box>
        </Box>
    );
}
