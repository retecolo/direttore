import { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Box, Text, Stack, ThemeIcon, rem, Tooltip } from '@mantine/core';
import {
    IconLayoutDashboard,
    IconServer,
    IconRocket,
    IconCalendar,
    IconFlask,
    IconCpu,
    IconNetwork,
} from '@tabler/icons-react';

export default function Layout({ children }) {
    const location = useLocation();
    const navigate = useNavigate();
    const [clabEnabled, setClabEnabled] = useState(false);
    const [proxmoxEnabled, setProxmoxEnabled] = useState(true);

    useEffect(() => {
        fetch('/api/containerlab/status')
            .then(r => { if (r.ok) return r.json(); throw new Error(); })
            .then(() => setClabEnabled(true))
            .catch(() => setClabEnabled(false));
            
        fetch('/api/proxmox/status')
            .then(r => { if (r.ok) return r.json(); throw new Error(); })
            .then(data => setProxmoxEnabled(data.enabled ?? true))
            .catch(() => setProxmoxEnabled(true));
    }, []);

    useEffect(() => {
        // Redirect away from proxmox-only views if proxmox is disabled
        if (!proxmoxEnabled && (location.pathname === '/' || location.pathname === '/dashboard')) {
            if (clabEnabled) {
                navigate('/containerlab', { replace: true });
            } else {
                navigate('/hardware', { replace: true });
            }
        }
    }, [proxmoxEnabled, clabEnabled, location.pathname, navigate]);

    let NAV = [];
    if (proxmoxEnabled) {
        NAV.push({ to: '/dashboard',  label: 'Dashboard',  icon: IconLayoutDashboard });
        NAV.push({ to: '/resources',  label: 'Resources',  icon: IconServer });
        NAV.push({ to: '/provision',  label: 'Provision',  icon: IconRocket });
    }
    NAV.push({ to: '/hardware',   label: 'Hardware',   icon: IconCpu });
    if (clabEnabled) {
        NAV.push({ to: '/containerlab', label: 'ContainerLab', icon: IconNetwork });
    }
    if (proxmoxEnabled) {
        NAV.push({ to: '/lab',        label: 'Lab',        icon: IconFlask });
    }
    NAV.push({ to: '/reservations', label: 'Reservations', icon: IconCalendar });

    return (
        <Box style={{ display: 'flex', minHeight: '100vh', width: '100%', background: 'var(--bg)' }}>
            {/* Sidebar */}
            <Box
                style={{
                    width: 220,
                    background: 'var(--surface)',
                    borderRight: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    padding: '1.25rem 0',
                    flexShrink: 0,
                }}
            >
                {/* Logo */}
                <Box px="lg" pb="xl">
                    <Text fw={700} size="lg" c="cyan.4" style={{ letterSpacing: '-0.5px' }}>
                        ⬡ Direttore
                    </Text>
                    <Text size="xs" c="dimmed">Lab Infrastructure</Text>
                </Box>

                {/* Nav items */}
                <Stack gap={4} px="sm">
                    {NAV.map(({ to, label, icon: Icon }) => {
                        const active = location.pathname.startsWith(to);
                        return (
                            <NavLink
                                key={to}
                                to={to}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: rem(10),
                                    padding: '0.6rem 0.85rem',
                                    borderRadius: 8,
                                    textDecoration: 'none',
                                    color: active ? '#fff' : 'var(--muted)',
                                    background: active ? 'rgba(0,188,212,0.12)' : 'transparent',
                                    fontWeight: active ? 600 : 400,
                                    fontSize: '0.875rem',
                                    transition: 'all 0.15s',
                                    border: active ? '1px solid rgba(0,188,212,0.25)' : '1px solid transparent',
                                }}
                            >
                                <ThemeIcon
                                    size="sm"
                                    variant="transparent"
                                    color={active ? 'cyan' : 'gray'}
                                >
                                    <Icon size={16} />
                                </ThemeIcon>
                                {label}
                            </NavLink>
                        );
                    })}
                </Stack>

                {/* Footer */}
                <Box mt="auto" px="lg" pt="lg">
                    <Text size="xs" c="dimmed">v0.1.0</Text>
                </Box>
            </Box>

            {/* Main content */}
            <Box style={{ flex: 1, overflowY: 'auto', padding: '2rem', position: 'relative' }}>
                {children}
            </Box>
        </Box>
    );
}
