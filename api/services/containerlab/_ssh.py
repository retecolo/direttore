"""SshBackend — runs clab commands on a remote host via SSH.

Uses _SshPool to manage a pool of paramiko SSHClient connections, avoiding
per-call connect/disconnect overhead.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import shlex
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import paramiko

from api.services.containerlab._base import (
    ClabBackend,
    build_labs_from_containers,
    normalize_inspect,
)

log = logging.getLogger(__name__)


def _settings():
    from api.config import settings
    return settings


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

class _SshPool:
    def __init__(self, max_size: int = 4) -> None:
        self._max_size = max_size
        self._pool: list[paramiko.SSHClient] = []
        self._sem = asyncio.Semaphore(max_size)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[paramiko.SSHClient]:
        await self._sem.acquire()
        client = None
        healthy = True
        try:
            async with self._lock:
                client = self._pop_healthy()
            if client is None:
                client = await asyncio.to_thread(self._connect)
            yield client
        except Exception:
            healthy = False
            raise
        finally:
            if client is not None:
                if healthy and self._is_healthy(client):
                    async with self._lock:
                        self._pool.append(client)
                else:
                    client.close()
            self._sem.release()

    def _pop_healthy(self) -> paramiko.SSHClient | None:
        """Pop a healthy client from the pool list. Call only while holding self._lock."""
        while self._pool:
            client = self._pool.pop()
            if self._is_healthy(client):
                return client
            client.close()
        return None

    def _connect(self) -> paramiko.SSHClient:
        s = _settings()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, Any] = {
            "hostname": s.clab_ssh_host,
            "port": s.clab_ssh_port,
            "username": s.clab_ssh_user,
            "timeout": 10,
        }
        if s.clab_ssh_key_path:
            kwargs["key_filename"] = s.clab_ssh_key_path
        elif s.clab_ssh_password:
            kwargs["password"] = s.clab_ssh_password
        client.connect(**kwargs)
        return client

    def _is_healthy(self, client: paramiko.SSHClient) -> bool:
        t = client.get_transport()
        return t is not None and t.is_active()


# ---------------------------------------------------------------------------
# SSH backend
# ---------------------------------------------------------------------------

ALLOWED_ACTIONS = {"start", "stop", "restart"}


class SshBackend(ClabBackend):

    def __init__(self) -> None:
        s = _settings()
        self._pool = _SshPool(max_size=s.clab_ssh_pool_size)

    def _topo_path(self, filename: str) -> str:
        return str(Path(_settings().clab_topo_dir) / filename)

    def _run_sync(
        self, client: paramiko.SSHClient, args: list[str]
    ) -> tuple[int, str, str]:
        s = _settings()
        cmd = " ".join(shlex.quote(token) for token in [s.clab_binary] + args)
        log.debug("clab ssh: %s", cmd)
        _, stdout_f, stderr_f = client.exec_command(cmd)
        out = stdout_f.read().decode()
        err = stderr_f.read().decode()
        rc = stdout_f.channel.recv_exit_status()
        return rc, out, err

    async def _run(self, args: list[str]) -> tuple[int, str, str]:
        async with self._pool.acquire() as client:
            return await asyncio.to_thread(self._run_sync, client, args)

    async def get_status(self) -> dict[str, Any]:
        s = _settings()
        if not s.clab_ssh_host:
            return {"ok": False, "mode": "ssh", "error": "CLAB_SSH_HOST not configured"}
        try:
            rc, out, err = await self._run(["version"])
            return {
                "ok": rc == 0,
                "mode": "ssh",
                "host": s.clab_ssh_host,
                "version_raw": out.strip(),
            }
        except Exception as exc:
            return {"ok": False, "mode": "ssh", "host": s.clab_ssh_host, "error": str(exc)}

    async def list_labs(self) -> list[dict[str, Any]]:
        rc, out, err = await self._run(["inspect", "--all", "--format", "json"])
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
            return build_labs_from_containers(data)
        if isinstance(data, dict):
            containers = data.get("containers") or []
            if not containers:
                for k, v in data.items():
                    if isinstance(v, list):
                        containers.extend(v)
            return build_labs_from_containers(containers)
        return []

    async def inspect_lab(self, name: str) -> dict[str, Any]:
        rc, out, err = await self._run(["inspect", "--name", name, "--format", "json"])
        if rc != 0:
            raise RuntimeError(
                f"clab ssh inspect --name {name} failed: {err.strip() or out.strip()}"
            )
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return {"containers": [], "raw": out}
        return normalize_inspect(data)

    async def deploy(self, topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
        args = ["deploy", "--topo", self._topo_path(topo_file)]
        if reconfigure:
            args.append("--reconfigure")
        rc, out, err = await self._run(args)
        if rc != 0:
            raise RuntimeError(f"clab ssh deploy failed: {err.strip() or out.strip()}")
        return {"deployed": True, "output": out, "topo_file": topo_file}

    async def deploy_stream(self, topo_file: str, reconfigure: bool = True):
        s = _settings()
        cmd_parts = [s.clab_binary, "deploy", "--topo", self._topo_path(topo_file)]
        if reconfigure:
            cmd_parts.append("--reconfigure")
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        async with self._pool.acquire() as client:
            _, stdout_f, _ = await asyncio.to_thread(
                functools.partial(client.exec_command, cmd, get_pty=True)
            )

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

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        try:
            while True:
                item = await q.get()
                if isinstance(item, tuple):
                    tag, val = item
                    if tag == "exit":
                        if val != 0:
                            yield {"type": "error", "message": f"Exit code {val}"}
                        else:
                            yield {"type": "success", "message": "Deployed successfully"}
                    else:
                        yield {"type": "error", "message": val}
                    break
                else:
                    yield {"type": "log", "line": item}
        finally:
            try:
                stdout_f.channel.close()
            except Exception:
                pass
            await asyncio.to_thread(t.join, timeout=5)

    async def destroy(self, lab_name: str) -> dict[str, Any]:
        rc, out, err = await self._run(["destroy", "--name", lab_name])
        if rc != 0:
            raise RuntimeError(f"clab ssh destroy failed: {err.strip() or out.strip()}")
        return {"destroyed": True, "lab_name": lab_name}

    async def validate(self, topo_file: str) -> dict[str, Any]:
        rc, out, err = await self._run(
            ["deploy", "--topo", self._topo_path(topo_file), "--check"]
        )
        return {"valid": rc == 0, "output": (out + err).strip()}

    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Action {action!r} is not allowed. Must be one of {ALLOWED_ACTIONS}")
        container = f"clab-{lab_name}-{node_name}"

        def run(client: paramiko.SSHClient) -> tuple[int, str, str]:
            _, stdout_f, stderr_f = client.exec_command(
                f"{shlex.quote('docker')} {shlex.quote(action)} {shlex.quote(container)}"
            )
            out = stdout_f.read().decode()
            err = stderr_f.read().decode()
            rc = stdout_f.channel.recv_exit_status()
            return rc, out, err

        async with self._pool.acquire() as client:
            rc, out, err = await asyncio.to_thread(run, client)
        if rc != 0:
            raise RuntimeError(err.strip() or out.strip())
        return {"ok": True, "action": action, "container": container}

    async def node_console(self, ws: Any, lab_name: str, node_name: str) -> None:
        """WebSocket terminal bridged to a container shell via SSH channel.

        Opens a dedicated interactive shell channel from the pool connection's
        transport — the pool slot is released immediately after channel setup,
        so console sessions don't exhaust the pool.
        """
        container = f"clab-{lab_name}-{node_name}"

        def open_channel(client: paramiko.SSHClient) -> paramiko.Channel:
            transport = client.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.invoke_shell()
            channel.sendall(f"docker exec -it {container} /bin/sh\n")
            return channel

        async with self._pool.acquire() as client:
            channel: paramiko.Channel = await asyncio.to_thread(open_channel, client)
        # pool slot released; channel stays open independently on its transport

        async def to_ws() -> None:
            try:
                while True:
                    data = await asyncio.to_thread(channel.recv, 4096)
                    if not data:
                        return
                    await ws.send_bytes(data)
            except Exception:
                return

        async def from_ws() -> None:
            try:
                while True:
                    data = await ws.receive_bytes()
                    await asyncio.to_thread(channel.sendall, data)
            except Exception:
                return

        tasks = [asyncio.create_task(to_ws()), asyncio.create_task(from_ws())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        try:
            channel.close()
        except Exception:
            pass
