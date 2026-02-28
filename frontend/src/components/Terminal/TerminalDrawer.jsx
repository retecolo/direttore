import { useEffect, useRef } from 'react';
import { Box, Paper, Text, Group, ActionIcon, rem } from '@mantine/core';
import { IconX, IconTerminal2 } from '@tabler/icons-react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

export default function TerminalDrawer({ opened, onClose }) {
    const terminalRef = useRef(null);
    const xtermRef = useRef(null);
    const fitAddonRef = useRef(null);
    const currentCommand = useRef('');

    useEffect(() => {
        if (!terminalRef.current) return;

        const term = new Terminal({
            cursorBlink: true,
            theme: {
                background: '#0d1117',
                foreground: '#e6edf3',
                cursor: '#00bcd4',
                selectionBackground: 'rgba(0, 188, 212, 0.3)',
            },
            fontSize: 13,
            fontFamily: 'JetBrains Mono, Menlo, Courier New, monospace',
        });

        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);
        term.open(terminalRef.current);
        fitAddon.fit();

        term.writeln('\x1b[1;36m⬡ Direttore Terminal\x1b[0m');
        term.writeln('Welcome to the lab infrastructure console.');
        term.write('\r\n$ ');

        term.onData((data) => {
            const { cursorX } = term.buffer.active;
            const cursorIdx = cursorX - 2;

            if (data === '\r') {
                term.write('\r\n$ ');
                currentCommand.current = '';
            } else if (data === '\u0015') { // Ctrl+U
                const moveBack = cursorX - 2;
                term.write('\x1b[' + moveBack + 'D\x1b[K');
                currentCommand.current = '';
            } else if (data === '\u0001') { // Ctrl+A
                term.write('\x1b[' + (cursorX - 2) + 'D');
            } else if (data === '\u0005') { // Ctrl+E
                const moveForward = currentCommand.current.length - (cursorX - 2);
                if (moveForward > 0) term.write('\x1b[' + moveForward + 'C');
            } else if (data === '\u000b') { // Ctrl+K
                term.write('\x1b[K');
                currentCommand.current = currentCommand.current.slice(0, cursorIdx);
            } else if (data === '\u000c') { // Ctrl+L
                term.clear();
                term.write('\x1b[H\x1b[1;36m⬡ Direttore Terminal\x1b[0m\r\nWelcome to the lab infrastructure console.\r\n$ ');
                currentCommand.current = '';
            } else if (data === '\u007f') { // Backspace
                if (cursorX > 2) {
                    // Supporting backspace from any position
                    const before = currentCommand.current.slice(0, cursorIdx - 1);
                    const after = currentCommand.current.slice(cursorIdx);
                    currentCommand.current = before + after;

                    term.write('\b'); // Move left
                    term.write('\x1b[K'); // Clear to end
                    term.write(after); // Write the 'after' part
                    // Move cursor back to original position
                    if (after.length > 0) {
                        term.write('\x1b[' + after.length + 'D');
                    }
                }
            } else {
                // Only allow printable characters
                if (data.length === 1 && data >= ' ') {
                    // Prevent infinite spacing or overflow beyond terminal width (rough check)
                    if (cursorX < term.cols - 1) {
                        const before = currentCommand.current.slice(0, cursorIdx);
                        const after = currentCommand.current.slice(cursorIdx);
                        currentCommand.current = before + data + after;

                        term.write(data + after);
                        if (after.length > 0) {
                            term.write('\x1b[' + after.length + 'D');
                        }
                    }
                }
            }
        });

        term.attachCustomKeyEventHandler((e) => {
            if (e.key === 'Escape' || e.key === 'F12') {
                return false;
            }
            return true;
        });

        xtermRef.current = term;
        fitAddonRef.current = fitAddon;

        return () => {
            term.dispose();
        };
    }, []);

    useEffect(() => {
        if (opened && fitAddonRef.current) {
            setTimeout(() => fitAddonRef.current.fit(), 100);
            xtermRef.current?.focus();
        }
    }, [opened]);

    // Handle window resize
    useEffect(() => {
        const handleResize = () => {
            if (opened) fitAddonRef.current?.fit();
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [opened]);

    return (
        <Box
            style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                zIndex: 1000,
                transform: opened ? 'translateY(0)' : 'translateY(-100%)',
                transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                pointerEvents: opened ? 'auto' : 'none',
            }}
        >
            <Paper
                shadow="xl"
                style={{
                    height: '40vh',
                    background: '#0d1117',
                    border: '1px solid var(--border)',
                    borderTop: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    borderBottomLeftRadius: '12px',
                    borderBottomRightRadius: '12px',
                    overflow: 'hidden',
                }}
            >
                {/* Header */}
                <Group justify="space-between" px="md" py={6} style={{ borderBottom: '1px solid var(--border)' }}>
                    <Group gap="xs">
                        <IconTerminal2 size={16} color="var(--cyan)" />
                        <Text size="xs" fw={600} c="dimmed">TERMINAL — F12 or ESC to close</Text>
                    </Group>
                    <ActionIcon size="sm" variant="subtle" color="gray" onClick={onClose}>
                        <IconX size={14} />
                    </ActionIcon>
                </Group>

                {/* Terminal Container */}
                <Box
                    ref={terminalRef}
                    style={{
                        flex: 1,
                        padding: '8px',
                        overflow: 'hidden',
                    }}
                />
            </Paper>
        </Box>
    );
}
