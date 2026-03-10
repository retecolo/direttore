import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
    Modal, Tabs, TextInput, Table, Badge, Alert, Loader, Stack, Group,
    Text, Button, SegmentedControl, ThemeIcon,
    ScrollArea,
} from '@mantine/core';
import {
    IconCloud, IconAlertTriangle, IconCheck, IconNetwork,
    IconSearch, IconLayersLinked, IconCirclePlus,
} from '@tabler/icons-react';
import { checkNetBoxStatus, getIPAddresses, getPrefixes, getVlans, allocateIP } from '../api/netbox';
import { notifications } from '@mantine/notifications';

// ── helpers ─────────────────────────────────────────────────────────────────

const STATUS_COLORS = { active: 'green', reserved: 'yellow', deprecated: 'red', available: 'blue' };

function StatusBadge({ status }) {
    return (
        <Badge size="xs" color={STATUS_COLORS[status] || 'gray'} variant="light">
            {status || '—'}
        </Badge>
    );
}

function useNetBoxStatus() {
    return useQuery({
        queryKey: ['netbox-status'],
        queryFn: checkNetBoxStatus,
        staleTime: 30_000,
        retry: false,
    });
}

function search(rows, q, keys) {
    if (!q) return rows;
    const lc = q.toLowerCase();
    return rows.filter(r => keys.some(k => String(r[k] ?? '').toLowerCase().includes(lc)));
}

// ── IP Addresses tab (existing IPs) ──────────────────────────────────────────

function IPAddressesTab({ onSelect }) {
    const [q, setQ] = useState('');
    const [family, setFamily] = useState('both');

    const params = {
        status: 'active',
        ...(family !== 'both' ? { family: Number(family) } : {}),
    };

    const { data = [], isLoading } = useQuery({
        queryKey: ['nb-ip-addresses', family],
        queryFn: () => getIPAddresses(params),
        staleTime: 60_000,
    });

    const rows = search(data, q, ['address', 'dns_name', 'description', 'vrf']);

    return (
        <Stack gap="sm">
            <Group grow>
                <TextInput
                    placeholder="Search address, DNS name…"
                    leftSection={<IconSearch size={14} />}
                    value={q}
                    onChange={e => setQ(e.currentTarget.value)}
                    size="xs"
                />
                <SegmentedControl
                    size="xs"
                    value={family}
                    onChange={setFamily}
                    data={[
                        { label: 'Both', value: 'both' },
                        { label: 'IPv4', value: '4' },
                        { label: 'IPv6', value: '6' },
                    ]}
                />
            </Group>

            {isLoading && <Group justify="center" py="md"><Loader size="sm" color="cyan" /></Group>}

            {!isLoading && (
                <ScrollArea h={320}>
                    <Table fz="xs" withRowBorders highlightOnHover>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>Address</Table.Th>
                                <Table.Th>DNS Name</Table.Th>
                                <Table.Th>Gateway</Table.Th>
                                <Table.Th>VRF</Table.Th>
                                <Table.Th>Status</Table.Th>
                                <Table.Th />
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {rows.length === 0 && (
                                <Table.Tr>
                                    <Table.Td colSpan={6}>
                                        <Text c="dimmed" fz="xs" ta="center">No active addresses found</Text>
                                    </Table.Td>
                                </Table.Tr>
                            )}
                            {rows.map(ip => (
                                <Table.Tr key={ip.id}>
                                    <Table.Td fw={500}>{ip.address}</Table.Td>
                                    <Table.Td c="dimmed">{ip.dns_name || '—'}</Table.Td>
                                    <Table.Td>{ip.prefix_gateway || '—'}</Table.Td>
                                    <Table.Td>{ip.vrf || 'global'}</Table.Td>
                                    <Table.Td><StatusBadge status={ip.status} /></Table.Td>
                                    <Table.Td>
                                        <Button
                                            size="compact-xs"
                                            color="cyan"
                                            variant="light"
                                            leftSection={<IconCheck size={10} />}
                                            onClick={() => onSelect({ type: 'ip', data: ip })}
                                        >
                                            Use
                                        </Button>
                                    </Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                </ScrollArea>
            )}
        </Stack>
    );
}

// ── Prefixes tab (allocate next available) ────────────────────────────────────

function PrefixesTab({ onSelect, hostname, resourceType }) {
    const [q, setQ] = useState('');
    const [family, setFamily] = useState('both');
    const [allocating, setAllocating] = useState(null); // prefix id currently being allocated

    const params = {
        ...(family !== 'both' ? { family: Number(family) } : {}),
    };

    const { data = [], isLoading } = useQuery({
        queryKey: ['nb-prefixes', family],
        queryFn: () => getPrefixes(params),
        staleTime: 60_000,
    });

    const rows = search(data, q, ['prefix', 'description', 'site', 'vrf', 'role']);

    const handleAllocate = async (prefix) => {
        if (!hostname) {
            notifications.show({
                color: 'orange',
                title: 'Hostname required',
                message: 'Enter a hostname in the Basic Config step before allocating an IP.',
                autoClose: 5000,
            });
            return;
        }
        setAllocating(prefix.id);
        try {
            const result = await allocateIP(prefix.id, hostname, resourceType);
            onSelect({ type: 'allocated', data: result });
        } catch (err) {
            const msg = err.response?.data?.detail || err.message || 'Allocation failed';
            notifications.show({ color: 'red', title: 'IP allocation failed', message: msg, autoClose: 10000 });
        } finally {
            setAllocating(null);
        }
    };

    return (
        <Stack gap="sm">
            <Alert color="blue" variant="light" p="xs">
                <Text size="xs">
                    <strong>Allocate Next Available</strong> — automatically reserves the gateway
                    (.1 / ::1) and network address (::) if not yet in NetBox, then allocates the
                    next free IP and configures a static address on the NIC.
                    Hostname: <strong>{hostname || '(not set — enter in Basic Config first)'}</strong>
                </Text>
            </Alert>

            <Group grow>
                <TextInput
                    placeholder="Search prefix, site, role…"
                    leftSection={<IconSearch size={14} />}
                    value={q}
                    onChange={e => setQ(e.currentTarget.value)}
                    size="xs"
                />
                <SegmentedControl
                    size="xs"
                    value={family}
                    onChange={setFamily}
                    data={[
                        { label: 'Both', value: 'both' },
                        { label: 'IPv4', value: '4' },
                        { label: 'IPv6', value: '6' },
                    ]}
                />
            </Group>

            {isLoading && <Group justify="center" py="md"><Loader size="sm" color="cyan" /></Group>}

            {!isLoading && (
                <ScrollArea h={280}>
                    <Table fz="xs" withRowBorders highlightOnHover>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>Prefix</Table.Th>
                                <Table.Th>Gateway (CF)</Table.Th>
                                <Table.Th>DNS Servers (CF)</Table.Th>
                                <Table.Th>Site / VRF</Table.Th>
                                <Table.Th>Status</Table.Th>
                                <Table.Th />
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {rows.length === 0 && (
                                <Table.Tr>
                                    <Table.Td colSpan={6}>
                                        <Text c="dimmed" fz="xs" ta="center">No prefixes found</Text>
                                    </Table.Td>
                                </Table.Tr>
                            )}
                            {rows.map(p => (
                                <Table.Tr key={p.id}>
                                    <Table.Td fw={500}>{p.prefix}</Table.Td>
                                    <Table.Td c="dimmed">{p.gateway || '—'}</Table.Td>
                                    <Table.Td c="dimmed">{p.dns_servers || '—'}</Table.Td>
                                    <Table.Td c="dimmed">
                                        {[p.site, p.vrf].filter(Boolean).join(' / ') || 'global'}
                                    </Table.Td>
                                    <Table.Td><StatusBadge status={p.status} /></Table.Td>
                                    <Table.Td>
                                        <Button
                                            size="compact-xs"
                                            color="teal"
                                            variant="light"
                                            leftSection={
                                                allocating === p.id
                                                    ? <Loader size={10} />
                                                    : <IconCirclePlus size={10} />
                                            }
                                            loading={allocating === p.id}
                                            disabled={allocating !== null}
                                            onClick={() => handleAllocate(p)}
                                        >
                                            Allocate
                                        </Button>
                                    </Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                </ScrollArea>
            )}
        </Stack>
    );
}

// ── VLANs tab ────────────────────────────────────────────────────────────────

function VlansTab({ onSelect }) {
    const [q, setQ] = useState('');

    const { data = [], isLoading } = useQuery({
        queryKey: ['nb-vlans'],
        queryFn: () => getVlans(),
        staleTime: 60_000,
    });

    const rows = search(data, q, ['name', 'description', 'site', 'group', 'role']);

    return (
        <Stack gap="sm">
            <TextInput
                placeholder="Search VLAN name, site, group…"
                leftSection={<IconSearch size={14} />}
                value={q}
                onChange={e => setQ(e.currentTarget.value)}
                size="xs"
            />

            {isLoading && <Group justify="center" py="md"><Loader size="sm" color="cyan" /></Group>}

            {!isLoading && (
                <ScrollArea h={320}>
                    <Table fz="xs" withRowBorders highlightOnHover>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>VID</Table.Th>
                                <Table.Th>Name</Table.Th>
                                <Table.Th>Site</Table.Th>
                                <Table.Th>Group</Table.Th>
                                <Table.Th>Role</Table.Th>
                                <Table.Th>Status</Table.Th>
                                <Table.Th />
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {rows.length === 0 && (
                                <Table.Tr>
                                    <Table.Td colSpan={7}>
                                        <Text c="dimmed" fz="xs" ta="center">No VLANs found</Text>
                                    </Table.Td>
                                </Table.Tr>
                            )}
                            {rows.map(v => (
                                <Table.Tr key={v.id}>
                                    <Table.Td fw={600} style={{ fontVariantNumeric: 'tabular-nums' }}>
                                        {v.vid}
                                    </Table.Td>
                                    <Table.Td>{v.name}</Table.Td>
                                    <Table.Td c="dimmed">{v.site || '—'}</Table.Td>
                                    <Table.Td c="dimmed">{v.group || '—'}</Table.Td>
                                    <Table.Td c="dimmed">{v.role || '—'}</Table.Td>
                                    <Table.Td><StatusBadge status={v.status} /></Table.Td>
                                    <Table.Td>
                                        <Button
                                            size="compact-xs"
                                            color="violet"
                                            variant="light"
                                            leftSection={<IconCheck size={10} />}
                                            onClick={() => onSelect({ type: 'vlan', data: v })}
                                        >
                                            Use
                                        </Button>
                                    </Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                </ScrollArea>
            )}
        </Stack>
    );
}

// ── Main exported component ───────────────────────────────────────────────────

/**
 * NetBoxNicPicker
 *
 * Props:
 *   opened       {bool}           - modal open state
 *   onClose      {fn}             - called when modal should close
 *   onApply      {fn}             - called with a NIC patch object to merge into the NIC
 *   nicIndex     {number}         - which interface this picker is for (display only)
 *   hostname     {string}         - current hostname from provisioning form (used as dns_name)
 *   resourceType {'lxc'|'vm'}    - controls NetBox IP status: active for lxc, reserved for vm
 */
export default function NetBoxNicPicker({ opened, onClose, onApply, nicIndex, hostname = '', resourceType = 'lxc' }) {
    const statusQ = useNetBoxStatus();
    const reachable = statusQ.data?.reachable;

    const [applied, setApplied] = useState(null);

    const handleSelect = ({ type, data }) => {
        let patch = {};

        if (type === 'ip') {
            // Pre-existing IP address — use as static
            const isV6 = Number(data.family) === 6;
            patch = isV6
                ? { ip6: data.address, gw6: data.prefix_gateway || '' }
                : { ip: data.address, gw: data.prefix_gateway || '' };
            setApplied(data.address);

        } else if (type === 'allocated') {
            // Freshly allocated from a prefix
            const isV6 = Number(data.family) === 6;
            patch = isV6
                ? { ip6: data.address, gw6: data.gateway || '' }
                : { ip: data.address, gw: data.gateway || '' };
            setApplied(`${data.address} (allocated)`);

        } else if (type === 'vlan') {
            patch = { vlan: data.vid };
            setApplied(`VLAN ${data.vid} — ${data.name}`);
        }

        onApply(patch);
        setTimeout(() => { setApplied(null); onClose(); }, 700);
    };

    return (
        <Modal
            opened={opened}
            onClose={onClose}
            title={
                <Group gap="xs">
                    <ThemeIcon size="sm" color="cyan" variant="light">
                        <IconCloud size={14} />
                    </ThemeIcon>
                    <Text fw={600} size="sm">
                        Populate from NetBox — Interface {nicIndex}
                    </Text>
                    {statusQ.isSuccess && (
                        <Badge size="xs" color={reachable ? 'green' : 'red'} variant="dot">
                            {reachable ? statusQ.data.version : 'unreachable'}
                        </Badge>
                    )}
                    {applied && (
                        <Badge size="xs" color="teal" variant="filled" leftSection={<IconCheck size={9} />}>
                            Applied: {applied}
                        </Badge>
                    )}
                </Group>
            }
            size="xl"
            styles={{
                content: { background: 'var(--surface)', border: '1px solid var(--border)' },
                header: { background: 'var(--surface)' },
            }}
        >
            {statusQ.isLoading && (
                <Group justify="center" py="xl">
                    <Loader size="sm" color="cyan" />
                    <Text c="dimmed" size="sm">Connecting to NetBox…</Text>
                </Group>
            )}

            {statusQ.isSuccess && !reachable && (
                <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="NetBox unreachable" mb="sm">
                    {statusQ.data?.reason || 'Could not connect to the configured NetBox instance.'}
                    {' '}Check <code>NETBOX_URL</code> and <code>NETBOX_TOKEN</code> in your <code>.env</code>.
                </Alert>
            )}

            {statusQ.isSuccess && reachable && (
                <Tabs defaultValue="prefixes" color="cyan">
                    <Tabs.List mb="sm">
                        <Tabs.Tab value="prefixes" leftSection={<IconCirclePlus size={13} />}>
                            Allocate from Prefix
                        </Tabs.Tab>
                        <Tabs.Tab value="ip" leftSection={<IconNetwork size={13} />}>
                            Use Existing IP
                        </Tabs.Tab>
                        <Tabs.Tab value="vlans" leftSection={<IconLayersLinked size={13} />}>
                            VLANs
                        </Tabs.Tab>
                    </Tabs.List>

                    <Tabs.Panel value="prefixes">
                        <PrefixesTab onSelect={handleSelect} hostname={hostname} resourceType={resourceType} />
                    </Tabs.Panel>
                    <Tabs.Panel value="ip">
                        <IPAddressesTab onSelect={handleSelect} />
                    </Tabs.Panel>
                    <Tabs.Panel value="vlans">
                        <VlansTab onSelect={handleSelect} />
                    </Tabs.Panel>
                </Tabs>
            )}
        </Modal>
    );
}
