import { useState, useCallback, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box, Text, Badge, Group, Stack, Table, Button, Loader, Alert,
  Modal, Code, ScrollArea, Drawer, ActionIcon,
  Tooltip, ThemeIcon, Switch, Accordion,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconNetwork, IconPlayerPlay, IconTrash, IconRefresh,
  IconCode, IconInfoCircle, IconTerminal2,
  IconAlertCircle, IconCheck, IconAlertTriangle, IconShieldCheck,
  IconPlayerStop, IconRotateClockwise, IconPlayerPlay as IconStart,
  IconEye,
} from '@tabler/icons-react';
import {
  getCLabStatus, listLabs, inspectLab, destroyLab,
  getTopology, validateTopology, nodeAction,
} from '../api/containerlab';
import { WorkspaceBrowser } from '../features/topology/WorkspaceBrowser';
import { NodeConsole } from '../features/topology/NodeConsole';
import { TopologyGraph } from '../features/topology/TopologyGraph';
import CodeMirror from '@uiw/react-codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';

// ─── Helpers ────────────────────────────────────────────────────────────────

function ModeBadge({ mode }) {
  const colors = { local: 'teal', ssh: 'blue', rest: 'violet' };
  return (
    <Badge color={colors[mode] || 'gray'} variant="light" size="sm" tt="uppercase">
      {mode}
    </Badge>
  );
}

const STATE_COLORS = {
  running:    'green',
  exited:     'red',
  stopped:    'red',
  paused:     'yellow',
  restarting: 'orange',
  dead:       'dark',
  created:    'blue',
};

function LabAge({ createdAt }) {
  if (!createdAt) return <Text size="xs" c="dimmed">—</Text>;
  try {
    const ms = Date.now() - new Date(createdAt).getTime();
    const mins = Math.floor(ms / 60000);
    if (mins < 60) return <Badge size="xs" variant="outline" color="gray">{mins}m ago</Badge>;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return <Badge size="xs" variant="outline" color="gray">{hrs}h ago</Badge>;
    return <Badge size="xs" variant="outline" color="gray">{Math.floor(hrs / 24)}d ago</Badge>;
  } catch {
    return <Text size="xs" c="dimmed">—</Text>;
  }
}

// ─── Lab detail drawer ──────────────────────────────────────────────────────
function LabDrawer({ labName, opened, onClose, statusConfig }) {
  const qc = useQueryClient();
  const [consoleTarget, setConsoleTarget] = useState(null); // { lab, node }

  const { data, isLoading, error } = useQuery({
    queryKey: ['clab-inspect', labName],
    queryFn: () => inspectLab(labName),
    enabled: opened && !!labName,
  });

  const containers = data?.containers || (Array.isArray(data) ? data : []);

  const actionMut = useMutation({
    mutationFn: ({ lab, node, action }) => nodeAction(lab, node, action),
    onSuccess: (_, vars) => {
      notifications.show({ color: 'teal', title: `${vars.action} sent`, message: vars.node, autoClose: 2000 });
      qc.invalidateQueries({ queryKey: ['clab-inspect', labName] });
      qc.invalidateQueries({ queryKey: ['clab-labs'] });
    },
    onError: (e, vars) => notifications.show({
      color: 'red', title: `${vars.action} failed`,
      message: e.response?.data?.detail || e.message,
    }),
  });

  const getShellStr = (c) => {
    const ipv6 = c.ipv6_address || c.management?.ipv6;
    const ipv4 = c.ipv4_address || c.management?.ipv4;
    const raw = ipv6 || ipv4;
    if (!raw) return null;
    const bare = raw.split('/')[0];
    const addr = ipv6 ? `[${bare}]` : bare;
    const mode = statusConfig?.mode;
    const s_host = statusConfig?.ssh_host;
    const s_user = statusConfig?.ssh_user;
    return mode === 'ssh' && s_host
      ? `ssh -J ${s_user || 'root'}@${s_host} admin@${addr}`
      : `ssh admin@${addr}`;
  };

  const nodeName = (c) => c.name || c.container_name || '';

  return (
    <>
      <Drawer
        opened={opened}
        onClose={onClose}
        title={
          <Group gap="xs">
            <ThemeIcon color="cyan" variant="light" size="sm"><IconNetwork size={14} /></ThemeIcon>
            <Text fw={600}>{labName}</Text>
          </Group>
        }
        position="right"
        size="xl"
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
                  <Table.Th>Management IP</Table.Th>
                  <Table.Th>State</Table.Th>
                  <Table.Th>Actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {containers.map((c, i) => {
                  const state = c.state || '';
                  const name = nodeName(c);
                  const shellStr = getShellStr(c);
                  // strip clab-<lab>- prefix to get the bare node name
                  const bareNode = name.replace(new RegExp(`^clab-${labName}-`), '');
                  const isRunning = state === 'running';
                  const isBusy = actionMut.isPending && actionMut.variables?.node === bareNode;

                  return (
                    <Table.Tr key={i}>
                      <Table.Td>
                        <Text size="xs" ff="mono">{bareNode || name || '—'}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge size="xs" variant="outline" color="cyan">
                          {c.kind || c.node_kind || '—'}
                        </Badge>
                      </Table.Td>
                      <Table.Td style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        <Text size="xs" truncate>{c.image || '—'}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Stack gap={2}>
                          {(c.ipv6_address || c.management?.ipv6) && (
                            <Text ff="mono" fz={10}>{(c.ipv6_address || c.management?.ipv6)}</Text>
                          )}
                          {(c.ipv4_address || c.management?.ipv4) && (
                            <Text ff="mono" fz={10} c="dimmed">{(c.ipv4_address || c.management?.ipv4)}</Text>
                          )}
                          {!(c.ipv6_address || c.management?.ipv6) && !(c.ipv4_address || c.management?.ipv4) && (
                            <Text fz={10} c="dimmed">—</Text>
                          )}
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Badge size="xs" color={STATE_COLORS[state] || 'gray'}>{state || '—'}</Badge>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          {shellStr && (
                            <Tooltip label="Copy SSH command">
                              <ActionIcon size="sm" variant="light" color="cyan"
                                onClick={() => {
                                  navigator.clipboard.writeText(shellStr);
                                  notifications.show({ title: 'Copied', message: shellStr, color: 'blue', autoClose: 2000 });
                                }}
                              >
                                <IconCode size={13} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                          <Tooltip label="Open terminal">
                            <ActionIcon size="sm" variant="light" color="green"
                              disabled={!isRunning}
                              onClick={() => setConsoleTarget({ lab: labName, node: bareNode || name })}
                            >
                              <IconTerminal2 size={13} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label="Restart">
                            <ActionIcon size="sm" variant="light" color="orange"
                              loading={isBusy && actionMut.variables?.action === 'restart'}
                              onClick={() => actionMut.mutate({ lab: labName, node: bareNode || name, action: 'restart' })}
                            >
                              <IconRotateClockwise size={13} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label={isRunning ? 'Stop' : 'Start'}>
                            <ActionIcon
                              size="sm" variant="light"
                              color={isRunning ? 'red' : 'green'}
                              loading={isBusy && (actionMut.variables?.action === 'stop' || actionMut.variables?.action === 'start')}
                              onClick={() => actionMut.mutate({ lab: labName, node: bareNode || name, action: isRunning ? 'stop' : 'start' })}
                            >
                              {isRunning ? <IconPlayerStop size={13} /> : <IconStart size={13} />}
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
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

      {/* Per-node console modal */}
      <Modal
        opened={!!consoleTarget}
        onClose={() => setConsoleTarget(null)}
        title={
          <Group gap="xs">
            <IconTerminal2 size={16} />
            <Text fw={600} ff="mono">{consoleTarget?.node}</Text>
          </Group>
        }
        size="xl"
        styles={{ body: { padding: 0 } }}
      >
        {consoleTarget && (
          <NodeConsole labName={consoleTarget.lab} nodeName={consoleTarget.node} />
        )}
      </Modal>
    </>
  );
}

// ─── Deploy modal ────────────────────────────────────────────────────────────
function DeployModal({ opened, onClose, selectedTopo, onDeployed }) {
  const [reconfigure, setReconfigure] = useState(true);
  const [deployLogs, setDeployLogs] = useState([]);
  const [deployStatus, setDeployStatus] = useState('idle'); // idle | deploying | success | error
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const logsEndRef = useRef(null);

  const { data: topoData } = useQuery({
    queryKey: ['clab-topo-preview', selectedTopo],
    queryFn: () => getTopology(selectedTopo),
    enabled: !!selectedTopo,
    staleTime: 30000,
  });

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [deployLogs]);

  const reset = () => {
    setDeployStatus('idle');
    setDeployLogs([]);
    setValidationResult(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const runValidation = async () => {
    setValidating(true);
    setValidationResult(null);
    try {
      const result = await validateTopology(selectedTopo);
      setValidationResult(result);
    } catch (e) {
      setValidationResult({ valid: false, output: e.response?.data?.detail || e.message });
    } finally {
      setValidating(false);
    }
  };

  const deployWithStreaming = async () => {
    setDeployStatus('deploying');
    setDeployLogs([]);
    let currentStatus = 'deploying';

    try {
      const res = await fetch('/api/containerlab/labs/deploy-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topo_file: selectedTopo, reconfigure }),
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
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          if (part.startsWith('data: ')) {
            try {
              const event = JSON.parse(part.substring(6));
              if (event.type === 'log') {
                setDeployLogs(prev => [...prev, event.line]);
              } else if (event.type === 'error') {
                currentStatus = 'error';
                setDeployStatus('error');
                setDeployLogs(prev => [...prev, `[ERROR] ${event.message}`]);
              } else if (event.type === 'success') {
                currentStatus = 'success';
                setDeployStatus('success');
                setDeployLogs(prev => [...prev, `\n[SUCCESS] ${event.message}`]);
              }
            } catch (e) {
              setDeployLogs(prev => [...prev, `[Parse Error] ${e.message}`]);
            }
          }
        }
      }

      if (currentStatus === 'deploying') {
        currentStatus = 'success';
        setDeployStatus('success');
        setDeployLogs(prev => [...prev, '[INFO] Stream ended.']);
      }
    } catch (exc) {
      currentStatus = 'error';
      setDeployStatus('error');
      setDeployLogs(prev => [...prev, `[Network Error] ${exc.message}`]);
    }

    onDeployed();
  };

  const isIdle = deployStatus === 'idle';

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={
        <Group gap="xs">
          <IconPlayerPlay size={16} />
          <Text fw={600}>Deploy Lab</Text>
        </Group>
      }
      size={isIdle ? 'lg' : 'xl'}
    >
      <Stack>
        {isIdle && (
          <>
            <Group justify="space-between">
              <Text size="sm">Topology: <Code>{selectedTopo}</Code></Text>
              <Switch
                size="sm"
                label="Reconfigure"
                checked={reconfigure}
                onChange={(e) => setReconfigure(e.currentTarget.checked)}
              />
            </Group>

            {/* Validation result */}
            {validationResult && (
              <Alert
                color={validationResult.valid === false ? 'red' : validationResult.valid === true ? 'green' : 'gray'}
                icon={validationResult.valid === false ? <IconAlertTriangle size={14} /> : <IconShieldCheck size={14} />}
                title={validationResult.valid === false ? 'Validation failed' : validationResult.valid === true ? 'Topology valid' : 'Validation skipped'}
              >
                {validationResult.output && (
                  <ScrollArea h={100} mt={4}>
                    <Text size="xs" ff="mono" style={{ whiteSpace: 'pre-wrap' }}>{validationResult.output}</Text>
                  </ScrollArea>
                )}
              </Alert>
            )}

            {/* Topology preview + graph */}
            {topoData?.content && (
              <Accordion variant="separated">
                <Accordion.Item value="yaml">
                  <Accordion.Control icon={<IconEye size={14} />}>
                    <Text size="sm">Preview YAML</Text>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <CodeMirror
                      value={topoData.content}
                      height="220px"
                      theme={oneDark}
                      extensions={[yaml()]}
                      editable={false}
                      style={{ borderRadius: 6, overflow: 'hidden', fontSize: 12 }}
                    />
                  </Accordion.Panel>
                </Accordion.Item>
                <Accordion.Item value="graph">
                  <Accordion.Control icon={<IconNetwork size={14} />}>
                    <Text size="sm">Topology Graph</Text>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <TopologyGraph yamlContent={topoData.content} height={320} />
                  </Accordion.Panel>
                </Accordion.Item>
              </Accordion>
            )}

            <Group grow>
              <Button variant="light" color="cyan" loading={validating}
                leftSection={<IconShieldCheck size={14} />} onClick={runValidation}>
                Validate
              </Button>
              <Button
                leftSection={<IconCheck size={14} />}
                disabled={!selectedTopo || validationResult?.valid === false}
                onClick={deployWithStreaming}
              >
                Deploy
              </Button>
            </Group>
          </>
        )}

        {deployStatus !== 'idle' && (
          <ScrollArea h={380} bg="#0e0e0e" p="sm" style={{ borderRadius: 6 }}>
            {deployLogs.length === 0
              ? <Text size="xs" c="dimmed" ff="mono">Starting deployment stream…</Text>
              : deployLogs.map((log, idx) => (
                <Text key={idx} size="xs" c="#00ff00" ff="mono" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
                  {log}
                </Text>
              ))
            }
            <div ref={logsEndRef} />
          </ScrollArea>
        )}

        {deployStatus === 'deploying' && (
          <Button fullWidth variant="subtle" color="gray" disabled>Deploying…</Button>
        )}
        {deployStatus === 'success' && (
          <Button fullWidth color="green" leftSection={<IconCheck size={14} />} onClick={handleClose}>
            Done — Close
          </Button>
        )}
        {deployStatus === 'error' && (
          <Group grow>
            <Button color="gray" onClick={reset}>Retry</Button>
            <Button variant="subtle" color="gray" onClick={handleClose}>Close</Button>
          </Group>
        )}
      </Stack>
    </Modal>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
export default function ContainerLab() {
  const qc = useQueryClient();
  const [inspectTarget, setInspectTarget] = useState(null);
  const [deployOpen, setDeployOpen] = useState(false);
  const [selectedTopo, setSelectedTopo] = useState(null);
  const [confirmDestroyLab, setConfirmDestroyLab] = useState(null);

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

  const gitConfigured = statusQ.data?.features?.git_topologies ?? false;
  const mode = statusQ.data?.mode;
  const statusOk = statusQ.data?.ok;

  const destroyMut = useMutation({
    mutationFn: destroyLab,
    onSuccess: (data) => {
      notifications.show({ color: 'orange', title: 'Lab destroyed', message: data.lab_name });
      qc.invalidateQueries({ queryKey: ['clab-labs'] });
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Destroy failed', message: e.response?.data?.detail || e.message }),
  });

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['clab-status'] });
    qc.invalidateQueries({ queryKey: ['clab-labs'] });
    qc.invalidateQueries({ queryKey: ['clab-ws'] });
  }, [qc]);

  return (
    <Box>
      {/* Header */}
      <Group justify="space-between" mb="lg">
        <Box>
          <Group gap="sm" align="center">
            <ThemeIcon color="cyan" variant="light" size="md"><IconNetwork size={18} /></ThemeIcon>
            <Text fw={700} size="xl">ContainerLab</Text>
            {mode && <ModeBadge mode={mode} />}
            {statusQ.data && (
              <Badge color={statusOk ? 'green' : 'red'} variant="dot" size="sm">
                {statusOk ? 'connected' : 'unreachable'}
              </Badge>
            )}
          </Group>
          <Text size="sm" c="dimmed" mt={2}>Network topology lifecycle management</Text>
        </Box>
        <Tooltip label="Refresh">
          <ActionIcon variant="subtle" onClick={refresh} loading={labsQ.isFetching}>
            <IconRefresh size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>

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
      {labsQ.error && <Alert color="red" mb="md">{labsQ.error.message}</Alert>}
      {!labsQ.isLoading && (
        <Table striped highlightOnHover withTableBorder mb="xl">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Lab Name</Table.Th>
              <Table.Th>Nodes</Table.Th>
              <Table.Th>Age</Table.Th>
              <Table.Th>Topology Path</Table.Th>
              <Table.Th style={{ width: 100 }}>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(labsQ.data || []).map((lab) => (
              <Table.Tr key={lab.name} style={{ cursor: 'pointer' }}
                onClick={() => setInspectTarget(lab.name)}>
                <Table.Td><Text fw={500} size="sm">{lab.name}</Text></Table.Td>
                <Table.Td>
                  <Badge size="xs" color="cyan" variant="light">
                    {lab.containers?.length ?? '—'} nodes
                  </Badge>
                </Table.Td>
                <Table.Td><LabAge createdAt={lab.created_at} /></Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed" ff="mono">{lab.lab_path || '—'}</Text>
                </Table.Td>
                <Table.Td onClick={(e) => e.stopPropagation()}>
                  <Group gap={4}>
                    <Tooltip label="Inspect">
                      <ActionIcon size="sm" variant="subtle" color="cyan"
                        onClick={() => setInspectTarget(lab.name)}>
                        <IconInfoCircle size={14} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Destroy">
                      <ActionIcon size="sm" variant="subtle" color="red"
                        loading={destroyMut.isPending && destroyMut.variables === lab.name}
                        onClick={() => setConfirmDestroyLab(lab.name)}>
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Tooltip>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {(labsQ.data || []).length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5} ta="center" c="dimmed" py="lg">
                  No running labs. Deploy a topology to get started.
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      {/* Workspace Browser */}
      <WorkspaceBrowser
        gitConfigured={gitConfigured}
        onDeploy={(topoPath) => {
          setSelectedTopo(topoPath);
          setDeployOpen(true);
        }}
      />

      {/* Destroy confirm modal */}
      <Modal
        opened={!!confirmDestroyLab}
        onClose={() => setConfirmDestroyLab(null)}
        title={
          <Group gap="xs">
            <IconAlertTriangle size={16} color="var(--mantine-color-red-5)" />
            <Text fw={600}>Destroy Lab</Text>
          </Group>
        }
        size="sm"
      >
        <Stack>
          <Text size="sm">
            Are you sure you want to destroy <Code>{confirmDestroyLab}</Code>?
            All running containers in this lab will be stopped and removed.
          </Text>
          <Group justify="flex-end" mt="xs">
            <Button variant="subtle" color="gray" onClick={() => setConfirmDestroyLab(null)}>
              Cancel
            </Button>
            <Button color="red" loading={destroyMut.isPending}
              leftSection={<IconTrash size={14} />}
              onClick={() => destroyMut.mutate(confirmDestroyLab, {
                onSettled: () => setConfirmDestroyLab(null),
              })}>
              Destroy
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Deploy modal */}
      <DeployModal
        opened={deployOpen}
        onClose={() => { setDeployOpen(false); setSelectedTopo(null); }}
        selectedTopo={selectedTopo}
        onDeployed={() => qc.invalidateQueries({ queryKey: ['clab-labs'] })}
      />

      {/* Lab inspect drawer */}
      <LabDrawer
        labName={inspectTarget}
        opened={!!inspectTarget}
        onClose={() => setInspectTarget(null)}
        statusConfig={statusQ.data?.features}
      />
    </Box>
  );
}
