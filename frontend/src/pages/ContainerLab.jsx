import { useState, useCallback, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box, Text, Badge, Group, Stack, Table, Button, Loader, Alert,
  Modal, Select, Tabs, Code, ScrollArea, Drawer, ActionIcon,
  FileInput, Tooltip, Divider, ThemeIcon, Paper,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconNetwork, IconPlayerPlay, IconTrash, IconRefresh,
  IconUpload, IconCode, IconHistory, IconInfoCircle,
  IconAlertCircle, IconCheck,
} from '@tabler/icons-react';
import {
  getCLabStatus, listLabs, inspectLab, deployLab, destroyLab,
  listTopologies, getTopology, uploadTopology,
} from '../api/containerlab';

// ─── Status badge helper ────────────────────────────────────────────────────
function ModeBadge({ mode }) {
  const colors = { local: 'teal', ssh: 'blue', rest: 'violet' };
  return (
    <Badge color={colors[mode] || 'gray'} variant="light" size="sm" tt="uppercase">
      {mode}
    </Badge>
  );
}

// ─── Lab detail drawer ──────────────────────────────────────────────────────
function LabDrawer({ labName, opened, onClose }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['clab-inspect', labName],
    queryFn: () => inspectLab(labName),
    enabled: opened && !!labName,
  });

  const containers =
    data?.containers ||
    (Array.isArray(data) ? data : []);

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <ThemeIcon color="cyan" variant="light" size="sm">
            <IconNetwork size={14} />
          </ThemeIcon>
          <Text fw={600}>{labName}</Text>
        </Group>
      }
      position="right"
      size="lg"
    >
      {isLoading && <Loader size="sm" mt="md" />}
      {error && <Alert color="red" title="Inspect error">{error.message}</Alert>}
      {!isLoading && !error && (
        <Stack gap="md">
          <Text size="sm" c="dimmed">{containers.length} node(s)</Text>
          <Table striped highlightOnHover withTableBorder fontSize="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Kind</Table.Th>
                <Table.Th>Image</Table.Th>
                <Table.Th>IPv4</Table.Th>
                <Table.Th>IPv6</Table.Th>
                <Table.Th>State</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {containers.map((c, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{c.name || c.container_name || '—'}</Table.Td>
                  <Table.Td>
                    <Badge size="xs" variant="outline" color="cyan">
                      {c.kind || c.node_kind || '—'}
                    </Badge>
                  </Table.Td>
                  <Table.Td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {c.image || '—'}
                  </Table.Td>
                  <Table.Td ff="mono" fz={11}>{c.ipv4_address || c.management?.ipv4 || '—'}</Table.Td>
                  <Table.Td ff="mono" fz={11}>{c.ipv6_address || c.management?.ipv6 || '—'}</Table.Td>
                  <Table.Td>
                    <Badge
                      size="xs"
                      color={c.state === 'running' ? 'green' : 'gray'}
                    >
                      {c.state || '—'}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
              {containers.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={6} ta="center" c="dimmed">No containers found</Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Stack>
      )}
    </Drawer>
  );
}

// ─── Topology viewer ────────────────────────────────────────────────────────
function TopoViewer({ filename, gitConfigured }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['clab-topo', filename],
    queryFn: () => getTopology(filename),
    enabled: !!filename,
  });

  if (isLoading) return <Loader size="xs" />;
  if (error) return <Alert color="red">{error.message}</Alert>;
  if (!data) return null;

  return (
    <Tabs defaultValue="content">
      <Tabs.List>
        <Tabs.Tab value="content" leftSection={<IconCode size={13} />}>YAML</Tabs.Tab>
        {gitConfigured && (
          <Tabs.Tab value="history" leftSection={<IconHistory size={13} />}>
            History ({data.git_history?.length ?? 0})
          </Tabs.Tab>
        )}
      </Tabs.List>

      <Tabs.Panel value="content" pt="xs">
        <ScrollArea h={400}>
          <Code block fz={11}>{data.content}</Code>
        </ScrollArea>
      </Tabs.Panel>

      {gitConfigured && (
        <Tabs.Panel value="history" pt="xs">
          {data.git_history?.length > 0 ? (
            <Stack gap={4}>
              {data.git_history.map((h) => (
                <Paper key={h.sha} px="sm" py={6} withBorder radius="sm">
                  <Group gap="xs" wrap="nowrap">
                    <Badge size="xs" variant="dot" color="cyan" ff="mono">{h.sha}</Badge>
                    <Text size="xs" truncate>{h.message}</Text>
                    <Text size="xs" c="dimmed" ml="auto" style={{ whiteSpace: 'nowrap' }}>
                      {new Date(h.date).toLocaleDateString()}
                    </Text>
                  </Group>
                </Paper>
              ))}
            </Stack>
          ) : (
            <Text size="sm" c="dimmed" mt="xs">No Git history found for this file.</Text>
          )}
        </Tabs.Panel>
      )}
    </Tabs>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
export default function ContainerLab() {
  const qc = useQueryClient();
  const [deployedLab, setDeployedLab] = useState(null);
  const [inspectTarget, setInspectTarget] = useState(null);
  const [deployOpen, setDeployOpen] = useState(false);
  const [selectedTopo, setSelectedTopo] = useState(null);
  const [selectedTopoView, setSelectedTopoView] = useState(null);
  const [uploadFile, setUploadFile] = useState(null);

  const [deployLogs, setDeployLogs] = useState([]);
  const [deployStatus, setDeployStatus] = useState('idle'); // idle, deploying, success, error
  const logsEndRef = useRef(null);

  useEffect(() => {
    if (deployOpen && logsEndRef.current) {
        logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [deployLogs, deployOpen]);

  const deployWithStreaming = async () => {
    setDeployStatus('deploying');
    setDeployLogs([]);
    let currentStatus = 'deploying';
    
    try {
        const res = await fetch('/api/containerlab/labs/deploy-stream', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({ topo_file: selectedTopo })
        });
        
        if (!res.ok || !res.body) {
           currentStatus = 'error';
           setDeployStatus('error');
           const text = await res.text();
           setDeployLogs(prev => [...prev, `[HTTP Error] ${res.status} ${res.statusText}: ${text}`]);
           return;
        }
        
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while(true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || ''; 
            
            for (const part of parts) {
                 if (part.startsWith('data: ')) {
                      const dataStr = part.substring(6);
                      try {
                          const event = JSON.parse(dataStr);
                          if (event.type === 'log') {
                              setDeployLogs(prev => [...prev, event.line]);
                          } else if (event.type === 'error') {
                              currentStatus = 'error';
                              setDeployStatus('error');
                              setDeployLogs(prev => [...prev, `[ERROR] ${event.message}`]);
                          } else if (event.type === 'success') {
                              currentStatus = 'success';
                              setDeployStatus('success');
                              setDeployLogs(prev => [...prev, `\n\n[SUCCESS] ${event.message}`]);
                          }
                      } catch (e) {
                          setDeployLogs(prev => [...prev, `[Parse Error] ${e.message} on payload: ${dataStr}`]);
                      }
                 }
            }
        }
        
        if (currentStatus === 'deploying') {
            currentStatus = 'success';
            setDeployStatus('success');
            setDeployLogs(prev => [...prev, `[INFO] Stream ended.`]);
        }
    } catch (exc) {
        currentStatus = 'error';
        setDeployStatus('error');
        setDeployLogs(prev => [...prev, `[Network Error] ${exc.message}`]);
    }
    
    qc.invalidateQueries({ queryKey: ['clab-labs'] });
    
    if (currentStatus === 'success') {
        setTimeout(() => {
             setDeployOpen(false);
             setDeployStatus('idle');
             setDeployLogs([]);
             setSelectedTopo(null);
        }, 5000);
    }
  };

  // ── Queries ──
  const statusQ = useQuery({
    queryKey: ['clab-status'],
    queryFn: getCLabStatus,
    refetchInterval: 30000,
  });

  const labsQ = useQuery({
    queryKey: ['clab-labs'],
    queryFn: listLabs,
    refetchInterval: 15000,
  });

  const topoQ = useQuery({
    queryKey: ['clab-topologies'],
    queryFn: listTopologies,
  });

  const gitConfigured = topoQ.data?.git_configured ?? false;
  const mode = statusQ.data?.mode;
  const statusOk = statusQ.data?.ok;

  // ── Mutations ──
  const deployMut = useMutation({
    mutationFn: deployLab,
    onSuccess: (data) => {
      notifications.show({ color: 'green', title: 'Lab deployed', message: data.topo_file });
      qc.invalidateQueries({ queryKey: ['clab-labs'] });
      setDeployOpen(false);
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Deploy failed', message: e.response?.data?.detail || e.message }),
  });

  const destroyMut = useMutation({
    mutationFn: destroyLab,
    onSuccess: (data) => {
      notifications.show({ color: 'orange', title: 'Lab destroyed', message: data.lab_name });
      qc.invalidateQueries({ queryKey: ['clab-labs'] });
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Destroy failed', message: e.response?.data?.detail || e.message }),
  });

  const uploadMut = useMutation({
    mutationFn: uploadTopology,
    onSuccess: (data) => {
      notifications.show({ color: 'green', title: 'Topology uploaded', message: data.filename });
      qc.invalidateQueries({ queryKey: ['clab-topologies'] });
      setUploadFile(null);
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Upload failed', message: e.response?.data?.detail || e.message }),
  });

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['clab-status'] });
    qc.invalidateQueries({ queryKey: ['clab-labs'] });
    qc.invalidateQueries({ queryKey: ['clab-topologies'] });
  }, [qc]);

  // ── Render ──
  return (
    <Box>
      {/* Header */}
      <Group justify="space-between" mb="lg">
        <Box>
          <Group gap="sm" align="center">
            <ThemeIcon color="cyan" variant="light" size="md">
              <IconNetwork size={18} />
            </ThemeIcon>
            <Text fw={700} size="xl">ContainerLab</Text>
            {mode && <ModeBadge mode={mode} />}
            {statusQ.data && (
              <Badge
                color={statusOk ? 'green' : 'red'}
                variant="dot"
                size="sm"
              >
                {statusOk ? 'connected' : 'unreachable'}
              </Badge>
            )}
          </Group>
          <Text size="sm" c="dimmed" mt={2}>Network topology lifecycle management</Text>
        </Box>
        <Group gap="xs">
          <Tooltip label="Refresh">
            <ActionIcon variant="subtle" onClick={refresh} loading={labsQ.isFetching}>
              <IconRefresh size={16} />
            </ActionIcon>
          </Tooltip>
          <Button
            size="xs"
            leftSection={<IconPlayerPlay size={14} />}
            disabled={!statusOk || !topoQ.data?.files?.length}
            onClick={() => setDeployOpen(true)}
          >
            Deploy Lab
          </Button>
        </Group>
      </Group>

      {/* Backend error */}
      {statusQ.data && !statusOk && (
        <Alert color="red" icon={<IconAlertCircle size={16} />} mb="md" title="Backend unreachable">
          {statusQ.data.error || 'The configured clab backend is not responding.'}
        </Alert>
      )}

      {/* Running Labs */}
      <Text fw={600} size="sm" mb="xs" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.05em' }}>
        Running Labs
      </Text>
      {labsQ.isLoading && <Loader size="sm" mb="md" />}
      {labsQ.error && (
        <Alert color="red" mb="md">{labsQ.error.message}</Alert>
      )}
      {!labsQ.isLoading && (
        <Table striped highlightOnHover withTableBorder mb="xl">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Lab Name</Table.Th>
              <Table.Th>Nodes</Table.Th>
              <Table.Th>Topology Path</Table.Th>
              <Table.Th style={{ width: 120 }}>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(labsQ.data || []).map((lab) => (
              <Table.Tr
                key={lab.name}
                style={{ cursor: 'pointer' }}
                onClick={() => setInspectTarget(lab.name)}
              >
                <Table.Td>
                  <Text fw={500} size="sm">{lab.name}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge size="xs" color="cyan" variant="light">
                    {lab.containers?.length ?? '—'} nodes
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed" ff="mono">{lab.lab_path || '—'}</Text>
                </Table.Td>
                <Table.Td onClick={(e) => e.stopPropagation()}>
                  <Group gap={4}>
                    <Tooltip label="Inspect">
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="cyan"
                        onClick={() => setInspectTarget(lab.name)}
                      >
                        <IconInfoCircle size={14} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Destroy">
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="red"
                        loading={destroyMut.isPending && deployedLab === lab.name}
                        onClick={() => {
                          setDeployedLab(lab.name);
                          destroyMut.mutate(lab.name);
                        }}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Tooltip>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {(labsQ.data || []).length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={4} ta="center" c="dimmed" py="lg">
                  No running labs. Deploy a topology to get started.
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      {/* Topology Files */}
      <Group justify="space-between" mb="xs">
        <Text fw={600} size="sm" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.05em' }}>
          Topology Files
          {gitConfigured && (
            <Badge ml="xs" size="xs" color="grape" variant="light">Git-backed</Badge>
          )}
        </Text>
        <Group gap="xs">
          <FileInput
            size="xs"
            placeholder="Upload .yml"
            accept=".yml,.yaml"
            leftSection={<IconUpload size={13} />}
            value={uploadFile}
            onChange={setUploadFile}
            style={{ width: 180 }}
          />
          <Button
            size="xs"
            variant="light"
            disabled={!uploadFile}
            loading={uploadMut.isPending}
            onClick={() => uploadFile && uploadMut.mutate(uploadFile)}
          >
            Upload
          </Button>
        </Group>
      </Group>

      {topoQ.isLoading && <Loader size="sm" />}
      {!topoQ.isLoading && (
        <Stack gap={4} mb="xl">
          {(topoQ.data?.files || []).map((f) => (
            <Paper
              key={f}
              px="md"
              py="sm"
              withBorder
              radius="sm"
              style={{
                cursor: 'pointer',
                borderColor: selectedTopoView === f ? 'var(--mantine-color-cyan-5)' : undefined,
                background: selectedTopoView === f ? 'rgba(0,188,212,0.05)' : undefined,
              }}
              onClick={() => setSelectedTopoView(selectedTopoView === f ? null : f)}
            >
              <Group justify="space-between">
                <Group gap="xs">
                  <IconCode size={14} color="var(--mantine-color-cyan-5)" />
                  <Text size="sm" ff="mono">{f}</Text>
                </Group>
                <Group gap="xs">
                  {gitConfigured && (
                    <Badge size="xs" variant="dot" color="grape">git</Badge>
                  )}
                  <Badge
                    size="xs"
                    variant="light"
                    color="teal"
                    style={{ cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedTopo(f);
                      setDeployOpen(true);
                    }}
                  >
                    Deploy
                  </Badge>
                </Group>
              </Group>
              {selectedTopoView === f && (
                <Box mt="sm">
                  <Divider mb="sm" />
                  <TopoViewer filename={f} gitConfigured={gitConfigured} />
                </Box>
              )}
            </Paper>
          ))}
          {(topoQ.data?.files || []).length === 0 && (
            <Text size="sm" c="dimmed">
              No topology files found in{' '}
              <Code>{topoQ.data?.topo_dir || 'CLAB_TOPO_DIR'}</Code>.
              Upload a .yml file to get started.
            </Text>
          )}
        </Stack>
      )}

      {/* Deploy modal */}
      <Modal
        opened={deployOpen}
        onClose={() => { setDeployOpen(false); setSelectedTopo(null); setDeployStatus('idle'); setDeployLogs([]); }}
        title={
          <Group gap="xs">
            <IconPlayerPlay size={16} />
            <Text fw={600}>Deploy Lab</Text>
          </Group>
        }
        size={deployStatus !== 'idle' ? 'lg' : 'sm'}
      >
        <Stack>
          {deployStatus === 'idle' && (
            <Select
              label="Topology file"
              placeholder="Select from CLAB_TOPO_DIR"
              data={topoQ.data?.files || []}
              value={selectedTopo}
              onChange={setSelectedTopo}
              searchable
            />
          )}

          {deployStatus !== 'idle' && (
            <ScrollArea h={350} bg="#0e0e0e" p="sm" style={{ borderRadius: 6 }}>
              {deployLogs.length === 0 ? (
                <Text size="xs" c="dimmed" ff="mono">Starting deployment stream...</Text>
              ) : (
                deployLogs.map((log, idx) => (
                  <Text key={idx} size="xs" c="#00ff00" ff="mono" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
                    {log}
                  </Text>
                ))
              )}
              <div ref={logsEndRef} />
            </ScrollArea>
          )}

          {deployStatus === 'idle' && (
            <Button
              fullWidth
              disabled={!selectedTopo}
              leftSection={<IconCheck size={14} />}
              onClick={deployWithStreaming}
            >
              Deploy
            </Button>
          )}
          {deployStatus === 'error' && (
            <Button color="gray" fullWidth onClick={() => { setDeployStatus('idle'); setDeployLogs([]); }}>
              Retry
            </Button>
          )}
        </Stack>
      </Modal>

      {/* Lab inspect drawer */}
      <LabDrawer
        labName={inspectTarget}
        opened={!!inspectTarget}
        onClose={() => setInspectTarget(null)}
      />
    </Box>
  );
}
