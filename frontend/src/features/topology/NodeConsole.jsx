import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export function NodeConsole({ labName, nodeName }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme: { background: '#0e0e0e', foreground: '#00ff00', cursor: '#00ff00' },
      fontSize: 13,
      fontFamily: '"Cascadia Code", "Fira Code", monospace',
      cursorBlink: true,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);

    // Small delay lets the DOM paint before fitting
    const fitTimer = setTimeout(() => fitAddon.fit(), 50);

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/api/containerlab/labs/${encodeURIComponent(labName)}/nodes/${encodeURIComponent(nodeName)}/console`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      term.writeln('\r\x1b[32mConnected.\x1b[0m Type to interact, close the modal to disconnect.\r\n');
    };
    ws.onmessage = (e) => {
      term.write(new Uint8Array(e.data));
    };
    ws.onclose = () => {
      term.writeln('\r\n\x1b[33m[Connection closed]\x1b[0m');
    };
    ws.onerror = () => {
      term.writeln('\r\n\x1b[31m[WebSocket error — is the container running?]\x1b[0m');
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    const observer = new ResizeObserver(() => fitAddon.fit());
    observer.observe(containerRef.current);

    return () => {
      clearTimeout(fitTimer);
      observer.disconnect();
      ws.close();
      term.dispose();
    };
  }, [labName, nodeName]);

  return (
    <div
      ref={containerRef}
      style={{ height: 400, background: '#0e0e0e', borderRadius: 6, overflow: 'hidden', padding: 4 }}
    />
  );
}
