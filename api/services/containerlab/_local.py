"""LocalBackend — runs clab commands via asyncio subprocess on the local host."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pty
import shutil
from pathlib import Path
from typing import Any

from api.services.containerlab._base import (
    ClabBackend,
    build_labs_from_containers,
    normalize_inspect,
)

log = logging.getLogger(__name__)


def _settings():
    from api.config import settings
    return settings


def _topo_path(filename: str) -> Path:
    return Path(_settings().clab_topo_dir) / filename


class LocalBackend(ClabBackend):

    async def _run(self, args: list[str]) -> tuple[int, str, str]:
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

    async def get_status(self) -> dict[str, Any]:
        s = _settings()
        binary = shutil.which(s.clab_binary) or s.clab_binary
        exists = os.path.isfile(binary) and os.access(binary, os.X_OK)
        if not exists:
            return {"ok": False, "mode": "local", "error": f"clab binary not found: {binary}"}
        rc, out, err = await self._run(["version", "--format", "json"])
        if rc != 0:
            rc2, out2, _ = await self._run(["version"])
            return {"ok": rc2 == 0, "mode": "local", "binary": binary, "version_raw": out2.strip()}
        try:
            data = json.loads(out)
            return {"ok": True, "mode": "local", "binary": binary, "version": data}
        except json.JSONDecodeError:
            return {"ok": True, "mode": "local", "binary": binary, "version_raw": out.strip()}

    async def list_labs(self) -> list[dict[str, Any]]:
        rc, out, err = await self._run(["inspect", "--all", "--format", "json"])
        if rc != 0:
            err_lower = out.lower() + err.lower()
            if "no labs found" in err_lower or "no containers found" in err_lower:
                return []
            raise RuntimeError(
                f"clab inspect failed (code {rc}): stdout='{out.strip()}' stderr='{err.strip()}'"
            )
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return data
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
            raise RuntimeError(f"clab inspect --name {name} failed: {err.strip() or out.strip()}")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return {"containers": [], "raw": out}
        return normalize_inspect(data)

    async def deploy(self, topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
        args = ["deploy", "--topo", str(_topo_path(topo_file))]
        if reconfigure:
            args.append("--reconfigure")
        rc, out, err = await self._run(args)
        if rc != 0:
            raise RuntimeError(f"clab deploy failed: {err.strip() or out.strip()}")
        return {"deployed": True, "output": out, "topo_file": topo_file}

    async def deploy_stream(self, topo_file: str, reconfigure: bool = True):
        s = _settings()
        cmd = [s.clab_binary, "deploy", "--topo", str(_topo_path(topo_file))]
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
            yield {"type": "log", "line": line.decode(errors="replace")}
        rc = await proc.wait()
        if rc != 0:
            yield {"type": "error", "message": f"Deployment failed with exit code {rc}"}
        else:
            yield {"type": "success", "message": "Deployed successfully"}

    async def destroy(self, lab_name: str) -> dict[str, Any]:
        rc, out, err = await self._run(["destroy", "--name", lab_name])
        if rc != 0:
            raise RuntimeError(f"clab destroy failed: {err.strip() or out.strip()}")
        return {"destroyed": True, "lab_name": lab_name}

    async def validate(self, topo_file: str) -> dict[str, Any]:
        rc, out, err = await self._run(
            ["deploy", "--topo", str(_topo_path(topo_file)), "--check"]
        )
        return {"valid": rc == 0, "output": (out + err).strip()}

    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> dict[str, Any]:
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

    async def node_console(self, ws: Any, lab_name: str, node_name: str) -> None:
        container = f"clab-{lab_name}-{node_name}"
        log.debug("local_node_console: attaching to %s", container)
        master_fd, slave_fd = pty.openpty()
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "-it", container, "/bin/sh",
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
            )
        except Exception as exc:
            os.close(master_fd)
            os.close(slave_fd)
            log.error("local_node_console: failed to start docker exec: %s", exc)
            raise
        os.close(slave_fd)

        loop = asyncio.get_running_loop()

        async def to_ws():
            try:
                while True:
                    fut: asyncio.Future = loop.create_future()
                    loop.add_reader(master_fd, fut.set_result, None)
                    try:
                        await fut
                    finally:
                        loop.remove_reader(master_fd)
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        return
                    if not data:
                        return
                    await ws.send_bytes(data)
            except Exception:
                return

        async def from_ws():
            try:
                while True:
                    data = await ws.receive_bytes()
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        return
            except Exception:
                return

        tasks = [asyncio.create_task(to_ws()), asyncio.create_task(from_ws())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass
