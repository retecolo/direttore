import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { Box, Text, Stack, ThemeIcon, rem, Tooltip, UnstyledButton } from '@mantine/core';
import {
    IconLayoutDashboard,
    IconServer,
    IconRocket,
    IconCalendar,
} from '@tabler/icons-react';
import { useEffect } from 'react';
import TerminalDrawer from './Terminal/TerminalDrawer';

const NAV = [
    { to: '/dashboard', label: 'Dashboard', icon: IconLayoutDashboard },
    { to: '/resources', label: 'Resources', icon: IconServer },
    { to: '/provision', label: 'Provision', icon: IconRocket },
    { to: '/reservations', label: 'Reservations', icon: IconCalendar },
];

export default function Layout({ children }) {
    const location = useLocation();
    const [terminalOpened, setTerminalOpened] = useState(false);

    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'F12') {
                e.preventDefault();
                setTerminalOpened((o) => !o);
            } else if (e.key === 'Escape') {
                setTerminalOpened(false);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

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
                    <Text size="xs" c="dimmed">v0.1.0 • mock mode</Text>
                </Box>
            </Box>

            {/* Main content */}
            <Box style={{ flex: 1, overflowY: 'auto', padding: '2rem', position: 'relative' }}>
                <TerminalDrawer
                    opened={terminalOpened}
                    onClose={() => setTerminalOpened(false)}
                />

                {/* Terminal Hint Bar */}
                <UnstyledButton
                    onClick={() => setTerminalOpened(true)}
                    pos="absolute"
                    top={0}
                    left="50%"
                    style={{
                        transform: 'translateX(-50%)',
                        zIndex: 10,
                        border: '1px solid var(--border)',
                        borderTop: 0,
                        borderRadius: '0 0 8px 8px',
                        transition: 'all 0.2s',
                    }}
                    px="md"
                    py={2}
                    bg="rgba(0, 188, 212, 0.05)"
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(0, 188, 212, 0.1)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(0, 188, 212, 0.05)';
                    }}
                >
                    <Text size="10px" fw={700} c="dimmed" tt="uppercase" lts="0.5px">
                        Press F12 to open a terminal
                    </Text>
                </UnstyledButton>

                {children}
            </Box>
        </Box>
    );
}
