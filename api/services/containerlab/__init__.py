"""Containerlab service — unified interface to a local or remote clab installation.

Three backends are supported, selected by CLAB_MODE in .env:
  local   — calls the `clab` binary directly via subprocess (user must be in clab_admins group)
  ssh     — connects via paramiko SSH to a remote host and runs `clab` commands there
  rest    — calls the clab-api-server HTTP REST API on a remote host

All three expose the same async interface:
  get_status()         → dict
  list_labs()          → list[dict]
  inspect_lab(name)    → dict
  deploy(topo_file)    → dict
  destroy(lab_name)    → dict
  validate(topo_file)  → dict
  node_action(lab, node, action) → dict
  node_console(ws, lab, node)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings():
    from api.config import settings  # lazy import avoids circular deps
    return settings


def _topo_path(filename: str) -> Path:
    s = _settings()
    return Path(s.clab_topo_dir) / filename


def _oldest_created_at(containers: list[dict]) -> str | None:
    """Return the earliest container creation timestamp as an ISO string, or None."""
    timestamps = []
    for c in containers:
        raw = c.get("createdAt") or c.get("created") or c.get("Created")
        if raw and isinstance(raw, str):
            timestamps.append(raw)
    return min(timestamps) if timestamps else None


# ---------------------------------------------------------------------------
# Local backend
# ---------------------------------------------------------------------------

async def _local_run(args: list[str]) -> tuple[int, str, str]:
    """Run a clab command locally via asyncio subprocess."""
    s = _settings()
    cmd = [s.clab_binary] + args
    log.debug("clab local: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def local_status() -> dict[str, Any]:
    s = _settings()
    binary = shutil.which(s.clab_binary) or s.clab_binary
    exists = os.path.isfile(binary) and os.access(binary, os.X_OK)
    if not exists:
        return {"ok": False, "mode": "local", "error": f"clab binary not found: {binary}"}
    rc, out, err = await _local_run(["version", "--format", "json"])
    if rc != 0:
        rc2, out2, _ = await _local_run(["version"])
        return {"ok": rc2 == 0, "mode": "local", "binary": binary, "version_raw": out2.strip()}
    try:
        data = json.loads(out)
        return {"ok": True, "mode": "local", "binary": binary, "version": data}
    except json.JSONDecodeError:
        return {"ok": True, "mode": "local", "binary": binary, "version_raw": out.strip()}


def _build_labs_from_containers(containers: list[dict]) -> list[dict[str, Any]]:
    """Group a flat container list into per-lab dicts."""
    labs: dict[str, dict] = {}
    for c in containers:
        name = c.get("lab_name") or c.get("labName") or "unknown"
        if name not in labs:
            labs[name] = {
                "name": name,
                "lab_path": c.get("lab_path") or c.get("labPath", ""),
                "containers": [],
            }
        labs[name]["containers"].append(c)
    for lab in labs.values():
        lab["created_at"] = _oldest_created_at(lab["containers"])
    return list(labs.values())


async def local_list_labs() -> list[dict[str, Any]]:
    rc, out, err = await _local_run(["inspect", "--all", "--format", "json"])
    if rc != 0:
        err_lower = out.lower() + err.lower()
        if "no labs found" in err_lower or "no containers found" in err_lower:
            return []
        raise RuntimeError(f"clab inspect failed (code {rc}): stdout='{out.strip()}' stderr='{err.strip()}'")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "containers" in data:
            containers = data["containers"]
        else:
            # ContainerLab 0.74+ returns {"lab-name": [container, container]}
            containers = []
            for k, v in data.items():
                if isinstance(v, list):
                    containers.extend(v)
        return _build_labs_from_containers(containers)
    return []


async def local_inspect_lab(name: str) -> dict[str, Any]:
    rc, out, err = await _local_run(["inspect", "--name", name, "--format", "json"])
    if rc != 0:
        raise RuntimeError(f"clab inspect --name {name} failed: {err.strip() or out.strip()}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"containers": [], "raw": out}

    if isinstance(data, list):
        return {"containers": data}
    if isinstance(data, dict):
        if "containers" in data:
            return {"containers": data["containers"]}
        containers = []
        for k, v in data.items():
            if isinstance(v, list):
                containers.extend(v)
        return {"containers": containers}
    return {"containers": []}


async def local_deploy(topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
    path = str(_topo_path(topo_file))
    args = ["deploy", "--topo", path]
    if reconfigure:
        args.append("--reconfigure")
    rc, out, err = await _local_run(args)
    if rc != 0:
        raise RuntimeError(f"clab deploy failed: {err.strip() or out.strip()}")
    return {"deployed": True, "output": out, "topo_file": topo_file}


async def local_deploy_stream(topo_file: str, reconfigure: bool = True):
    s = _settings()
    path = str(_topo_path(topo_file))
    cmd = [s.clab_binary, "deploy", "--topo", path]
    if reconfigure:
        cmd.append("--reconfigure")
    log.debug("clab local stream: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    if proc.stdout is None:
        yield {"type": "error", "message": "Failed to create subprocess pipe"}
        return

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        yield {"type": "log", "line": line.decode(errors='replace')}

    rc = await proc.wait()
    if rc != 0:
        yield {"type": "error", "message": f"Deployment failed with exit code {rc}"}
    else:
        yield {"type": "success", "message": "Deployed successfully"}


async def local_validate(topo_file: str) -> dict[str, Any]:
    path = str(_topo_path(topo_file))
    rc, out, err = await _local_run(["deploy", "--topo", path, "--check"])
    output = (out + err).strip()
    return {"valid": rc == 0, "output": output}


async def local_destroy(lab_name: str) -> dict[str, Any]:
    rc, out, err = await _local_run(["destroy", "--name", lab_name])
    if rc != 0:
        raise RuntimeError(f"clab destroy failed: {err.strip() or out.strip()}")
    return {"destroyed": True, "lab_name": lab_name}


async def local_node_action(lab_name: str, node_name: str, action: str) -> dict[str, Any]:
    container = f"clab-{lab_name}-{node_name}"
    proc = await asyncio.create_subprocess_exec(
        "docker", action, container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip() or stdout.decode().strip())
    return {"ok": True, "action": action, "container": container}


async def local_node_console(ws: Any, lab_name: str, node_name: str) -> None:
    container = f"clab-{lab_name}-{node_name}"
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container, "/bin/sh",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def to_ws():
        while True:
            data = await proc.stdout.read(1024)
            if not data:
                return
            try:
                await ws.send_bytes(data)
            except Exception:
                return

    async def from_ws():
        while True:
            try:
                data = await ws.receive_bytes()
            except Exception:
                return
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.write(data)
                try:
                    await proc.stdin.drain()
                except Exception:
                    return

    tasks = [asyncio.create_task(to_ws()), asyncio.create_task(from_ws())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    try:
        proc.terminate()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSH backend
# ---------------------------------------------------------------------------

def _ssh_client():
    """Return a connected paramiko SSHClient."""
    import paramiko
    s = _settings()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict[str, Any] = {
        "hostname": s.clab_ssh_host,
        "port": s.clab_ssh_port,
        "username": s.clab_ssh_user,
        "timeout": 10,
    }
    if s.clab_ssh_key_path:
        connect_kwargs["key_filename"] = s.clab_ssh_key_path
    elif s.clab_ssh_password:
        connect_kwargs["password"] = s.clab_ssh_password
    client.connect(**connect_kwargs)
    return client


def _ssh_run_sync(args: list[str]) -> tuple[int, str, str]:
    s = _settings()
    cmd = " ".join([s.clab_binary] + args)
    log.debug("clab ssh: %s", cmd)
    client = _ssh_client()
    try:
        _, stdout_f, stderr_f = client.exec_command(cmd)
        out = stdout_f.read().decode()
        err = stderr_f.read().decode()
        rc = stdout_f.channel.recv_exit_status()
        return rc, out, err
    finally:
        client.close()


async def _ssh_run(args: list[str]) -> tuple[int, str, str]:
    return await asyncio.to_thread(_ssh_run_sync, args)


async def ssh_status() -> dict[str, Any]:
    s = _settings()
    if not s.clab_ssh_host:
        return {"ok": False, "mode": "ssh", "error": "CLAB_SSH_HOST not configured"}
    try:
        rc, out, err = await _ssh_run(["version"])
        return {"ok": rc == 0, "mode": "ssh", "host": s.clab_ssh_host, "version_raw": out.strip()}
    except Exception as exc:
        return {"ok": False, "mode": "ssh", "host": s.clab_ssh_host, "error": str(exc)}


async def ssh_list_labs() -> list[dict[str, Any]]:
    rc, out, err = await _ssh_run(["inspect", "--all", "--format", "json"])
    if rc != 0:
        err_lower = out.lower() + err.lower()
        if "no labs found" in err_lower or "no containers found" in err_lower:
            return []
        raise RuntimeError(f"clab ssh inspect failed: {err.strip() or out.strip()}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "containers" in data:
            containers = data["containers"]
        else:
            containers = []
            for k, v in data.items():
                if isinstance(v, list):
                    containers.extend(v)
        return _build_labs_from_containers(containers)
    return []


async def ssh_inspect_lab(name: str) -> dict[str, Any]:
    rc, out, err = await _ssh_run(["inspect", "--name", name, "--format", "json"])
    if rc != 0:
        raise RuntimeError(f"clab ssh inspect --name {name} failed: {err.strip() or out.strip()}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"containers": [], "raw": out}

    if isinstance(data, list):
        return {"containers": data}
    if isinstance(data, dict):
        if "containers" in data:
            return {"containers": data["containers"]}
        containers = []
        for k, v in data.items():
            if isinstance(v, list):
                containers.extend(v)
        return {"containers": containers}
    return {"containers": []}


async def ssh_deploy(topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
    s = _settings()
    path = str(Path(s.clab_topo_dir) / topo_file)
    args = ["deploy", "--topo", path]
    if reconfigure:
        args.append("--reconfigure")
    rc, out, err = await _ssh_run(args)
    if rc != 0:
        raise RuntimeError(f"clab ssh deploy failed: {err.strip() or out.strip()}")
    return {"deployed": True, "output": out, "topo_file": topo_file}


async def ssh_deploy_stream(topo_file: str, reconfigure: bool = True):
    s = _settings()
    path = str(Path(s.clab_topo_dir) / topo_file)
    cmd_parts = [s.clab_binary, "deploy", "--topo", path]
    if reconfigure:
        cmd_parts.append("--reconfigure")
    cmd = " ".join(cmd_parts)

    client = await asyncio.to_thread(_ssh_client)
    try:
        _, stdout_f, stderr_f = client.exec_command(cmd, get_pty=True)
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def reader():
            try:
                for line in iter(stdout_f.readline, ""):
                    loop.call_soon_threadsafe(q.put_nowait, line)
                rc = stdout_f.channel.recv_exit_status()
                loop.call_soon_threadsafe(q.put_nowait, ("exit", rc))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))

        t = threading.Thread(target=reader)
        t.start()

        while True:
            item = await q.get()
            if isinstance(item, tuple):
                if item[0] == "exit":
                    rc = item[1]
                    if rc != 0:
                        yield {"type": "error", "message": f"Exit code {rc}"}
                    else:
                        yield {"type": "success", "message": "Deployed successfully"}
                    break
                elif item[0] == "error":
                    yield {"type": "error", "message": item[1]}
                    break
            else:
                yield {"type": "log", "line": item}

        await asyncio.to_thread(t.join)
    finally:
        client.close()


async def ssh_validate(topo_file: str) -> dict[str, Any]:
    s = _settings()
    path = str(Path(s.clab_topo_dir) / topo_file)
    rc, out, err = await _ssh_run(["deploy", "--topo", path, "--check"])
    output = (out + err).strip()
    return {"valid": rc == 0, "output": output}


async def ssh_destroy(lab_name: str) -> dict[str, Any]:
    rc, out, err = await _ssh_run(["destroy", "--name", lab_name])
    if rc != 0:
        raise RuntimeError(f"clab ssh destroy failed: {err.strip() or out.strip()}")
    return {"destroyed": True, "lab_name": lab_name}


async def ssh_node_action(lab_name: str, node_name: str, action: str) -> dict[str, Any]:
    container = f"clab-{lab_name}-{node_name}"

    def run():
        client = _ssh_client()
        try:
            _, stdout_f, stderr_f = client.exec_command(f"docker {action} {container}")
            out = stdout_f.read().decode()
            err = stderr_f.read().decode()
            rc = stdout_f.channel.recv_exit_status()
            return rc, out, err
        finally:
            client.close()

    rc, out, err = await asyncio.to_thread(run)
    if rc != 0:
        raise RuntimeError(err.strip() or out.strip())
    return {"ok": True, "action": action, "container": container}


async def ssh_node_console(ws: Any, lab_name: str, node_name: str) -> None:
    container = f"clab-{lab_name}-{node_name}"

    client = await asyncio.to_thread(_ssh_client)
    channel = await asyncio.to_thread(client.invoke_shell)
    await asyncio.to_thread(channel.send, f"docker exec -it {container} /bin/sh\n")

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def reader():
        try:
            while not channel.closed:
                if channel.recv_ready():
                    data = channel.recv(1024)
                    loop.call_soon_threadsafe(q.put_nowait, data)
                elif channel.exit_status_ready():
                    break
        except Exception:
            pass
        loop.call_soon_threadsafe(q.put_nowait, None)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    async def to_ws():
        while True:
            data = await q.get()
            if data is None:
                return
            try:
                await ws.send_bytes(data)
            except Exception:
                return

    async def from_ws():
        while True:
            try:
                data = await ws.receive_bytes()
                channel.send(data)
            except Exception:
                return

    tasks = [asyncio.create_task(to_ws()), asyncio.create_task(from_ws())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    client.close()


# ---------------------------------------------------------------------------
# REST backend (clab-api-server)
# ---------------------------------------------------------------------------

def _rest_base() -> str:
    s = _settings()
    return s.clab_api_url.rstrip("/")


def _rest_headers() -> dict[str, str]:
    s = _settings()
    h: dict[str, str] = {"Content-Type": "application/json"}
    if s.clab_api_token:
        h["Authorization"] = f"Bearer {s.clab_api_token}"
    elif s.clab_api_username and s.clab_api_password:
        import base64
        creds = base64.b64encode(f"{s.clab_api_username}:{s.clab_api_password}".encode()).decode()
        h["Authorization"] = f"Basic {creds}"
    return h


async def rest_status() -> dict[str, Any]:
    s = _settings()
    if not s.clab_api_url:
        return {"ok": False, "mode": "rest", "error": "CLAB_API_URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=10, verify=s.clab_api_verify_ssl) as c:
            r = await c.get(f"{_rest_base()}/api/v1/version", headers=_rest_headers())
        r.raise_for_status()
        return {"ok": True, "mode": "rest", "url": s.clab_api_url, "version": r.json()}
    except Exception as exc:
        return {"ok": False, "mode": "rest", "url": s.clab_api_url, "error": str(exc)}


async def rest_list_labs() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30, verify=_settings().clab_api_verify_ssl) as c:
        r = await c.get(f"{_rest_base()}/api/v1/labs", headers=_rest_headers())
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("labs", [])


async def rest_inspect_lab(name: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30, verify=_settings().clab_api_verify_ssl) as c:
        r = await c.get(f"{_rest_base()}/api/v1/labs/{name}", headers=_rest_headers())
    r.raise_for_status()
    return r.json()


async def rest_deploy(topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
    s = _settings()
    topo_path = str(Path(s.clab_topo_dir) / topo_file)
    async with httpx.AsyncClient(timeout=120, verify=s.clab_api_verify_ssl) as c:
        r = await c.post(
            f"{_rest_base()}/api/v1/labs",
            headers=_rest_headers(),
            json={"topoFile": topo_path, "reconfigure": reconfigure},
        )
    r.raise_for_status()
    return r.json()


async def rest_deploy_stream(topo_file: str, reconfigure: bool = True):
    try:
        res = await rest_deploy(topo_file, reconfigure=reconfigure)
        yield {"type": "log", "line": res.get("output", "Successfully communicated with REST API.\n")}
        yield {"type": "success", "message": "Deployed successfully"}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}


async def rest_validate(topo_file: str) -> dict[str, Any]:
    return {"valid": None, "output": "Validation not supported for REST backend — deploy will catch errors."}


async def rest_destroy(lab_name: str) -> dict[str, Any]:
    s = _settings()
    async with httpx.AsyncClient(timeout=60, verify=s.clab_api_verify_ssl) as c:
        r = await c.delete(
            f"{_rest_base()}/api/v1/labs/{lab_name}",
            headers=_rest_headers(),
        )
    r.raise_for_status()
    return {"destroyed": True, "lab_name": lab_name}


async def rest_node_action(lab_name: str, node_name: str, action: str) -> dict[str, Any]:
    return {"ok": False, "error": "Node actions are not supported for REST backend."}


async def rest_node_console(ws: Any, lab_name: str, node_name: str) -> None:
    await ws.send_bytes(b"\r\nNode console is not supported for REST backend.\r\n")


# ---------------------------------------------------------------------------
# Topology file helpers (filesystem — same for all modes)
# ---------------------------------------------------------------------------

def list_topology_files() -> list[str]:
    s = _settings()
    topo_dir = Path(s.clab_topo_dir)
    if not topo_dir.is_dir():
        return []
    return sorted(
        f.name
        for f in topo_dir.iterdir()
        if f.is_file() and f.suffix in (".yml", ".yaml")
    )


def read_topology_file(filename: str) -> str | None:
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    path = (topo_dir / filename).resolve()
    if topo_dir not in path.parents or not path.is_file():
        return None
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None


def write_topology_file(filename: str, content: str) -> None:
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    path = (topo_dir / filename).resolve()
    if topo_dir not in path.parents:
        raise ValueError("Invalid path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def delete_topology_file(filename: str) -> bool:
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    path = (topo_dir / filename).resolve()
    if topo_dir not in path.parents or not path.exists():
        return False
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    return True


def rename_workspace_item(old_path: str, new_name: str) -> str:
    """Rename a file or directory within the workspace. Returns new relative path."""
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    old = (topo_dir / old_path).resolve()
    if topo_dir not in old.parents or not old.exists():
        raise ValueError("Source not found")
    if "/" in new_name or ".." in new_name:
        raise ValueError("new_name must be a plain filename")
    new = old.parent / new_name
    if new.exists():
        raise ValueError(f"'{new_name}' already exists")
    old.rename(new)
    return str(new.relative_to(topo_dir))


def duplicate_workspace_file(path: str, new_name: str) -> str:
    """Copy a file to a new name in the same directory. Returns new relative path."""
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    src = (topo_dir / path).resolve()
    if topo_dir not in src.parents or not src.is_file():
        raise ValueError("Source not found or is a directory")
    if "/" in new_name or ".." in new_name:
        raise ValueError("new_name must be a plain filename")
    dst = src.parent / new_name
    if dst.exists():
        raise ValueError(f"'{new_name}' already exists")
    shutil.copy2(str(src), str(dst))
    return str(dst.relative_to(topo_dir))


def list_workspace(subpath: str = "") -> list[dict[str, Any]]:
    """Return a list of files and directories in the workspace."""
    s = _settings()
    topo_dir = Path(s.clab_topo_dir).resolve()
    target = (topo_dir / subpath).resolve()

    if topo_dir not in target.parents and target != topo_dir:
        return []
    if not target.is_dir():
        return []

    items = []
    for f in target.iterdir():
        if f.name.startswith(".git"):
            continue
        rel = f.relative_to(topo_dir)
        items.append({
            "name": f.name,
            "path": str(rel),
            "is_dir": f.is_dir(),
            "size": f.stat().st_size if f.is_file() else 0,
        })
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"]))


# ---------------------------------------------------------------------------
# Topology Git helpers
# ---------------------------------------------------------------------------

def list_topology_git_history(filename: str, limit: int = 30) -> list[dict[str, Any]]:
    """Return git log for a topology file if CLAB_TOPO_GIT_REPO is configured."""
    from api.config import settings as s
    if not s.clab_topo_git_repo:
        return []
    try:
        path = Path(s.clab_topo_git_local_path) / filename
        import git as gitpython  # type: ignore
        repo = gitpython.Repo(s.clab_topo_git_local_path)
        commits = list(repo.iter_commits(paths=str(path.relative_to(s.clab_topo_git_local_path)), max_count=limit))
        return [
            {
                "sha": str(c.hexsha[:8]),
                "message": c.message.strip(),
                "author": str(c.author),
                "date": c.committed_datetime.isoformat(),
            }
            for c in commits
        ]
    except Exception as exc:
        log.warning("topology git log failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Unified dispatcher — routes calls to the correct backend
# ---------------------------------------------------------------------------

def _mode() -> str:
    return _settings().clab_mode.lower()


async def get_status() -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_status()
    if m == "ssh":
        return await ssh_status()
    if m == "rest":
        return await rest_status()
    return {"ok": False, "error": f"Unknown CLAB_MODE: {m}"}


async def list_labs() -> list[dict[str, Any]]:
    m = _mode()
    if m == "local":
        return await local_list_labs()
    if m == "ssh":
        return await ssh_list_labs()
    if m == "rest":
        return await rest_list_labs()
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def inspect_lab(name: str) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_inspect_lab(name)
    if m == "ssh":
        return await ssh_inspect_lab(name)
    if m == "rest":
        return await rest_inspect_lab(name)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def deploy(topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_deploy(topo_file, reconfigure=reconfigure)
    if m == "ssh":
        return await ssh_deploy(topo_file, reconfigure=reconfigure)
    if m == "rest":
        return await rest_deploy(topo_file, reconfigure=reconfigure)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def deploy_stream(topo_file: str, reconfigure: bool = True):
    m = _mode()
    if m == "local":
        async for chunk in local_deploy_stream(topo_file, reconfigure=reconfigure):
            yield chunk
    elif m == "ssh":
        async for chunk in ssh_deploy_stream(topo_file, reconfigure=reconfigure):
            yield chunk
    elif m == "rest":
        async for chunk in rest_deploy_stream(topo_file, reconfigure=reconfigure):
            yield chunk
    else:
        yield {"type": "error", "message": f"Unknown CLAB_MODE: {m}"}


async def destroy(lab_name: str) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_destroy(lab_name)
    if m == "ssh":
        return await ssh_destroy(lab_name)
    if m == "rest":
        return await rest_destroy(lab_name)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def validate(topo_file: str) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_validate(topo_file)
    if m == "ssh":
        return await ssh_validate(topo_file)
    if m == "rest":
        return await rest_validate(topo_file)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def node_action(lab_name: str, node_name: str, action: str) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_node_action(lab_name, node_name, action)
    if m == "ssh":
        return await ssh_node_action(lab_name, node_name, action)
    if m == "rest":
        return await rest_node_action(lab_name, node_name, action)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def node_console(ws: Any, lab_name: str, node_name: str) -> None:
    m = _mode()
    if m == "local":
        await local_node_console(ws, lab_name, node_name)
    elif m == "ssh":
        await ssh_node_console(ws, lab_name, node_name)
    elif m == "rest":
        await rest_node_console(ws, lab_name, node_name)
    else:
        await ws.send_bytes(f"Unknown CLAB_MODE: {m}".encode())
