import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
    Box, Title, Text, Group, Badge, Stack, Table, ScrollArea,
    ActionIcon, Tooltip, Drawer, Tabs, Alert, Loader, Button,
    Select, Code, Divider, TextInput, SegmentedControl, ThemeIcon,
    CopyButton, Notification,
} from '@mantine/core';
import {
    IconServer, IconCloudUpload, IconGitCommit, IconRefresh,
    IconWifi, IconAlertTriangle, IconCheck, IconTerminal2,
    IconHistory, IconUpload, IconSearch, IconDatabase,
    IconCopy, IconPlayerPlay,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import {
    getDevices, getDevice, getHardwareStatus,
    backupDevice, getConfigHistory, getConfigAtRef, provisionDevice,
} from '../api/hardware';

// ── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_COLOR = {
    active:     'green',
    planned:    'blue',
    staged:     'cyan',
    failed:     'red',
    inventory:  'gray',
    decommissioning: 'orange',
};

function StatusBadge({ status }) {
    return (
        <Badge size="xs" color={STATUS_COLOR[status] || 'gray'} variant="light">
            {status || '—'}
        </Badge>
    );
}

// ── Config viewer with syntax highlight ──────────────────────────────────────

function ConfigViewer({ content, maxHeight = 420 }) {
    if (!content) return <Text c="dimmed" fz="xs">No config content.</Text>;
    return (
        <Box pos="relative">
            <CopyButton value={content}>
                {({ copied, copy }) => (
                    <ActionIcon
                        size="xs"
                        color={copied ? 'teal' : 'gray'}
                        variant="subtle"
                        onClick={copy}
                        style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}
                    >
                        {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}
                    </ActionIcon>
                )}
            </CopyButton>
            <ScrollArea h={maxHeight}>
                <Code block fz="xs" style={{ whiteSpace: 'pre', fontFamily: 'monospace' }}>
                    {content}
                </Code>
            </ScrollArea>
        </Box>
    );
}

// ── Device detail drawer ──────────────────────────────────────────────────────

function DeviceDrawer({ deviceId, opened, onClose }) {
    const qc = useQueryClient();

    const { data: device,  isLoading: devLoading  } = useQuery({
        queryKey: ['hw-device', deviceId],
        queryFn:  () => getDevice(deviceId),
        enabled: opened && !!deviceId,
    });

    const { data: history, isLoading: histLoading, refetch: refetchHistory } = useQuery({
        queryKey: ['hw-config-history', deviceId],
        queryFn:  () => getConfigHistory(deviceId),
        enabled: opened && !!deviceId,
        staleTime: 30_000,
    });

    // Backup mutation
    const [backupTargets, setBackupTargets] = useState(['unimus', 'git']);
    const backupMut = useMutation({
        mutationFn: () => backupDevice(deviceId, backupTargets),
        onSuccess: (data) => {
            const warns = data.warnings || [];
            if (warns.length) {
                notifications.show({ color: 'yellow', title: 'Backup completed with warnings', message: warns.join(' | '), autoClose: 10000 });
            } else {
                notifications.show({ color: 'teal', title: 'Backup successful', message: `Config archived${data.git_ref ? ` (git: ${data.git_ref.slice(0, 8)})` : ''}` });
            }
            refetchHistory();
            qc.invalidateQueries(['hw-device', deviceId]);
        },
        onError: (err) => {
            notifications.show({ color: 'red', title: 'Backup failed', message: err.response?.data?.detail || err.message });
        },
    });

    // Provision mutation
    const [provSource, setProvSource] = useState('git');
    const [provRef,    setProvRef]    = useState('');
    const [provNote,   setProvNote]   = useState('');
    const provMut = useMutation({
        mutationFn: () => provisionDevice(deviceId, provSource, provRef || null, provNote),
        onSuccess: (data) => {
            notifications.show({
                color: 'teal',
                title: 'Config push initiated',
                message: `Source: ${data.source_label} | Unimus job: ${data.unimus_job?.id || 'queued'}`,
            });
        },
        onError: (err) => {
            notifications.show({ color: 'red', title: 'Provision failed', message: err.response?.data?.detail || err.message, autoClose: 12000 });
        },
    });

    // Config viewer for history
    const [selectedRef, setSelectedRef] = useState(null);
    const { data: configAtRef, isLoading: refLoading } = useQuery({
        queryKey: ['hw-config-ref', deviceId, selectedRef],
        queryFn:  () => getConfigAtRef(deviceId, selectedRef),
        enabled: !!selectedRef,
    });

    const hostname = device?.name || `device-${deviceId}`;

    return (
        <Drawer
            opened={opened}
            onClose={onClose}
            size="xl"
            position="right"
            title={
                <Group gap="sm">
                    <ThemeIcon size="md" color="cyan" variant="light">
                        <IconServer size={16} />
                    </ThemeIcon>
                    <Box>
                        <Text fw={700} size="sm">{hostname}</Text>
                        {device?.primary_ip && (
                            <Text size="xs" c="dimmed" ff="monospace">{device.primary_ip}</Text>
                        )}
                    </Box>
                    {device?.status && <StatusBadge status={device.status} />}
                </Group>
            }
            styles={{
                content: { background: 'var(--surface)', border: '1px solid var(--border)' },
                header:  { background: 'var(--surface)' },
            }}
        >
            {devLoading && (
                <Group justify="center" py="xl"><Loader size="sm" color="cyan" /></Group>
            )}

            {!devLoading && device && (
                <Tabs defaultValue="overview" color="cyan">
                    <Tabs.List mb="md">
                        <Tabs.Tab value="overview"  leftSection={<IconServer size={13} />}>Overview</Tabs.Tab>
                        <Tabs.Tab value="backup"    leftSection={<IconCloudUpload size={13} />}>Backup</Tabs.Tab>
                        <Tabs.Tab value="history"   leftSection={<IconHistory size={13} />}>Config History</Tabs.Tab>
                        <Tabs.Tab value="provision" leftSection={<IconUpload size={13} />}>Provision</Tabs.Tab>
                    </Tabs.List>

                    {/* ── Overview ── */}
                    <Tabs.Panel value="overview">
                        <Stack gap="xs">
                            {[
                                ['Hostname',     device.name],
                                ['Device Type',  device.device_type],
                                ['Manufacturer', device.manufacturer],
                                ['Site',         device.site],
                                ['Rack',         device.rack],
                                ['Role',         device.role],
                                ['Mgmt IP',      device.primary_ip],
                                ['Status',       device.status],
                            ].map(([label, val]) => val ? (
                                <Group key={label} justify="space-between">
                                    <Text size="xs" c="dimmed">{label}</Text>
                                    <Text size="xs" fw={500} ff={label === 'Mgmt IP' ? 'monospace' : undefined}>{val}</Text>
                                </Group>
                            ) : null)}

                            {device.tags?.length > 0 && (
                                <Group gap="xs" mt="xs">
                                    {device.tags.map(t => (
                                        <Badge key={t} size="xs" variant="outline" color="gray">{t}</Badge>
                                    ))}
                                </Group>
                            )}

                            {device.interfaces?.length > 0 && (
                                <>
                                    <Divider my="xs" label="Interfaces" labelPosition="left" />
                                    <ScrollArea h={180}>
                                        <Table fz="xs" withRowBorders>
                                            <Table.Thead>
                                                <Table.Tr>
                                                    <Table.Th>Name</Table.Th>
                                                    <Table.Th>Type</Table.Th>
                                                    <Table.Th>Mgmt Only</Table.Th>
                                                    <Table.Th>MAC</Table.Th>
                                                </Table.Tr>
                                            </Table.Thead>
                                            <Table.Tbody>
                                                {device.interfaces.map(iface => (
                                                    <Table.Tr key={iface.id}>
                                                        <Table.Td fw={500}>{iface.name}</Table.Td>
                                                        <Table.Td c="dimmed">{iface.type}</Table.Td>
                                                        <Table.Td>
                                                            {iface.mgmt_only && (
                                                                <Badge size="xs" color="cyan" variant="light">mgmt</Badge>
                                                            )}
                                                        </Table.Td>
                                                        <Table.Td ff="monospace" fz="xs">{iface.mac || '—'}</Table.Td>
                                                    </Table.Tr>
                                                ))}
                                            </Table.Tbody>
                                        </Table>
                                    </ScrollArea>
                                </>
                            )}
                        </Stack>
                    </Tabs.Panel>

                    {/* ── Backup ── */}
                    <Tabs.Panel value="backup">
                        <Stack gap="md">
                            <Alert color="blue" variant="light" p="xs">
                                <Text size="xs">
                                    Triggers a real-time backup via <strong>Unimus</strong>,
                                    then archives the config to <strong>Git</strong>.
                                    The request waits for Unimus to complete (up to 2 min).
                                </Text>
                            </Alert>

                            <Box>
                                <Text size="xs" fw={600} mb="xs">Archive to:</Text>
                                <Group gap="xs">
                                    {['unimus', 'git'].map(target => {
                                        const active = backupTargets.includes(target);
                                        return (
                                            <Button
                                                key={target}
                                                size="compact-xs"
                                                variant={active ? 'filled' : 'outline'}
                                                color={target === 'git' ? 'violet' : 'cyan'}
                                                leftSection={target === 'git' ? <IconGitCommit size={11} /> : <IconDatabase size={11} />}
                                                onClick={() => setBackupTargets(prev =>
                                                    active ? prev.filter(t => t !== target) : [...prev, target]
                                                )}
                                            >
                                                {target === 'git' ? 'Git' : 'Unimus'}
                                            </Button>
                                        );
                                    })}
                                </Group>
                            </Box>

                            <Button
                                color="cyan"
                                leftSection={<IconCloudUpload size={14} />}
                                loading={backupMut.isPending}
                                disabled={backupTargets.length === 0}
                                onClick={() => backupMut.mutate()}
                            >
                                {backupMut.isPending ? 'Backing up… (waiting for Unimus)' : 'Backup Now'}
                            </Button>

                            {backupMut.data && (
                                <Stack gap="xs" mt="xs">
                                    {backupMut.data.git_ref && (
                                        <Group gap="xs">
                                            <IconGitCommit size={13} color="var(--mantine-color-violet-5)" />
                                            <Text size="xs" ff="monospace">git: {backupMut.data.git_ref.slice(0, 8)}</Text>
                                        </Group>
                                    )}
                                    {backupMut.data.config_preview && (
                                        <>
                                            <Text size="xs" c="dimmed" mt="xs">Config preview:</Text>
                                            <ConfigViewer content={backupMut.data.config_preview} maxHeight={200} />
                                        </>
                                    )}
                                    {(backupMut.data.warnings || []).map((w, i) => (
                                        <Alert key={i} color="yellow" p="xs">
                                            <Text size="xs">{w}</Text>
                                        </Alert>
                                    ))}
                                </Stack>
                            )}
                        </Stack>
                    </Tabs.Panel>

                    {/* ── Config History ── */}
                    <Tabs.Panel value="history">
                        <Stack gap="sm">
                            {histLoading && <Group justify="center"><Loader size="sm" color="cyan" /></Group>}
                            {!histLoading && (!history?.history?.length) && (
                                <Text c="dimmed" fz="xs">No config history in Git yet. Run a backup first.</Text>
                            )}
                            {!histLoading && history?.history?.length > 0 && (
                                <ScrollArea h={200}>
                                    <Table fz="xs" withRowBorders highlightOnHover>
                                        <Table.Thead>
                                            <Table.Tr>
                                                <Table.Th>Commit</Table.Th>
                                                <Table.Th>Message</Table.Th>
                                                <Table.Th>When</Table.Th>
                                                <Table.Th />
                                            </Table.Tr>
                                        </Table.Thead>
                                        <Table.Tbody>
                                            {history.history.map(h => (
                                                <Table.Tr
                                                    key={h.ref}
                                                    style={{ cursor: 'pointer', background: selectedRef === h.ref ? 'rgba(0,188,212,0.08)' : undefined }}
                                                    onClick={() => setSelectedRef(h.ref)}
                                                >
                                                    <Table.Td ff="monospace" fw={600}>{h.short_ref}</Table.Td>
                                                    <Table.Td c="dimmed">{h.message}</Table.Td>
                                                    <Table.Td c="dimmed">{new Date(h.timestamp).toLocaleString()}</Table.Td>
                                                    <Table.Td>
                                                        <Button size="compact-xs" variant="subtle" color="cyan"
                                                            onClick={(e) => { e.stopPropagation(); setSelectedRef(h.ref); }}>
                                                            View
                                                        </Button>
                                                    </Table.Td>
                                                </Table.Tr>
                                            ))}
                                        </Table.Tbody>
                                    </Table>
                                </ScrollArea>
                            )}

                            {selectedRef && (
                                <>
                                    <Divider label={`Config at ${selectedRef.slice(0, 8)}`} labelPosition="left" />
                                    {refLoading
                                        ? <Group justify="center"><Loader size="xs" /></Group>
                                        : <ConfigViewer content={configAtRef?.content} />
                                    }
                                </>
                            )}
                        </Stack>
                    </Tabs.Panel>

                    {/* ── Provision ── */}
                    <Tabs.Panel value="provision">
                        <Stack gap="md">
                            <Alert color="orange" variant="light" p="xs" icon={<IconAlertTriangle size={14} />}>
                                <Text size="xs">
                                    <strong>This will push a config to the live device via Unimus Pro.</strong>{' '}
                                    Verify the selected config before proceeding.
                                </Text>
                            </Alert>

                            <Box>
                                <Text size="xs" fw={600} mb="xs">Source of truth:</Text>
                                <SegmentedControl
                                    size="xs"
                                    value={provSource}
                                    onChange={setProvSource}
                                    data={[
                                        { label: 'Git repository', value: 'git' },
                                        { label: 'Unimus (latest backup)', value: 'unimus' },
                                    ]}
                                />
                            </Box>

                            {provSource === 'git' && (
                                <Box>
                                    <Text size="xs" c="dimmed" mb="xs">
                                        Git commit ref (leave blank for HEAD / latest committed config):
                                    </Text>
                                    <TextInput
                                        placeholder="e.g. a1b2c3d4 or HEAD"
                                        size="xs"
                                        ff="monospace"
                                        leftSection={<IconGitCommit size={13} />}
                                        value={provRef}
                                        onChange={e => setProvRef(e.currentTarget.value)}
                                    />
                                    {history?.history?.length > 0 && (
                                        <Box mt="xs">
                                            <Text size="xs" c="dimmed" mb="xs">Or pick from history:</Text>
                                            <Select
                                                size="xs"
                                                placeholder="Select commit…"
                                                value={provRef || null}
                                                onChange={val => setProvRef(val || '')}
                                                data={(history.history || []).map(h => ({
                                                    value: h.ref,
                                                    label: `${h.short_ref} — ${h.message} (${new Date(h.timestamp).toLocaleDateString()})`,
                                                }))}
                                                searchable
                                                clearable
                                            />
                                        </Box>
                                    )}
                                </Box>
                            )}

                            <TextInput
                                label="Note (optional)"
                                placeholder="Reason for this config push…"
                                size="xs"
                                value={provNote}
                                onChange={e => setProvNote(e.currentTarget.value)}
                            />

                            <Button
                                color="orange"
                                leftSection={<IconPlayerPlay size={14} />}
                                loading={provMut.isPending}
                                onClick={() => provMut.mutate()}
                            >
                                Push Golden Config via Unimus
                            </Button>

                            {provMut.data && (
                                <Alert color="teal" icon={<IconCheck size={14} />} p="xs">
                                    <Text size="xs">
                                        Config push queued via Unimus.{' '}
                                        Source: <Code fz="xs">{provMut.data.source_label}</Code>
                                        {provMut.data.unimus_job?.id && (
                                            <> | Job ID: <Code fz="xs">{provMut.data.unimus_job.id}</Code></>
                                        )}
                                    </Text>
                                </Alert>
                            )}
                        </Stack>
                    </Tabs.Panel>
                </Tabs>
            )}
        </Drawer>
    );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Hardware() {
    const [q,          setQ         ] = useState('');
    const [siteFilter, setSiteFilter ] = useState('');
    const [selectedId, setSelectedId ] = useState(null);

    const statusQ = useQuery({
        queryKey: ['hw-status'],
        queryFn: getHardwareStatus,
        staleTime: 60_000,
        retry: false,
    });

    const devicesQ = useQuery({
        queryKey: ['hw-devices'],
        queryFn: () => getDevices({ limit: 500 }),
        staleTime: 60_000,
    });

    const devices = devicesQ.data || [];

    // Extract unique sites for quick filtering
    const sites = [...new Set(devices.map(d => d.site).filter(Boolean))].sort();

    const filtered = devices.filter(d => {
        const qLc = q.toLowerCase();
        const matchQ = !q || [d.name, d.device_type, d.primary_ip, d.site, d.role]
            .some(v => (v || '').toLowerCase().includes(qLc));
        const matchSite = !siteFilter || d.site === siteFilter;
        return matchQ && matchSite;
    });

    const unimus = statusQ.data?.unimus;
    const git    = statusQ.data?.git;

    return (
        <Box>
            {/* Header */}
            <Group justify="space-between" mb="lg">
                <Box>
                    <Title order={2} fw={700} c="cyan.4">Hardware</Title>
                    <Text c="dimmed" size="sm">Physical devices from NetBox — backup and golden-config management</Text>
                </Box>
                <Group gap="xs">
                    {unimus && (
                        <Badge
                            size="sm"
                            color={unimus.reachable ? 'green' : 'red'}
                            variant="dot"
                            leftSection={<IconDatabase size={10} />}
                        >
                            Unimus {unimus.reachable ? unimus.version : 'unreachable'}
                        </Badge>
                    )}
                    {git && (
                        <Badge
                            size="sm"
                            color={git.configured ? 'violet' : 'gray'}
                            variant="dot"
                            leftSection={<IconGitCommit size={10} />}
                        >
                            Git {git.configured ? git.branch : 'not configured'}
                        </Badge>
                    )}
                    <ActionIcon
                        variant="subtle"
                        color="gray"
                        onClick={() => devicesQ.refetch()}
                        loading={devicesQ.isFetching}
                    >
                        <IconRefresh size={16} />
                    </ActionIcon>
                </Group>
            </Group>

            {/* Integration warnings */}
            {statusQ.isSuccess && (
                <Stack gap="xs" mb="md">
                    {!unimus?.reachable && (
                        <Alert color="yellow" icon={<IconAlertTriangle size={14} />} p="xs">
                            <Text size="xs">
                                Unimus unreachable. Set <Code fz="xs">UNIMUS_URL</Code> and{' '}
                                <Code fz="xs">UNIMUS_TOKEN</Code> in your <Code fz="xs">.env</Code> to enable backup.
                                {unimus?.reason && ` (${unimus.reason})`}
                            </Text>
                        </Alert>
                    )}
                    {!git?.configured && (
                        <Alert color="blue" icon={<IconGitCommit size={14} />} p="xs">
                            <Text size="xs">
                                Git repo not configured. Set <Code fz="xs">GIT_CONFIG_REPO</Code> and{' '}
                                <Code fz="xs">GIT_CONFIG_AUTH_TOKEN</Code> in <Code fz="xs">.env</Code> to enable config archiving.
                            </Text>
                        </Alert>
                    )}
                </Stack>
            )}

            {/* Filters */}
            <Group mb="md" gap="sm">
                <TextInput
                    placeholder="Search name, type, IP, site…"
                    leftSection={<IconSearch size={14} />}
                    value={q}
                    onChange={e => setQ(e.currentTarget.value)}
                    size="xs"
                    style={{ flex: 1 }}
                />
                <Select
                    placeholder="All sites"
                    size="xs"
                    clearable
                    data={sites.map(s => ({ value: s, label: s }))}
                    value={siteFilter || null}
                    onChange={val => setSiteFilter(val || '')}
                    style={{ minWidth: 160 }}
                />
            </Group>

            {/* Loading */}
            {devicesQ.isLoading && (
                <Group justify="center" py="xl">
                    <Loader size="sm" color="cyan" />
                    <Text c="dimmed" size="sm">Loading devices from NetBox…</Text>
                </Group>
            )}

            {/* Device table */}
            {!devicesQ.isLoading && (
                <ScrollArea>
                    <Table fz="xs" withRowBorders highlightOnHover>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>Hostname</Table.Th>
                                <Table.Th>Type / Manufacturer</Table.Th>
                                <Table.Th>Site</Table.Th>
                                <Table.Th>Role</Table.Th>
                                <Table.Th>Management IP</Table.Th>
                                <Table.Th>Status</Table.Th>
                                <Table.Th />
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {filtered.length === 0 && (
                                <Table.Tr>
                                    <Table.Td colSpan={7}>
                                        <Text c="dimmed" fz="xs" ta="center" py="md">
                                            {devices.length === 0
                                                ? 'No devices found in NetBox.'
                                                : 'No devices match the current filter.'}
                                        </Text>
                                    </Table.Td>
                                </Table.Tr>
                            )}
                            {filtered.map(d => (
                                <Table.Tr key={d.id}>
                                    <Table.Td fw={600}>{d.name}</Table.Td>
                                    <Table.Td c="dimmed">
                                        <Stack gap={0}>
                                            <Text fz="xs">{d.device_type || '—'}</Text>
                                            {d.manufacturer && (
                                                <Text fz="10px" c="dimmed">{d.manufacturer}</Text>
                                            )}
                                        </Stack>
                                    </Table.Td>
                                    <Table.Td c="dimmed">{d.site || '—'}</Table.Td>
                                    <Table.Td c="dimmed">{d.role || '—'}</Table.Td>
                                    <Table.Td ff="monospace" fw={500}>
                                        {d.primary_ip
                                            ? <Group gap={4}><IconWifi size={11} color="var(--mantine-color-cyan-5)" />{d.primary_ip}</Group>
                                            : <Text fz="xs" c="red.5">No mgmt IP</Text>
                                        }
                                    </Table.Td>
                                    <Table.Td><StatusBadge status={d.status} /></Table.Td>
                                    <Table.Td>
                                        <Button
                                            size="compact-xs"
                                            variant="subtle"
                                            color="cyan"
                                            onClick={() => setSelectedId(d.id)}
                                        >
                                            Manage
                                        </Button>
                                    </Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                </ScrollArea>
            )}

            {/* Device detail drawer */}
            <DeviceDrawer
                deviceId={selectedId}
                opened={selectedId !== null}
                onClose={() => setSelectedId(null)}
            />
        </Box>
    );
}
