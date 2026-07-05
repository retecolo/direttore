# Direttore — Lab Infrastructure Management Platform

A vendor-agnostic network and compute lab automation platform combining **NetBox** inventory, **Nornir** network device configuration, and a modern **React + FastAPI** web interface for provisioning and reserving Proxmox VMs and LXC containers, managing physical network hardware via **Unimus Pro** and **Git**, and orchestrating virtual network labs with **ContainerLab**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          React Frontend (Vite 7)                             │
│  Dashboard · Resources · Provision Wizard · Hardware · ContainerLab ·        │
│  Lab Topology · Reservation Calendar                                         │
└──────────────┬────────────────────────────────────────────┬─────────────────┘
               │ REST API                                   │
┌──────────────▼────────────────────────────────────────────▼─────────────────┐
│                          FastAPI Backend (api/)                              │
├──────────────┬───────────────┬────────────────┬────────────┬────────────────┤
│  Proxmox     │  Reservations │  NetBox Proxy  │  Hardware  │  ContainerLab  │
│  (proxmoxer) │  (SQLAlchemy) │  (httpx)       │  (Unimus + │  (local/SSH/   │
│  services/   │  models.py    │  services/     │   Git)     │   REST API)    │
│  proxmox/    │               │  netbox/       │            │  services/     │
│              │               │                │            │  containerlab/ │
└──────────────┴───────────────┴────────────────┴────────────┴────────────────┘
        │                          │                  │              │
  Proxmox VE API             NetBox API          Unimus Pro    clab binary /
  (QEMU VMs + LXC)       (Device inventory)   (Config backup)  SSH / REST API
                                                    │
                                             Git HTTPS + PAT
                                          (Config + topology repos)
```

---

## Web UI Features

### Dashboard
Real-time cluster overview — one card per Proxmox node showing CPU, RAM, and disk utilization with auto-refresh every 30 seconds.

### Resources
Browse all VMs and LXC containers across nodes. Start, stop, and delete resources directly from the table. Click any resource row for a detailed modal view.

### Provision Wizard
7-step wizard to provision a new VM or LXC container:
1. **Type** — choose VM (QEMU/KVM) or LXC Container, select target node
2. **Template** — select ISO or container template from node storage
3. **User** — set username, password, and optional SSH public key
4. **Resources** — set name, VMID, CPU cores, RAM, disk size
5. **Network & Storage** — configure storage pool and network interfaces:
   - **Storage**: select from available Proxmox storage pools (shows type and free space)
   - **NICs**: add up to 8 network interfaces per VM/LXC — each with:
     - Bridge selection (live list from the node's configured bridges)
     - Optional VLAN ID (1–4094; empty = untagged)
     - NIC model (VMs: VirtIO / E1000 / RTL8139)
     - Dual-stack IP: **IPv4 / CIDR** (or `dhcp`) + **IPv6 / Prefix** (or `auto` / `dhcp6`)
     - Default gateways (IPv4 / IPv6) and DNS servers
     - ☁ **NetBox IPAM Integration**: Connects to your NetBox instance to browse and select IP addresses, Prefix gateways, and VLANs directly in the wizard.
       - Automatically allocates the next available IP address from a selected Prefix.
       - Smart IPv6 handling (avoids network addresses like `::` and `.0`).
       - Auto-detects explicit default gateways from NetBox records, or gracefully assumes `.1` / `::1` as gateways when absent.
6. **Review** — confirm all settings including per-NIC summary table
7. **Progress** — live task progress bar polling the Proxmox UPID

### Lab Topology
Interactive drag-and-drop canvas (powered by **React Flow / @xyflow/react**) for visualizing and designing your infrastructure topology:
- Drag VMs and LXC containers from the sidebar onto the canvas
- Draw connections between resources to document network relationships
- Snap-to-grid layout with dark-mode dot background
- Node selection highlights with cyan glow; edge selection with stroke emphasis
- Prevents duplicate resources from being placed on the canvas

### Reservation Calendar
FullCalendar week/month/day view. Click any time slot to reserve a resource window. Conflict detection prevents double-booking the same node.

### Hardware Management
Manage physical network devices (routers, switches, firewalls) that are registered in NetBox. Devices are discovered automatically from NetBox DCIM, and the page provides:

- **Device table** — searchable/filterable by name, type, IP, or site; shows both IPv6 and IPv4 management IPs (IPv6 preferred when available) with colour-coded family badges
- **Per-device drawer** with four tabs:
  - **Overview** — NetBox device details: type, manufacturer, site, rack, role, all management IPs, interface table with mgmt-only indicators
  - **Backup** — trigger a real-time backup via Unimus Pro; selectively archive to Unimus, Git, or both; shows git commit SHA and a config preview after completion
  - **Config History** — browsable git log per device; click any commit to view the full config at that point in time with one-click copy
  - **Provision** — push a "golden config" to the live device via Unimus Pro; choose source of truth (Git or Unimus latest backup); Git source lets you pick any historical commit
- **Status badges** (header) — real-time reachability indicators for Unimus (shows device count) and Git repo (shows configured branch)
- **Integration warnings** — actionable alerts when `UNIMUS_URL` or `GIT_CONFIG_REPO` are not configured

### ContainerLab
Orchestrate virtual network topologies powered by [ContainerLab](https://containerlab.dev). The page is **hidden from the sidebar unless `CLAB_MODE` is set** in `.env`. Three backends are supported:

| Mode | How it works |
|---|---|
| `local` | Calls the `clab` binary directly on the Direttore host. The process user must be a member of the `clab_admins` group. |
| `ssh` | Connects via SSH (using `paramiko`) to a remote host running ContainerLab. |
| `rest` | Calls the [clab-api-server](https://github.com/srl-labs/clab-api-server) HTTP REST API on a remote host. |

Page features:
- **Status badge** — shows backend mode (local / ssh / rest) and live reachability
- **Running labs table** — name, node count, topology path, and **lab age** (how long ago the lab was deployed); click any row to open the lab detail drawer
- **Lab detail drawer** — per-node table with kind, image, IPv4/IPv6, and **colour-coded container state** (running / stopped / error)
  - **Per-node actions**: restart, stop, or start individual nodes without tearing down the whole lab
  - **In-browser terminal**: click the console button on any running node to open a full xterm.js terminal session over WebSocket — no SSH client or ProxyJump needed
  - **SSH ProxyJump commands**: copy a ready-made `ssh -J ...` command for direct terminal access outside the browser
- **Deploy panel** — select any `.yml` topology file and deploy with configurable options:
  - **Reconfigure toggle** — choose whether to run `clab deploy --reconfigure` (redeploys existing nodes) or a plain deploy
  - **Pre-deploy validation** — validate the topology file with `clab deploy --check` before committing; result shown inline
  - **Topology graph preview** — an interactive React Flow canvas renders the node/link graph parsed directly from the YAML before you deploy
  - **YAML editor** — edit the topology file in-browser with syntax highlighting before deploying
  - **Real-time deploy log** — streaming SSE output with manual dismissal
- **Destroy confirmation dialogue** — confirm before destroying a running lab to prevent accidental teardown
- **Topology Workspace** — a fully interactive file manager for `CLAB_TOPO_DIR`:
  - Create, rename, duplicate, and delete folders and files in-browser
  - Create and edit text files (`.cfg`, `.cli`, `.json`, `.yml`) directly in the browser
  - Navigate directories using dynamic breadcrumbs
  - **Git history tab** — per-file commit log shown when `CLAB_TOPO_GIT_REPO` is configured
  - Deploy directly from any `.yml` topology file within the workspace
- **Topology upload** — file-picker upload of `.yml` and config files targeting the current workspace directory
- All sub-features (Git history tab, SSH/REST indicators) are hidden when their respective env vars are not set

#### Accessing ContainerLab Nodes via SSH

ContainerLab exposes native SSH on the mgmt network bridge of the deployment host (usually `172.20.20.0/24`). You can find the exact node IPs within the Direttore "Inspect" drawer.

**Local Mode:**
If Direttore and your labs run locally on your machine, simply connect directly:
```bash
ssh admin@172.20.20.3
```

**SSH Remote Mode (ProxyJump):**
If Direttore deploys labs to a remote SSH worker (e.g. `CLAB_MODE=ssh`), your workstation does not have a direct route to `172.20.20.x`. Direttore addresses this by surfacing a **Console ProxyJump Command** directly in the Lab drawer!

Clicking the console button will automatically copy an SSH command formatted like this:
```bash
ssh -J root@my-clab-worker admin@172.20.20.3
```
This instantly routes your SSH session _through_ the worker node into the virtual container, giving you immediate terminal access without any VPNs or static routes.

> **Pro-Tip**: You can persist this routing structure in your `~/.ssh/config`:
> ```ssh-config
> Host 172.20.20.*
>     ProxyJump root@my-clab-worker
>     User admin
> ```
> With this block, you can simply run `ssh 172.20.20.3` and your SSH client will automatically jump through the remote worker!

#### Unimus connectivity notes

Unimus is contacted from the **server running Direttore**, not from your browser. Common issues:

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectError: All connection attempts failed` | DNS doesn't resolve from server, or wrong hostname | Use the bare IP address in `UNIMUS_URL` (e.g. `https://10.x.x.x`) |
| Same error with IPv6 host | Must use bracket notation | `UNIMUS_URL=https://[2001:db8::10]` |
| HTTP 401 | Wrong or expired API token | Re-generate in Unimus → Settings → Security → API access tokens |
| HTTP 403 | Token lacks API permission | Enable "API Access" scope for the token |
| Devices found but backup returns "not found in Unimus" | Unimus stores devices by **hostname**, not IP — and there is no DNS | Use the manual Unimus device link (see below) |
| Backup fails with `404` on `/api/v2/jobs/backupDevices` | Wrong endpoint for your Unimus version | Direttore auto-detects: tries `PATCH /api/v2/jobs/backup` first (2.8+), then POST variants |
| Backup warning: "no working job endpoint found" | None of the trigger endpoints returned 2xx | The fallback returns the **latest existing** Unimus backup — still archives it to Git |

Use the built-in debug endpoint to diagnose from the server:
```bash
curl -s http://127.0.0.1:8000/api/hardware/debug-unimus | python3 -m json.tool
```
This now probes **all known job endpoint variants** (GET and POST/PATCH) so you can see exactly which ones your Unimus installation exposes.

#### Linking a NetBox device to a Unimus device (no DNS required)

When Direttore cannot automatically match a NetBox device to a Unimus device (because Unimus stores devices by FQDN but there is no DNS), use the manual link API:

```bash
# Step 1 — list all devices known to Unimus (to find the right address string)
curl -s http://127.0.0.1:8000/api/hardware/unimus-devices | python3 -m json.tool
# Output: [{"id": 5, "address": "gw1.mgt.cu-es.net", "vendor": "MikroTik", ...}, ...]

# Step 2 — link the NetBox device ID to the Unimus address
# (Find the NetBox device ID from the Hardware page URL or from /api/hardware/devices)
curl -s -X PUT http://127.0.0.1:8000/api/hardware/devices/2/unimus-link \
  -H "Content-Type: application/json" \
  -d '{"unimus_address": "gw1.mgt.cu-es.net"}'

# Step 3 — verify
curl -s http://127.0.0.1:8000/api/hardware/devices/2/unimus-link | python3 -m json.tool

# To remove a link (e.g. after DNS is configured and auto-match works again)
curl -s -X DELETE http://127.0.0.1:8000/api/hardware/devices/2/unimus-link
```

Links are stored in `/opt/unimus_links.json` (one directory above `GIT_CONFIG_LOCAL_PATH`) and persist across restarts. When a link exists, it takes priority over all automatic discovery strategies.

#### Automatic Unimus device discovery order

When a backup or provision is triggered, Direttore searches for the Unimus device using these strategies in order:

| Priority | Strategy | Details |
|---|---|---|
| 0 | **Manual link store** | Fastest — uses the pinned `unimus_address` if set via the link API |
| 1 | **Exact address match** | `findByAddress(primary_ip)` — works if Unimus stores the device by IP |
| 2 | **Reverse DNS** | Resolves primary IP to FQDN, then tries `findByAddress(fqdn)` |
| 3 | **NetBox device name** | Tries `findByAddress(hostname)` directly |
| 4 | **Linear scan** | Fetches all Unimus devices and matches by address substring / device name |

---

## Screenshots

### Dashboard
![Dashboard — Proxmox node cards with resource usage](docs/screenshots/dashboard.png)

### Resource Browser
![Resources — VM table with status and action buttons](docs/screenshots/resources.png)

### Provision Wizard (Step 4 — Resources)
![Provision wizard showing resource configuration step](docs/screenshots/provision.png)

### Reservation Calendar
![Reservations calendar with scheduled lab sessions](docs/screenshots/reservations.png)

---

## Prerequisites

- **Python 3.13+** (backend)
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (replaces pip/venv)
- **Node.js 20.19+** (frontend — see install guide below)
- A Proxmox VE host, **or** use `PROXMOX_MOCK=true` for development without hardware
- NetBox instance (optional — only needed for the inventory proxy routes and NetBox NIC picker)
- **ContainerLab** (optional — only needed for the ContainerLab management page)

> [!IMPORTANT]
> Node.js **20.19+** is required by Vite 7. The system `apt` packages on Debian/Ubuntu are often too old, and binaries compiled for newer microarchitectures can produce `Illegal instruction` crashes on older or virtualized CPUs. **Use `nvm` to install Node** — it compiles a native binary that matches your CPU.

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd direttore
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Proxmox host, credentials, and NetBox token
# Set PROXMOX_MOCK=true for development without real hardware
```

### 3. Backend setup

The backend is managed with [`uv`](https://docs.astral.sh/uv/). Install it if you don't have it:

```bash
# Install uv (macOS / Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install and run:

```bash
# Install all dependencies from pyproject.toml + uv.lock
uv sync

# Start the API server (IPv6 loopback; adjust host as needed)
PROXMOX_MOCK=true uv run uvicorn api.main:app --host ::1 --reload --port 8000

# Or on IPv4 / all interfaces:
PROXMOX_MOCK=true uv run uvicorn api.main:app --host 0.0.0.0 --reload --port 8000
```

API docs available at **http://localhost:8000/docs** (Swagger) and **http://localhost:8000/redoc** (ReDoc).
Health check: **http://localhost:8000/healthz**

### 4. Frontend setup

If you do not have Node.js and `npm` installed, the recommended and most reliable way to install them (and to avoid architecture or "Illegal instruction" errors) is via [Node Version Manager (nvm)](https://github.com/nvm-sh/nvm):

```bash
# 1. Install NVM
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# 2. Activate NVM (or restart your terminal)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 3. Install Node.js 20 (LTS)
nvm install 20
nvm use 20
```

> **Note on "Illegal instruction" errors:** If you receive an `Illegal instruction` error when running `npm` or `node`, your CPU might lack the latest instruction sets (like SSE4.1/AVX) required by Node 20+. If you installed using a package manager (e.g. `apt install nsolid` or `snap`), remove those packages (`sudo apt remove nsolid nodejs npm`). Use `nvm` as shown above. If `nvm install 20` still yields "Illegal instruction", fallback to Node 18 by running `nvm install 18 && nvm use 18`.

Then, to install dependencies and run the development server:

```bash
cd frontend
npm install
npm run dev
```

Frontend available at **http://[::1]:5173** (or **http://localhost:5173**).

> **Note:** Vite is configured to bind to `::1` (IPv6 loopback). If your system doesn't have IPv6 loopback, change `host: '::1'` to `host: '0.0.0.0'` in `frontend/vite.config.js`.

The Vite dev server also proxies the following paths directly to the FastAPI backend (no nginx required during development):

| Vite proxy path | Backend |
|---|---|
| `/api/*` | `http://localhost:8000` |
| `/docs` | `http://localhost:8000` |
| `/redoc` | `http://localhost:8000` |
| `/openapi.json` | `http://localhost:8000` |

---

## Environment Variables

### Stack Mode (Docker deployments)

Controls which address families Traefik binds on the host. IPv6 / dual-stack is the default. See [docs/daemon-ipv6.md](docs/daemon-ipv6.md) for Docker daemon setup.

| Variable | Default | Description |
|---|---|---|
| `TRAEFIK_HOST_IP` | `::` | Host IP for Docker port bindings. `::` = dual-stack (IPv4+IPv6); `0.0.0.0` = IPv4 only |
| `TRAEFIK_BIND_ADDR` | `[::]` | Address Traefik entrypoints bind inside the container. `[::]` = all; `0.0.0.0` = IPv4 only |
| `ENABLE_IPV6` | `true` | Adds an IPv6 IPAM subnet (`fd00:0:1::/64`) to the internal Docker proxy network |

| Mode | `TRAEFIK_HOST_IP` | `TRAEFIK_BIND_ADDR` | `ENABLE_IPV6` |
|---|---|---|---|
| Dual-stack / IPv6-preferred (default) | `::` | `[::]` | `true` |
| IPv6-only | `::` | `[::]` | `true` + drop IPv4 at host firewall |
| IPv4-only | `0.0.0.0` | `0.0.0.0` | `false` |

### Traefik / TLS (Docker deployments)

| Variable | Default | Description |
|---|---|---|
| `DOMAIN` | `direttore.example.com` | Public hostname Traefik routes and requests a certificate for |
| `ACME_EMAIL` | `admin@example.com` | Email sent to Let's Encrypt for expiry notifications |

### Core

| Variable | Default | Description |
|---|---|---|
| `PROXMOX_HOST` | `192.168.1.100` | Proxmox VE hostname or IP |
| `PROXMOX_USER` | `root@pam` | Proxmox API user |
| `PROXMOX_PASSWORD` | — | Proxmox API password |
| `PROXMOX_VERIFY_SSL` | `false` | Verify TLS certificate |
| `PROXMOX_MOCK` | `false` | Use mock data (no real Proxmox needed) |
| `NETBOX_URL` | `http://localhost:8000` | NetBox base URL |
| `NETBOX_TOKEN` | — | NetBox API token |
| `DATABASE_URL` | `sqlite+aiosqlite:///./direttore.db` | SQLAlchemy async DB URL |
| `API_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed CORS origins |

### Hardware Management (Unimus + Git)

| Variable | Default | Description |
|---|---|---|
| **`UNIMUS_URL`** | — | Unimus base URL — e.g. `https://unimus.example.com` or `https://[2001:db8::10]` for IPv6 hosts |
| **`UNIMUS_TOKEN`** | — | Unimus API Bearer token (Settings → Security → API access tokens) |
| **`GIT_CONFIG_REPO`** | — | HTTPS clone URL of the config archive repo (e.g. `https://github.com/org/configs.git`) |
| **`GIT_CONFIG_BRANCH`** | `main` | Branch to commit device configs to |
| **`GIT_CONFIG_AUTH_TOKEN`** | — | Personal Access Token for HTTPS Git auth (needs repo read+write scope) |
| **`GIT_CONFIG_LOCAL_PATH`** | `/opt/direttore/config-repo` | Local clone path on the server |
| **`GIT_CONFIG_AUTHOR_NAME`** | `Direttore` | Git commit author name |
| **`GIT_CONFIG_AUTHOR_EMAIL`** | `direttore@localhost` | Git commit author email |

### ContainerLab

Leave `CLAB_MODE` empty (or omit it) to hide the ContainerLab page entirely.

| Variable | Default | Description |
|---|---|---|
| **`CLAB_MODE`** | _(empty — hidden)_ | Backend mode: `local` \| `ssh` \| `rest` |
| `CLAB_BINARY` | `clab` | Path to the `clab` binary (local mode) |
| `CLAB_TOPO_DIR` | `/opt/direttore/topologies` | Directory where topology `.yml` files are stored |
| `CLAB_SSH_HOST` | — | Hostname/IP of remote clab host (ssh mode) |
| `CLAB_SSH_PORT` | `22` | SSH port (ssh mode) |
| `CLAB_SSH_USER` | `root` | SSH username (ssh mode) |
| `CLAB_SSH_KEY_PATH` | — | Path to SSH private key file (ssh mode) |
| `CLAB_SSH_PASSWORD` | — | SSH password fallback — prefer key auth (ssh mode) |
| `CLAB_API_URL` | — | Base URL of the clab-api-server (rest mode), e.g. `https://clab-host:8080` |
| `CLAB_API_TOKEN` | — | Bearer token for clab-api-server auth (rest mode) |
| `CLAB_API_USERNAME` | — | HTTP Basic username for clab-api-server (rest mode) |
| `CLAB_API_PASSWORD` | — | HTTP Basic password for clab-api-server (rest mode) |
| `CLAB_API_VERIFY_SSL` | `true` | Verify TLS for clab-api-server (rest mode) |
| `CLAB_TOPO_GIT_REPO` | — | HTTPS clone URL for topology Git backing (any mode) |
| `CLAB_TOPO_GIT_BRANCH` | `main` | Branch for topology Git repo |
| `CLAB_TOPO_GIT_AUTH_TOKEN` | — | PAT for topology Git repo HTTPS push |
| `CLAB_TOPO_GIT_LOCAL_PATH` | `/opt/direttore/clab-topologies` | Local clone path for topology Git repo |

---

## API Reference

### Proxmox Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/proxmox/nodes` | List nodes with CPU/RAM/disk stats |
| `GET` | `/api/proxmox/nodes/{node}/networks` | List bridge interfaces on a node |
| `GET` | `/api/proxmox/nodes/{node}/storage` | List storage pools that support VM/CT disks |
| `GET` | `/api/proxmox/nodes/{node}/vms` | List QEMU VMs |
| `POST` | `/api/proxmox/nodes/{node}/vms` | Create a VM (supports multi-NIC, VLAN, storage selection) |
| `POST` | `/api/proxmox/nodes/{node}/vms/{vmid}/{action}` | start / stop / reboot / shutdown / delete |
| `GET` | `/api/proxmox/nodes/{node}/lxc` | List LXC containers |
| `POST` | `/api/proxmox/nodes/{node}/lxc` | Create a container (supports multi-NIC, VLAN, storage selection) |
| `POST` | `/api/proxmox/nodes/{node}/lxc/{vmid}/{action}` | start / stop / reboot / shutdown / delete |
| `GET` | `/api/proxmox/nodes/{node}/templates` | List available ISOs and templates |
| `GET` | `/api/proxmox/tasks/{node}/{upid}` | Poll task status by UPID |

#### VM creation request body (`POST /api/proxmox/nodes/{node}/vms`)

```json
{
  "vmid": 1042,
  "name": "my-vm",
  "cores": 2,
  "memory": 2048,
  "disk": "32G",
  "storage": "local-lvm",
  "iso": "local:iso/ubuntu-22.04.4-live-server-amd64.iso",
  "username": "labuser",
  "password": "changeme",
  "ssh_key": "ssh-ed25519 AAAA...",
  "nics": [
    { "bridge": "vmbr0", "model": "virtio", "vlan": null },
    { "bridge": "vmbr1", "model": "e1000", "vlan": 100, "ip": "10.0.0.5/24", "gw": "10.0.0.1", "ip6": "2001:db8::5/64", "dns": "1.1.1.1 8.8.8.8" }
  ]
}
```

#### LXC creation request body (`POST /api/proxmox/nodes/{node}/lxc`)

```json
{
  "vmid": 3001,
  "hostname": "my-container",
  "cores": 1,
  "memory": 512,
  "storage": "local-lvm",
  "disk_size": 8,
  "template": "local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.gz",
  "username": "labuser",
  "password": "changeme",
  "ssh_key": "ssh-ed25519 AAAA...",
  "nics": [
    { "name": "eth0", "bridge": "vmbr0", "ip": "dhcp", "ip6": "auto", "vlan": null },
    { "name": "eth1", "bridge": "vmbr1", "ip": "10.10.100.5/24", "gw": "10.10.100.1", "ip6": "2001:db8::100:5/64", "gw6": "2001:db8::100:1", "dns": "1.1.1.1 2606:4700:4700::1111", "vlan": 200 }
  ],
  "unprivileged": true,
  "start_after_create": true
}
```

### Reservation Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/reservations/` | List reservations (filterable by `?start=&end=`) |
| `POST` | `/api/reservations/` | Create reservation (conflict check included) |
| `GET` | `/api/reservations/{id}` | Get a single reservation |
| `PATCH` | `/api/reservations/{id}` | Update a reservation |
| `DELETE` | `/api/reservations/{id}` | Cancel a reservation |
| `GET` | `/api/reservations/export/ical` | iCAL feed for calendar apps |

### Inventory Endpoints (NetBox proxy)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/inventory/netbox-status` | Quick reachability check |
| `GET` | `/api/inventory/devices` | Proxy NetBox device list |
| `GET` | `/api/inventory/ip-addresses` | IP addresses with dual-stack and DNS info |
| `GET` | `/api/inventory/prefixes` | IP prefixes with gateway and DNS hints |
| `GET` | `/api/inventory/vlans` | VLANs list |

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Returns `{"status":"ok","mock_mode":<bool>}` |

### Hardware Endpoints (Unimus Pro + Git)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/hardware/status` | Reachability check for Unimus and Git config repo |
| `GET` | `/api/hardware/debug-unimus` | Raw multi-endpoint probe for Unimus — returns full HTTP status/body for debugging |
| `GET` | `/api/hardware/devices` | List physical devices from NetBox (filterable: `?site=&role=&status=&limit=`) |
| `GET` | `/api/hardware/devices/{id}` | Full device detail: NetBox data + interface table, dual-stack mgmt IPs |
| `POST` | `/api/hardware/devices/{id}/backup` | Trigger Unimus backup → poll until done → retrieve config → commit to Git |
| `GET` | `/api/hardware/devices/{id}/configs` | Git log for this device's config file (`?limit=30`) |
| `GET` | `/api/hardware/devices/{id}/configs/{ref}` | Config file content at a specific git commit SHA |
| `POST` | `/api/hardware/devices/{id}/provision` | Push golden config to device via Unimus Pro |
| `GET` | `/api/hardware/devices/{id}/unimus-link` | Get the manually pinned Unimus address for this device |
| `PUT` | `/api/hardware/devices/{id}/unimus-link` | Set a manual Unimus device link (`{"unimus_address": "host.example.com"}`) |
| `DELETE` | `/api/hardware/devices/{id}/unimus-link` | Remove a manual Unimus device link |
| `GET` | `/api/hardware/unimus-devices` | List all devices known to Unimus (id, address, vendor, type, lastJobStatus) |

#### Backup request body (`POST /api/hardware/devices/{id}/backup`)

```json
{ "targets": ["unimus", "git"] }
```

`targets` is optional — defaults to both. Use `["unimus"]` to skip Git archiving or `["git"]` to archive an existing Unimus backup without re-triggering.

> [!NOTE]
> **Unimus version compatibility:** Direttore detects the correct backup trigger endpoint automatically:
> - **Unimus 2.8+**: `PATCH /api/v2/jobs/backup?deviceIds=<id>` (query param, no JSON body)
> - **Older Unimus**: tries several `POST /api/v2/jobs/*` variants
> - **Fallback**: if no trigger endpoint works, archives the latest backup already stored in Unimus
>
> The backup response includes `"tried_endpoints"` showing which endpoints were attempted.

#### Provision request body (`POST /api/hardware/devices/{id}/provision`)

```json
{
  "source": "git",
  "git_ref": "a1b2c3d4",
  "note": "Rolling back after bad change"
}
```

| Field | Values | Description |
|---|---|---|
| `source` | `"git"` \| `"unimus"` | Source of truth for the golden config |
| `git_ref` | commit SHA or `null` | `null` = HEAD (latest committed config); ignored when `source="unimus"` |
| `note` | string | Human-readable note attached to the Unimus push job |

> [!WARNING]
> Provisioning pushes a config to a **live device** via Unimus Pro. Always verify the selected config in the Config History tab before provisioning.

---

## ContainerLab API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/containerlab/status` | Backend reachability check; returns mode, version, and configured features |
| `GET` | `/api/containerlab/labs` | List all running labs (`clab inspect --all`) |
| `GET` | `/api/containerlab/labs/{name}` | Inspect a specific lab — returns per-node detail |
| `POST` | `/api/containerlab/labs` | Deploy a topology (`{"topo_file": "example.yml", "reconfigure": true}`) |
| `POST` | `/api/containerlab/labs/validate` | Validate a topology file without deploying (`clab deploy --check`) |
| `POST` | `/api/containerlab/labs/deploy-stream` | Deploy and stream output back as SSE (`text/event-stream`) |
| `DELETE` | `/api/containerlab/labs/{name}` | Destroy a running lab |
| `POST` | `/api/containerlab/labs/{name}/nodes/{node}/action` | Run `start`, `stop`, or `restart` on a single node (`{"action": "restart"}`) |
| `WebSocket` | `/api/containerlab/labs/{name}/nodes/{node}/console` | In-browser xterm.js terminal session for a node container |
| `GET` | `/api/containerlab/topologies` | List `.yml` topology files in `CLAB_TOPO_DIR` |
| `GET` | `/api/containerlab/topologies/{filename}` | Return raw YAML + optional Git history for a topology file |
| `POST` | `/api/containerlab/topologies` | Upload a new topology file (`multipart/form-data`) |
| `GET` | `/api/containerlab/topologies/{filename}/history` | Git commit history for a topology file (requires `CLAB_TOPO_GIT_REPO`) |
| `GET` | `/api/containerlab/workspace/{subpath}` | List workspace directory contents |
| `POST` | `/api/containerlab/workspace/folder` | Create a new folder in the workspace |
| `POST` | `/api/containerlab/workspace/file` | Create or overwrite a workspace file |
| `DELETE` | `/api/containerlab/workspace/file` | Delete a workspace file |
| `POST` | `/api/containerlab/workspace/rename` | Rename a file or folder in the workspace |
| `POST` | `/api/containerlab/workspace/duplicate` | Duplicate a file to a new name in the same directory |

> [!NOTE]
> All `/api/containerlab/*` endpoints return **HTTP 503** if `CLAB_MODE` is not set. The sidebar nav item is also hidden client-side until the status endpoint returns 200.


## HTTPS on a Bare-Metal Install

> **Docker deployments** use Traefik instead — see the [Docker Compose](#docker-compose) section. This section covers bare-metal installs where Direttore runs directly under `systemd` and nginx provides TLS termination.

Config files live in [`docs/nginx/`](docs/nginx/):

| File | Purpose |
|---|---|
| [`direttore.conf`](docs/nginx/direttore.conf) | Main server block — HTTP→HTTPS redirect, TLS, upstream proxy |
| [`websocket_map.conf`](docs/nginx/websocket_map.conf) | `map` block for WebSocket / Vite HMR — goes in the `http {}` context |

### URL routing

| Path | Upstream |
|---|---|
| `/api/*` | FastAPI backend — `[::1]:8000` |
| `/docs`, `/redoc`, `/openapi.json` | FastAPI Swagger / ReDoc |
| `/` (everything else) | React (Vite dev `[::1]:5173`, or built `dist/` served by nginx) |

### Step 1 — Get a TLS certificate

**Option A — Let's Encrypt via Certbot (recommended for public-facing hosts)**

```bash
sudo apt install certbot python3-certbot-nginx   # Debian/Ubuntu
sudo certbot --nginx -d direttore.example.com
```

Certbot will edit nginx config automatically and schedule auto-renewal. Skip to Step 3 once done.

**Option B — Let's Encrypt via standalone (no nginx running yet)**

```bash
sudo certbot certonly --standalone -d direttore.example.com
# Certificates written to /etc/letsencrypt/live/direttore.example.com/
```

**Option C — Bring your own certificate**

Place your cert and key at any path and update `ssl_certificate` / `ssl_certificate_key` in `direttore.conf` accordingly.

**Auto-renewal** (certbot installs a systemd timer automatically; verify with):

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

### Step 2 — Install nginx config

```bash
# 1. Install the WebSocket map snippet (http context — required for Vite HMR)
sudo cp docs/nginx/websocket_map.conf /etc/nginx/conf.d/

# 2. Install the site config
sudo cp docs/nginx/direttore.conf /etc/nginx/sites-available/direttore
sudo ln -s /etc/nginx/sites-available/direttore /etc/nginx/sites-enabled/

# 3. Edit the two server_name lines and the ssl_certificate paths
sudo nano /etc/nginx/sites-available/direttore

# 4. Validate and reload
sudo nginx -t && sudo systemctl reload nginx
```

### Step 3 — Verify upstream addresses

The default `direttore.conf` uses `[::1]:8000` (IPv6 loopback) for the FastAPI upstream and `[::1]:5173` for Vite. This matches the default `--host ::` in both `Dockerfile.api` and `vite.config.js`.

If your systemd services still bind to `0.0.0.0` (IPv4 only), change the upstream `server` lines in `direttore.conf` back to `127.0.0.1:8000` / `127.0.0.1:5173`, or update the service to use `--host ::`.

### Step 4 — Set CORS origins

nginx terminates TLS, so the browser reaches the API as `https://direttore.example.com`. Add that origin to `.env`:

```
API_CORS_ORIGINS=https://direttore.example.com
```

Restart the API after changing `.env`:

```bash
sudo systemctl restart direttore-api
```

### IPv6 considerations

The `direttore.conf` upstream block and both `listen` directives already support dual-stack:

```nginx
listen 80;          # IPv4
listen [::]:80;     # IPv6
listen 443 ssl;
listen [::]:443 ssl;
```

The OCSP resolver list includes both IPv4 and IPv6 addresses (`1.1.1.1`, `8.8.8.8`, `2606:4700:4700::1111`, `2001:4860:4860::8888`) so stapling works on IPv6-only hosts.

For an **IPv6-only** host, ensure your DNS has an AAAA record for the domain and that the Let's Encrypt CA can reach port 80 over IPv6 during the HTTP-01 challenge.

### No TLS yet?

`direttore.conf` includes a commented-out plain HTTP server block at the bottom — uncomment it and delete the HTTPS blocks for internal/staging use.

> [!IMPORTANT]
> **Vite host check** — Vite's dev server rejects requests whose `Host` header doesn't match `localhost`/`127.0.0.1`. When nginx proxies from a real hostname, Vite returns an *"Invalid Host header"* error. `vite.config.js` already sets `allowedHosts: 'all'` to prevent this. If you see a blank page, make sure Vite was **restarted** after any config change.

---

## Systemd Services (Production)

For bare-metal production deployments, Direttore includes `systemd` service files to keep the API and Vite server running in the background.

```bash
# 1. Copy the unit files into systemd
sudo cp systemd/direttore-api.service /etc/systemd/system/
sudo cp systemd/direttore-frontend.service /etc/systemd/system/

# 2. Reload daemon, enable, and start
sudo systemctl daemon-reload
sudo systemctl enable --now direttore-api
sudo systemctl enable --now direttore-frontend

# 3. Check status
sudo systemctl status direttore-api
```

---

## Docker Compose

### Quick-start (production — Traefik + Let's Encrypt)

`docker-compose.yml` uses [Traefik](https://traefik.io) as the sole externally-exposed service. Traefik automatically obtains and renews a Let's Encrypt certificate for your domain and redirects all HTTP traffic to HTTPS. The `api` and `frontend` services are not reachable from outside the host — only Traefik can reach them. Traffic to `/api/*` is routed directly to the FastAPI backend (WebSocket and SSE work natively); everything else goes to the nginx frontend container.

**Prerequisites:**
- Port 80 and 443 open on the host firewall
- DNS for `DOMAIN` resolving to this host **before** you start the stack (Let's Encrypt performs an HTTP-01 challenge on first boot)
- For IPv6 / dual-stack: Docker daemon IPv6 enabled — see [docs/daemon-ipv6.md](docs/daemon-ipv6.md)

```bash
cp .env.example .env
# Required: set your public hostname and ACME email
# DOMAIN=direttore.example.com
# ACME_EMAIL=admin@example.com
#
# Stack mode (defaults to dual-stack / IPv6-preferred):
# TRAEFIK_HOST_IP=::        # or 0.0.0.0 for IPv4-only
# TRAEFIK_BIND_ADDR=[::]    # or 0.0.0.0 for IPv4-only
# ENABLE_IPV6=true          # set false for IPv4-only

docker compose up -d
```

Once up, the app is available at **https://your.domain** — HTTP requests are redirected to HTTPS automatically.

> **Certificate storage**: Let's Encrypt state is persisted in the `letsencrypt` Docker volume so certificates survive container restarts and are reused across deploys.

### Full Dev Stack (`docker-compose.dev.yml`)

The dev compose file brings up the complete local environment including a Proxmox container, NetBox, PostgreSQL, and Redis:

```bash
docker compose -f docker-compose.dev.yml up
```

| Service | Port | Description |
|---|---|---|
| `api` | 8000 | FastAPI backend (hot-reload via volume mount) |
| `frontend` | 5173 | Vite dev server (hot-reload via volume mount) |
| `proxmox` | 8006 | Proxmox VE 8 container (`rtedpro/proxmox:8.4.1-arm64`) |
| `netbox` | 8080 | NetBox v3.7 (admin/superuserpassword) |
| `postgres` | — | PostgreSQL 15 for NetBox |
| `redis` | — | Redis 7 for NetBox |

#### Initialize the Proxmox dev container

After the dev stack is up, run the included setup script to configure the Proxmox container with templates, ISOs, and network bridges:

```bash
bash api/scripts/init_proxmox_node.sh
```

This script:
- Sets the root password to `root`
- Updates the LXC appliance template list
- Downloads Ubuntu 22.04 and Debian 12 LXC templates
- Stubs out Rocky 9 and Ubuntu 22.04 ISO files
- Creates `vmbr0` and `vmbr1` network bridges
- Regenerates SSL certificates (fixes `pveproxy` startup errors)

#### Seed test data

```bash
bash api/scripts/seed_test_resources.sh
```

---

## Project Structure

```
direttore/
├── api/                          # FastAPI backend
│   ├── main.py                   # App entrypoint, CORS, lifespan
│   ├── config.py                 # Pydantic-settings from .env
│   ├── db.py                     # Async SQLAlchemy engine
│   ├── models.py                 # Reservation, ResourcePool ORM models
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── proxmox.py
│   │   ├── reservations.py
│   │   └── inventory.py
│   ├── services/                 # Business logic / external integrations
│   │   ├── proxmox/
│   │   │   ├── client.py         # proxmoxer wrapper + mock data
│   │   │   ├── vms.py            # QEMU VM CRUD
│   │   │   ├── containers.py     # LXC container CRUD
│   │   │   ├── templates.py      # ISO/template listing
│   │   │   ├── network.py        # Bridge interface listing
│   │   │   └── storage.py        # Storage pool listing
│   │   ├── netbox/               # NetBox API client + IPAM allocation
│   │   ├── unimus/               # Unimus Pro REST API client
│   │   │   └── __init__.py       #   backup/poll/push, _unwrap normalizer
│   │   ├── git_config/           # Git config archive service
│   │   │   └── __init__.py       #   clone/pull/read/write/push
│   │   └── containerlab/         # ContainerLab service (local/SSH/REST backends)
│   │       └── __init__.py       #   deploy/destroy/inspect/topology CRUD
│   ├── routes/                   # FastAPI routers
│   │   ├── proxmox.py            # /api/proxmox/* routes
│   │   ├── reservations.py       # /api/reservations/* routes
│   │   ├── inventory.py          # /api/inventory/* routes
│   │   ├── hardware.py           # /api/hardware/* routes
│   │   └── containerlab.py       # /api/containerlab/* routes
│   └── scripts/                  # Dev / ops helper scripts
│       ├── init_proxmox_node.sh  # Bootstrap Proxmox Docker container
│       └── seed_test_resources.sh
├── frontend/                     # React + Vite SPA
│   ├── src/
│   │   ├── api/                  # Axios client + typed API functions
│   │   │   ├── client.js         # Axios base instance
│   │   │   ├── hardware.js       # Hardware management calls
│   │   │   ├── containerlab.js   # ContainerLab API calls
│   │   │   └── ...               # Other API modules
│   │   ├── components/
│   │   │   ├── Layout.jsx        # Sidebar navigation
│   │   │   └── NetBoxNicPicker.jsx  # NetBox IPAM modal
│   │   ├── features/
│   │   │   ├── provisioning/     # Wizard steps, hooks, utils
│   │   │   └── topology/         # Lab Topology canvas
│   │   └── pages/
│   │       ├── Dashboard.jsx     # Node cards + resource bars
│   │       ├── Resources.jsx     # VM/CT table with actions
│   │       ├── Provision.jsx     # Provision wizard wrapper
│   │       ├── Hardware.jsx      # Physical device management
│   │       ├── ContainerLab.jsx  # ContainerLab topology management
│   │       ├── Lab.jsx           # React Flow topology canvas
│   │       └── Reservations.jsx  # FullCalendar + booking modal
│   ├── vite.config.js
│   └── Dockerfile.frontend
├── templates/                    # Jinja2 network config templates
│   ├── junos/, arista/, panos/, nokia-sros/, mikrotik/
│   └── html/                     # Legacy Flask template (superseded)
├── nornir-examples/              # Nornir task examples
├── inventory.py                  # Nornir + NetBox inventory plugin
├── deploy.py                     # Git-backed config deployment
├── scheduler.py                  # Legacy iCAL scheduler (superseded by API)
├── pyproject.toml                # Python project metadata + dependencies (uv)
├── uv.lock                       # Locked dependency tree
├── Dockerfile.api                # Backend Docker image
├── docker-compose.yml            # Production compose — Traefik + Let's Encrypt
├── docker-compose.dev.yml        # Full dev stack (Proxmox + NetBox + Postgres + Redis)
└── .env.example                  # Environment variable template
```

---

## Connecting a Real Proxmox Host

1. Set `PROXMOX_MOCK=false` (or remove the flag) in `.env`
2. Fill in `PROXMOX_HOST`, `PROXMOX_USER`, `PROXMOX_PASSWORD`
3. If using a self-signed certificate, set `PROXMOX_VERIFY_SSL=false`
4. Ensure the Proxmox user has `VM.Allocate`, `VM.PowerMgmt`, `Datastore.Allocate` privileges

```bash
# Proxmox — create a dedicated API user (recommended over root)
pveum role add DirettoreRole -privs "VM.Allocate VM.PowerMgmt VM.Console Datastore.AllocateSpace Pool.Allocate"
pveum user add direttore@pve --password <password>
pveum aclmod / -user direttore@pve -role DirettoreRole
```

---

## Populating NetBox Inventory via SNMP

The `snmp_to_netbox.sh` bash script walks a live network device via SNMP and pushes it into the NetBox model (interfaces, VRFs, VLANs, IPv4, IPv6, Serial Number).

```bash
# Set your NetBox URL and token in .env or your environment
# SNMP_COMMUNITY defaults to "public" but can be overridden

# Single device (IPv4, literal IPv6, or DNS hostname)
./snmp_to_netbox.sh -s "New York" -r "Router" -t "ASR1000" gateway.local "Core Router 1"
./snmp_to_netbox.sh fd68:1e02:dc1a:ffff::1 "gw.buragl.io"

# Bulk import from CSV
./snmp_to_netbox.sh -f devices.csv
```

#### Known platform quirks fixed in the script

| Platform | Issue | Fix applied |
|---|---|---|
| **Junos** | `sysDescr` contains forward slashes (e.g. `Junos 23.2R1/amd64`), breaking `sed 's/...//'` | All `sed` delimiters changed from `/` to `\|` |
| **Junos** | Doesn't respond to `IF-MIB::ifDescr` (MIB name form) | Script retries with numeric OID `1.3.6.1.2.1.2.2.1.2` if MIB-name walk returns 0 interfaces |
| **`/bin/sh` (dash)** | `grep -c` output with trailing newline causes `[: Illegal number:` in arithmetic comparisons | Counts are stripped with `tr -d '[:space:]'` and defaulted with `${var:-0}` |

---

## Physical Network Automation (NetBox + Nornir + Unimus)

In addition to virtual infrastructure, Direttore manages physical networking hardware (Juniper, Cisco, Aruba, MikroTik, FS, IP Infusion, Palo Alto) using a closed-loop automation architecture:

1. **NetBox**: The "Source of Truth" detailing intended state (VLANs, IPs, devices).
2. **Nornir**: The orchestration engine that fetches NetBox data, renders Jinja2 templates via NAPALM/Netmiko, and pushes config.
3. **Unimus**: The auditor that automatically syncs from NetBox, backs up the operational state, and detects configuration drift.

For the detailed, step-by-step implementation plan (including directory structures, Junos examples, and Netmiko platform mapping), please read the **[Network Automation Implementation Plan](docs/network_automation_plan.md)**.

```bash
# Example: Deploy provisioned VLANs to all Active Juniper switches
uv run python nornir_automation/generate_and_push.py
```

---

## Roadmap

| Feature | Status | Effort |
|---|---|---|
| JWT Authentication (local users) | ✅ Done | — |
| Hardware Management — Unimus backup + Git archive | ✅ Done | — |
| Hardware Management — golden-config provisioning | ✅ Done | — |
| Unimus device-address auto-match (4-strategy: IP→rDNS→name→scan) | ✅ Done | — |
| Manual Unimus device link store (DNS-free pairing) | ✅ Done | — |
| Unimus 2.8 backup endpoint auto-detection | ✅ Done | — |
| ContainerLab integration — local, SSH, REST backends | ✅ Done | — |
| ContainerLab topology Git backing + history | ✅ Done | — |
| ContainerLab in-browser node console (xterm.js + WebSocket) | ✅ Done | — |
| Real-time VM console (xterm.js + WebSocket) | Planned | 15 hrs |
| Snapshot management UI | Planned | 5 hrs |
| Prometheus metrics endpoint | Planned | 8 hrs |
| Two-way iCAL sync (CalDAV) | Planned | 8 hrs |
| YANG config validation | Planned | 5 hrs |
| SSH-based direct backup (NAPALM/Netmiko, no Unimus) | Planned | 8 hrs |
| Config diff viewer in Hardware History tab | Planned | 3 hrs |
| ContainerLab — clab-api-server auth in UI | Planned | 2 hrs |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-change`
3. Commit your changes: `git commit -m 'Add my change'`
4. Push and open a pull request

> **Note**: Set `PROXMOX_MOCK=true` during development so no Proxmox hardware is required.
