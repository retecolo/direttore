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
  list_topologies()    → list[str]
  read_topology(fname) → str
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
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
        # version flag may not support --format json on older builds
        rc2, out2, _ = await _local_run(["version"])
        return {"ok": rc2 == 0, "mode": "local", "binary": binary, "version_raw": out2.strip()}
    try:
        data = json.loads(out)
        return {"ok": True, "mode": "local", "binary": binary, "version": data}
    except json.JSONDecodeError:
        return {"ok": True, "mode": "local", "binary": binary, "version_raw": out.strip()}


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
    # Output shape varies by clab version — normalise to list
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
                    
        # Group containers by lab name
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
        return list(labs.values())
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


async def local_deploy(topo_file: str) -> dict[str, Any]:
    path = str(_topo_path(topo_file))
    rc, out, err = await _local_run(["deploy", "--topo", path, "--reconfigure"])
    if rc != 0:
        raise RuntimeError(f"clab deploy failed: {err.strip() or out.strip()}")
    return {"deployed": True, "output": out, "topo_file": topo_file}


async def local_deploy_stream(topo_file: str):
    s = _settings()
    path = str(_topo_path(topo_file))
    
    cmd = [s.clab_binary, "deploy", "--topo", path, "--reconfigure"]
    log.debug("clab local stream: %s", " ".join(cmd))
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
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


async def local_destroy(lab_name: str) -> dict[str, Any]:
    rc, out, err = await _local_run(["destroy", "--name", lab_name])
    if rc != 0:
        raise RuntimeError(f"clab destroy failed: {err.strip() or out.strip()}")
    return {"destroyed": True, "lab_name": lab_name}


# ---------------------------------------------------------------------------
# SSH backend
# ---------------------------------------------------------------------------

def _ssh_client():
    """Return a connected paramiko SSHClient."""
    import paramiko  # already a project dependency
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
                    
        labs: dict[str, dict] = {}
        for c in containers:
            name = c.get("lab_name") or c.get("labName") or "unknown"
            if name not in labs:
                labs[name] = {"name": name, "lab_path": c.get("lab_path", ""), "containers": []}
            labs[name]["containers"].append(c)
        return list(labs.values())
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


async def ssh_deploy(topo_file: str) -> dict[str, Any]:
    s = _settings()
    path = str(Path(s.clab_topo_dir) / topo_file)
    rc, out, err = await _ssh_run(["deploy", "--topo", path, "--reconfigure"])
    if rc != 0:
        raise RuntimeError(f"clab ssh deploy failed: {err.strip() or out.strip()}")
    return {"deployed": True, "output": out, "topo_file": topo_file}


async def ssh_deploy_stream(topo_file: str):
    s = _settings()
    path = str(Path(s.clab_topo_dir) / topo_file)
    cmd = " ".join([s.clab_binary, "deploy", "--topo", path, "--reconfigure"])
    
    client = await asyncio.to_thread(_ssh_client)
    try:
        _, stdout_f, stderr_f = client.exec_command(cmd, get_pty=True)
        q = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        def reader():
            try:
                for line in iter(stdout_f.readline, ""):
                    loop.call_soon_threadsafe(q.put_nowait, line)
                rc = stdout_f.channel.recv_exit_status()
                loop.call_soon_threadsafe(q.put_nowait, ("exit", rc))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))

        import threading
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


async def ssh_destroy(lab_name: str) -> dict[str, Any]:
    rc, out, err = await _ssh_run(["destroy", "--name", lab_name])
    if rc != 0:
        raise RuntimeError(f"clab ssh destroy failed: {err.strip() or out.strip()}")
    return {"destroyed": True, "lab_name": lab_name}


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


async def rest_deploy(topo_file: str) -> dict[str, Any]:
    s = _settings()
    topo_path = str(Path(s.clab_topo_dir) / topo_file)
    async with httpx.AsyncClient(timeout=120, verify=s.clab_api_verify_ssl) as c:
        r = await c.post(
            f"{_rest_base()}/api/v1/labs",
            headers=_rest_headers(),
            json={"topoFile": topo_path, "reconfigure": True},
        )
    r.raise_for_status()
    return r.json()


async def rest_deploy_stream(topo_file: str):
    try:
        res = await rest_deploy(topo_file)
        yield {"type": "log", "line": res.get("output", "Successfully communicated with REST API.\n")}
        yield {"type": "success", "message": "Deployed successfully"}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}


async def rest_destroy(lab_name: str) -> dict[str, Any]:
    s = _settings()
    async with httpx.AsyncClient(timeout=60, verify=s.clab_api_verify_ssl) as c:
        r = await c.delete(
            f"{_rest_base()}/api/v1/labs/{lab_name}",
            headers=_rest_headers(),
        )
    r.raise_for_status()
    return {"destroyed": True, "lab_name": lab_name}


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
    path = Path(s.clab_topo_dir) / filename
    if not path.is_file():
        return None
    return path.read_text()


def write_topology_file(filename: str, content: str) -> None:
    s = _settings()
    topo_dir = Path(s.clab_topo_dir)
    topo_dir.mkdir(parents=True, exist_ok=True)
    (topo_dir / filename).write_text(content)


# ---------------------------------------------------------------------------
# Topology Git helpers
# ---------------------------------------------------------------------------

def list_topology_git_history(filename: str, limit: int = 30) -> list[dict[str, Any]]:
    """Return git log for a topology file if CLAB_TOPO_GIT_REPO is configured."""
    from api.config import settings as s
    if not s.clab_topo_git_repo:
        return []
    from api.services import git_config as git
    # Reuse git_config service pointed at topo dir — just read the log
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


async def deploy(topo_file: str) -> dict[str, Any]:
    m = _mode()
    if m == "local":
        return await local_deploy(topo_file)
    if m == "ssh":
        return await ssh_deploy(topo_file)
    if m == "rest":
        return await rest_deploy(topo_file)
    raise RuntimeError(f"Unknown CLAB_MODE: {m}")


async def deploy_stream(topo_file: str):
    m = _mode()
    if m == "local":
        async for chunk in local_deploy_stream(topo_file):
            yield chunk
    elif m == "ssh":
        async for chunk in ssh_deploy_stream(topo_file):
            yield chunk
    elif m == "rest":
        async for chunk in rest_deploy_stream(topo_file):
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
