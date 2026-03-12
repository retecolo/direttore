# Remote Server Apply — API 502/404 Fix

Run these commands on the server (`100.89.192.21` or `ssh` into it) after pulling the latest code.

## 1. Pull latest code

```bash
cd /opt/direttore
git pull
```

## 2. Restart the API

The API is already running correctly with `--host 0.0.0.0`. Just restart it to pick
up the code changes (improved error logging, `/api/` root endpoint):

```bash
# If started manually — kill it and restart:
pkill -f "uvicorn api.main:app"
PROXMOX_MOCK=false uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &

# If using systemd:
sudo systemctl restart direttore-api
```

Confirm the startup log shows the right host and CORS:
```
INFO api.main: Direttore API ready | mock=False | cors_origins=[...]
INFO api.services.proxmox.client: Connecting to Proxmox at 10.209.5.2 as root@pam
INFO api.services.proxmox.client: Proxmox client initialised (host=10.209.5.2)
```

## 3. Restart the frontend

`vite.config.js` was changed — Vite now:
- Binds to `0.0.0.0` by default (no `--host` flag needed)
- Proxies `/api/*` to `http://127.0.0.1:8000` instead of `http://localhost:8000`
  (fixes the IPv4/IPv6 mismatch that caused API calls to fail)

```bash
cd /opt/direttore/frontend

# Kill the old dev server
pkill -f "vite"   # or Ctrl+C in the terminal running it

# Restart — no --host flag needed now
npm run dev
```

You should see:
```
  VITE v7.x.x  ready in ...ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://100.89.192.21:5173/
```

Visit **http://100.89.192.21:5173/dashboard** — API calls should work cleanly.

## What was broken

| Symptom | Root cause | Fix |
|---|---|---|
| `GET /api/lxc 404` | Vite `localhost:8000` proxy target resolved to `::1` (IPv6); uvicorn at `0.0.0.0` doesn't listen on `::1` → connection refused → broken proxy | Changed proxy target to `http://127.0.0.1:8000` |
| `GET /api/ 404` | No route existed for `/api/` root | Added `/api` endpoint returning route directory |
| Needed `--host` every time | `vite.config.js` had `host: '::1'` | Changed to `host: '0.0.0.0'` |
