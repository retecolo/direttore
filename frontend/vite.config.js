import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Bind to all interfaces so the dev server is reachable at the host's
    // real IP (e.g. http://100.x.x.x:5173) without needing the --host CLI flag.
    // allowedHosts: true suppresses Vite's host-header check so nginx or
    // any external proxy can forward requests without getting a 403.
    allowedHosts: true,
    host: '::',

    // Proxy /api/* (and docs) to the FastAPI backend.
    //
    // IMPORTANT: use 127.0.0.1, NOT localhost.
    // On many Linux hosts, 'localhost' resolves to ::1 (IPv6) but uvicorn
    // launched with --host 0.0.0.0 only listens on IPv4 interfaces, so the
    // proxy connection will be refused and API calls will fail with 502/ECONNREFUSED.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
      '/docs':         { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/redoc':        { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/openapi.json': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
