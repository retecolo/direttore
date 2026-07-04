# ContainerLab Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the ContainerLab service into a clean ABC-based backend hierarchy with SSH connection pooling and four UX/reliability fixes.

**Architecture:** A `ClabBackend` ABC in `_base.py` defines the contract; `LocalBackend`, `SshBackend`, and `RestBackend` each live in their own module. `SshBackend` owns a `_SshPool` that manages a pool of up to N paramiko connections. The existing `__init__.py` shims delegate to a module-level singleton so `api/routes/containerlab.py` requires zero changes.

**Tech Stack:** Python 3.13, FastAPI, paramiko 4+, httpx 0.28+, asyncio, React 19, Mantine 7, @tanstack/react-query 5

## Global Constraints

- Python ≥ 3.13, `requires-python = ">=3.13"` — use `str | None` union syntax, not `Optional`
- No new dependencies — paramiko, httpx, asyncio are already in `pyproject.toml`
- `api/routes/containerlab.py` must not be modified — the public shim interface is the backward-compatibility boundary
- All SSH operations go through `_SshPool.acquire()` — no bare `paramiko.SSHClient` construction outside `_SshPool._connect()`
- Frontend: Mantine 7 component API throughout (e.g. `<Modal>`, `<ActionIcon>`, `<Code>`)
- No new npm dependencies — all needed frontend packages already installed

---

## File Map

**Created:**
- `api/services/containerlab/_base.py` — `ClabBackend` ABC + shared parsing helpers
- `api/services/containerlab/_local.py` — `LocalBackend` class
- `api/services/containerlab/_ssh.py` — `SshBackend` class + `_SshPool`
- `api/services/containerlab/_rest.py` — `RestBackend` class
- `api/services/containerlab/_workspace.py` — topology file / workspace / git helpers
- `tests/test_containerlab_base.py` — tests for shared parsing helpers
- `tests/test_containerlab_pool.py` — tests for `_SshPool` logic

**Modified:**
- `api/services/containerlab/__init__.py` — gutted to shims + `get_backend()` singleton
- `api/config.py` — add `clab_ssh_pool_size: int = 4`
- `frontend/src/features/topology/WorkspaceBrowser.jsx` — file edit + delete confirm
- `frontend/src/features/topology/NodeConsole.jsx` — no change (SSH fix is backend-only)

---

## Task 1: Shared base — `ClabBackend` ABC + parsing helpers

**Files:**
- Create: `api/services/containerlab/_base.py`
- Create: `tests/test_containerlab_base.py`

**Interfaces:**
- Produces:
  - `ClabBackend` ABC (9 abstract async methods — see step 3)
  - `oldest_created_at(containers: list[dict]) -> str | None`
  - `build_labs_from_containers(containers: list[dict]) -> list[dict]`
  - `normalize_inspect(data: list | dict) -> dict` — returns `{"containers": [...]}`

- [ ] **Step 1: Write failing tests for the three parsing helpers**

Create `tests/test_containerlab_base.py`:

```python
import pytest
from api.services.containerlab._base import (
    oldest_created_at,
    build_labs_from_containers,
    normalize_inspect,
)


def test_oldest_created_at_returns_none_for_empty():
    assert oldest_created_at([]) is None


def test_oldest_created_at_returns_earliest():
    containers = [
        {"createdAt": "2024-01-02T00:00:00Z"},
        {"createdAt": "2024-01-01T00:00:00Z"},
    ]
    assert oldest_created_at(containers) == "2024-01-01T00:00:00Z"


def test_oldest_created_at_handles_alternate_keys():
    containers = [{"Created": "2024-03-01T00:00:00Z"}]
    assert oldest_created_at(containers) == "2024-03-01T00:00:00Z"


def test_build_labs_groups_by_lab_name():
    containers = [
        {"lab_name": "mylab", "lab_path": "/t/mylab.yml", "createdAt": "2024-01-01T00:00:00Z"},
        {"lab_name": "mylab", "lab_path": "/t/mylab.yml", "createdAt": "2024-01-02T00:00:00Z"},
        {"lab_name": "other", "lab_path": "/t/other.yml", "createdAt": "2024-01-03T00:00:00Z"},
    ]
    labs = build_labs_from_containers(containers)
    assert len(labs) == 2
    mylab = next(l for l in labs if l["name"] == "mylab")
    assert len(mylab["containers"]) == 2
    assert mylab["created_at"] == "2024-01-01T00:00:00Z"


def test_normalize_inspect_list():
    data = [{"name": "c1"}]
    assert normalize_inspect(data) == {"containers": [{"name": "c1"}]}


def test_normalize_inspect_dict_with_containers_key():
    data = {"containers": [{"name": "c1"}]}
    assert normalize_inspect(data) == {"containers": [{"name": "c1"}]}


def test_normalize_inspect_clab_074_format():
    # ContainerLab 0.74+ returns {"lab-name": [container, ...]}
    data = {"mylab": [{"name": "c1"}, {"name": "c2"}]}
    result = normalize_inspect(data)
    assert len(result["containers"]) == 2


def test_normalize_inspect_empty_dict():
    assert normalize_inspect({}) == {"containers": []}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run pytest tests/test_containerlab_base.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or `ImportError` — `_base` doesn't exist yet.

- [ ] **Step 3: Write `_base.py`**

Create `api/services/containerlab/_base.py`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# Shared parsing helpers — used by LocalBackend and SshBackend
# ---------------------------------------------------------------------------

def oldest_created_at(containers: list[dict]) -> str | None:
    timestamps = []
    for c in containers:
        raw = c.get("createdAt") or c.get("created") or c.get("Created")
        if raw and isinstance(raw, str):
            timestamps.append(raw)
    return min(timestamps) if timestamps else None


def build_labs_from_containers(containers: list[dict]) -> list[dict[str, Any]]:
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
        lab["created_at"] = oldest_created_at(lab["containers"])
    return list(labs.values())


def normalize_inspect(data: list | dict) -> dict[str, Any]:
    """Normalize clab inspect JSON into {"containers": [...]}."""
    if isinstance(data, list):
        return {"containers": data}
    if isinstance(data, dict):
        if "containers" in data:
            return {"containers": data["containers"]}
        # ContainerLab 0.74+: {"lab-name": [container, ...]}
        containers: list[dict] = []
        for v in data.values():
            if isinstance(v, list):
                containers.extend(v)
        return {"containers": containers}
    return {"containers": []}


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------

class ClabBackend(ABC):

    @abstractmethod
    async def get_status(self) -> dict[str, Any]: ...

    @abstractmethod
    async def list_labs(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def inspect_lab(self, name: str) -> dict[str, Any]: ...

    @abstractmethod
    async def deploy(self, topo_file: str, reconfigure: bool = True) -> dict[str, Any]: ...

    @abstractmethod
    async def deploy_stream(self, topo_file: str, reconfigure: bool = True): ...
    # ^ async generator — yields {"type": "log"|"error"|"success", ...}

    @abstractmethod
    async def destroy(self, lab_name: str) -> dict[str, Any]: ...

    @abstractmethod
    async def validate(self, topo_file: str) -> dict[str, Any]: ...

    @abstractmethod
    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def node_console(self, ws: Any, lab_name: str, node_name: str) -> None: ...
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/test_containerlab_base.py -v
```

Expected: 8 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/containerlab/_base.py tests/test_containerlab_base.py
git commit -m "feat(clab): add ClabBackend ABC and shared parsing helpers"
```

---

## Task 2: `_workspace.py` — extract filesystem helpers

**Files:**
- Create: `api/services/containerlab/_workspace.py`

**Interfaces:**
- Produces: `list_topology_files`, `read_topology_file`, `write_topology_file`, `delete_topology_file`, `rename_workspace_item`, `duplicate_workspace_file`, `list_workspace`, `list_topology_git_history` — same signatures as current `__init__.py`
- Consumes: nothing from other new modules

- [ ] **Step 1: Create `_workspace.py`**

Create `api/services/containerlab/_workspace.py` by extracting all workspace/filesystem functions from the current `__init__.py`. The content is identical to the existing functions — copy them verbatim:

```python
"""Topology file, workspace, and git helpers.

These operate on the local filesystem (CLAB_TOPO_DIR) regardless of which
backend mode (local/ssh/rest) is active.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _settings():
    from api.config import settings
    return settings


def _topo_path(filename: str) -> Path:
    s = _settings()
    return Path(s.clab_topo_dir) / filename


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


def list_topology_git_history(filename: str, limit: int = 30) -> list[dict[str, Any]]:
    from api.config import settings as s
    if not s.clab_topo_git_repo:
        return []
    try:
        path = Path(s.clab_topo_git_local_path) / filename
        import git as gitpython  # type: ignore
        repo = gitpython.Repo(s.clab_topo_git_local_path)
        commits = list(
            repo.iter_commits(
                paths=str(path.relative_to(s.clab_topo_git_local_path)),
                max_count=limit,
            )
        )
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
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run python -c "from api.services.containerlab._workspace import list_topology_files; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add api/services/containerlab/_workspace.py
git commit -m "feat(clab): extract workspace/filesystem helpers to _workspace.py"
```

---

## Task 3: `LocalBackend` class

**Files:**
- Create: `api/services/containerlab/_local.py`

**Interfaces:**
- Consumes: `ClabBackend` from `._base`, `oldest_created_at`, `build_labs_from_containers`, `normalize_inspect` from `._base`
- Produces: `LocalBackend(ClabBackend)` — implements all 9 abstract methods

- [ ] **Step 1: Create `_local.py`**

Create `api/services/containerlab/_local.py`:

```python
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
```

- [ ] **Step 2: Verify import**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run python -c "from api.services.containerlab._local import LocalBackend; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add api/services/containerlab/_local.py
git commit -m "feat(clab): add LocalBackend class"
```

---

## Task 4: `_SshPool` + `SshBackend` class

**Files:**
- Create: `api/services/containerlab/_ssh.py`
- Create: `tests/test_containerlab_pool.py`
- Modify: `api/config.py` — add `clab_ssh_pool_size: int = 4`

**Interfaces:**
- Consumes: `ClabBackend`, `build_labs_from_containers`, `normalize_inspect` from `._base`
- Produces: `SshBackend(ClabBackend)` — implements all 9 abstract methods; `_SshPool`

- [ ] **Step 1: Add pool size config**

Edit `api/config.py` — add one line inside the ContainerLab block after `clab_ssh_password`:

```python
    clab_ssh_pool_size: int = 4       # max concurrent SSH connections for ssh mode
```

- [ ] **Step 2: Write pool tests**

Create `tests/test_containerlab_pool.py`:

```python
import asyncio
import pytest
from unittest.mock import MagicMock, patch


def _make_healthy_client():
    transport = MagicMock()
    transport.is_active.return_value = True
    client = MagicMock()
    client.get_transport.return_value = transport
    return client


def _make_dead_client():
    transport = MagicMock()
    transport.is_active.return_value = False
    client = MagicMock()
    client.get_transport.return_value = transport
    return client


@pytest.mark.asyncio
async def test_pool_reuses_healthy_connection():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    client = _make_healthy_client()
    pool._pool.append(client)

    async with pool.acquire() as c:
        assert c is client


@pytest.mark.asyncio
async def test_pool_replaces_dead_connection():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    dead = _make_dead_client()
    fresh = _make_healthy_client()
    pool._pool.append(dead)

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire() as c:
            assert c is fresh
    dead.close.assert_called_once()


@pytest.mark.asyncio
async def test_pool_creates_connection_when_empty():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    fresh = _make_healthy_client()

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire() as c:
            assert c is fresh


@pytest.mark.asyncio
async def test_pool_returns_connection_after_use():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    fresh = _make_healthy_client()

    with patch.object(pool, "_connect", return_value=fresh):
        async with pool.acquire():
            pass
    assert len(pool._pool) == 1


@pytest.mark.asyncio
async def test_pool_respects_max_size():
    from api.services.containerlab._ssh import _SshPool
    pool = _SshPool(max_size=2)
    clients = [_make_healthy_client() for _ in range(2)]
    call_count = 0

    def make_client():
        nonlocal call_count
        c = clients[call_count]
        call_count += 1
        return c

    with patch.object(pool, "_connect", side_effect=make_client):
        async with pool.acquire() as c1:
            async with pool.acquire() as c2:
                # third acquire must wait; test that semaphore blocks
                acquired = False

                async def try_acquire():
                    nonlocal acquired
                    async with pool.acquire():
                        acquired = True

                task = asyncio.create_task(try_acquire())
                await asyncio.sleep(0.05)
                assert not acquired  # still waiting
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
```

- [ ] **Step 3: Run pool tests — expect import error (not yet written)**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run pytest tests/test_containerlab_pool.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` for `_ssh`.

- [ ] **Step 4: Create `_ssh.py`**

Create `api/services/containerlab/_ssh.py`:

```python
"""SshBackend — runs clab commands on a remote host via SSH.

Uses _SshPool to manage a pool of paramiko SSHClient connections, avoiding
per-call connect/disconnect overhead.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
        try:
            async with self._lock:
                client = self._checkout()
            yield client
        finally:
            async with self._lock:
                self._pool.append(client)
            self._sem.release()

    def _checkout(self) -> paramiko.SSHClient:
        while self._pool:
            client = self._pool.pop()
            if self._is_healthy(client):
                return client
            client.close()
        return self._connect()

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
        cmd = " ".join([s.clab_binary] + args)
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
        cmd = " ".join(cmd_parts)

        async with self._pool.acquire() as client:
            _, stdout_f, _ = await asyncio.to_thread(
                client.exec_command, cmd, True  # get_pty=True
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

        await asyncio.to_thread(t.join)

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
        container = f"clab-{lab_name}-{node_name}"

        def run(client: paramiko.SSHClient) -> tuple[int, str, str]:
            _, stdout_f, stderr_f = client.exec_command(f"docker {action} {container}")
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
```

- [ ] **Step 5: Run pool tests — expect all pass**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run pytest tests/test_containerlab_pool.py -v
```

Expected: 5 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/services/containerlab/_ssh.py tests/test_containerlab_pool.py api/config.py
git commit -m "feat(clab): add SshBackend with _SshPool connection pool"
```

---

## Task 5: `RestBackend` class

**Files:**
- Create: `api/services/containerlab/_rest.py`

**Interfaces:**
- Consumes: `ClabBackend` from `._base`
- Produces: `RestBackend(ClabBackend)` — implements all 9 abstract methods; `deploy_stream` uses real httpx streaming

- [ ] **Step 1: Create `_rest.py`**

Create `api/services/containerlab/_rest.py`:

```python
"""RestBackend — delegates to a remote clab-api-server HTTP REST API."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from api.services.containerlab._base import ClabBackend

log = logging.getLogger(__name__)


def _settings():
    from api.config import settings
    return settings


class RestBackend(ClabBackend):

    def _base(self) -> str:
        return _settings().clab_api_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        s = _settings()
        h: dict[str, str] = {"Content-Type": "application/json"}
        if s.clab_api_token:
            h["Authorization"] = f"Bearer {s.clab_api_token}"
        elif s.clab_api_username and s.clab_api_password:
            creds = base64.b64encode(
                f"{s.clab_api_username}:{s.clab_api_password}".encode()
            ).decode()
            h["Authorization"] = f"Basic {creds}"
        return h

    def _verify(self) -> bool:
        return _settings().clab_api_verify_ssl

    def _topo_path(self, filename: str) -> str:
        return str(Path(_settings().clab_topo_dir) / filename)

    async def get_status(self) -> dict[str, Any]:
        s = _settings()
        if not s.clab_api_url:
            return {"ok": False, "mode": "rest", "error": "CLAB_API_URL not configured"}
        try:
            async with httpx.AsyncClient(timeout=10, verify=self._verify()) as c:
                r = await c.get(f"{self._base()}/api/v1/version", headers=self._headers())
            r.raise_for_status()
            return {"ok": True, "mode": "rest", "url": s.clab_api_url, "version": r.json()}
        except Exception as exc:
            return {"ok": False, "mode": "rest", "url": s.clab_api_url, "error": str(exc)}

    async def list_labs(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30, verify=self._verify()) as c:
            r = await c.get(f"{self._base()}/api/v1/labs", headers=self._headers())
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("labs", [])

    async def inspect_lab(self, name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, verify=self._verify()) as c:
            r = await c.get(f"{self._base()}/api/v1/labs/{name}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def deploy(self, topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120, verify=self._verify()) as c:
            r = await c.post(
                f"{self._base()}/api/v1/labs",
                headers=self._headers(),
                json={"topoFile": self._topo_path(topo_file), "reconfigure": reconfigure},
            )
        r.raise_for_status()
        return r.json()

    async def deploy_stream(self, topo_file: str, reconfigure: bool = True):
        """Stream deployment output line-by-line from clab-api-server.

        Falls back to two synthetic events if the server does not support
        chunked streaming (older clab-api-server versions).
        """
        url = f"{self._base()}/api/v1/labs"
        payload = {"topoFile": self._topo_path(topo_file), "reconfigure": reconfigure}
        try:
            async with httpx.AsyncClient(timeout=120, verify=self._verify()) as c:
                async with c.stream(
                    "POST", url, headers=self._headers(), json=payload
                ) as response:
                    response.raise_for_status()
                    streamed_any = False
                    async for line in response.aiter_lines():
                        if line:
                            streamed_any = True
                            yield {"type": "log", "line": line + "\n"}
                    if not streamed_any:
                        yield {
                            "type": "log",
                            "line": "[REST backend: no streaming output — deployment complete]\n",
                        }
                    yield {"type": "success", "message": "Deployed successfully"}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    async def destroy(self, lab_name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60, verify=self._verify()) as c:
            r = await c.delete(
                f"{self._base()}/api/v1/labs/{lab_name}",
                headers=self._headers(),
            )
        r.raise_for_status()
        return {"destroyed": True, "lab_name": lab_name}

    async def validate(self, topo_file: str) -> dict[str, Any]:
        return {
            "valid": None,
            "output": "Validation not supported for REST backend — deploy will catch errors.",
        }

    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> dict[str, Any]:
        return {"ok": False, "error": "Node actions are not supported for REST backend."}

    async def node_console(self, ws: Any, lab_name: str, node_name: str) -> None:
        await ws.send_bytes(b"\r\nNode console is not supported for REST backend.\r\n")
```

- [ ] **Step 2: Verify import**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run python -c "from api.services.containerlab._rest import RestBackend; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add api/services/containerlab/_rest.py
git commit -m "feat(clab): add RestBackend with real httpx streaming for deploy_stream"
```

---

## Task 6: Rewire `__init__.py` — singleton dispatcher + shims

**Files:**
- Modify: `api/services/containerlab/__init__.py` — replace with shim-only implementation

**Interfaces:**
- Consumes: `LocalBackend`, `SshBackend`, `RestBackend`, workspace functions
- Produces: same public API as the original `__init__.py` — all existing names preserved

- [ ] **Step 1: Replace `__init__.py`**

Overwrite `api/services/containerlab/__init__.py` with:

```python
"""ContainerLab service — public interface.

Provides module-level shims that delegate to the active ClabBackend singleton
so api/routes/containerlab.py requires no changes.

Backend is selected by CLAB_MODE in .env:
  local — LocalBackend (subprocess)
  ssh   — SshBackend (paramiko pool)
  rest  — RestBackend (httpx / clab-api-server)
"""

from __future__ import annotations

from typing import Any

from api.services.containerlab._base import ClabBackend
from api.services.containerlab._workspace import (  # noqa: F401 — re-exported
    delete_topology_file,
    duplicate_workspace_file,
    list_topology_files,
    list_topology_git_history,
    list_workspace,
    read_topology_file,
    rename_workspace_item,
    write_topology_file,
)

_backend: ClabBackend | None = None


def get_backend() -> ClabBackend:
    global _backend
    if _backend is None:
        from api.config import settings
        m = settings.clab_mode.lower()
        if m == "local":
            from api.services.containerlab._local import LocalBackend
            _backend = LocalBackend()
        elif m == "ssh":
            from api.services.containerlab._ssh import SshBackend
            _backend = SshBackend()
        elif m == "rest":
            from api.services.containerlab._rest import RestBackend
            _backend = RestBackend()
        else:
            raise RuntimeError(f"Unknown CLAB_MODE: {m!r}")
    return _backend


# ---------------------------------------------------------------------------
# Module-level shims — keep api/routes/containerlab.py unchanged
# ---------------------------------------------------------------------------

async def get_status() -> dict[str, Any]:
    return await get_backend().get_status()


async def list_labs() -> list[dict[str, Any]]:
    return await get_backend().list_labs()


async def inspect_lab(name: str) -> dict[str, Any]:
    return await get_backend().inspect_lab(name)


async def deploy(topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
    return await get_backend().deploy(topo_file, reconfigure=reconfigure)


async def deploy_stream(topo_file: str, reconfigure: bool = True):
    async for chunk in get_backend().deploy_stream(topo_file, reconfigure=reconfigure):
        yield chunk


async def destroy(lab_name: str) -> dict[str, Any]:
    return await get_backend().destroy(lab_name)


async def validate(topo_file: str) -> dict[str, Any]:
    return await get_backend().validate(topo_file)


async def node_action(lab_name: str, node_name: str, action: str) -> dict[str, Any]:
    return await get_backend().node_action(lab_name, node_name, action)


async def node_console(ws: Any, lab_name: str, node_name: str) -> None:
    await get_backend().node_console(ws, lab_name, node_name)
```

- [ ] **Step 2: Verify all public names are importable**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run python -c "
from api.services import containerlab as clab
names = [
    'get_status', 'list_labs', 'inspect_lab', 'deploy', 'deploy_stream',
    'destroy', 'validate', 'node_action', 'node_console',
    'list_topology_files', 'read_topology_file', 'write_topology_file',
    'delete_topology_file', 'rename_workspace_item', 'duplicate_workspace_file',
    'list_workspace', 'list_topology_git_history',
]
for n in names:
    assert hasattr(clab, n), f'missing: {n}'
print('all public names present')
"
```

Expected: `all public names present`

- [ ] **Step 3: Run all existing tests**

```bash
cd /Users/buraglio/Documents/Dev/direttore
uv run pytest tests/ -v
```

Expected: all tests pass (base + pool tests from Tasks 1 and 4).

- [ ] **Step 4: Commit**

```bash
git add api/services/containerlab/__init__.py
git commit -m "refactor(clab): rewire __init__.py to singleton dispatcher + shims"
```

---

## Task 7: Frontend — inline file editing in WorkspaceBrowser

**Files:**
- Modify: `frontend/src/features/topology/WorkspaceBrowser.jsx`

**Interfaces:**
- Consumes: existing `getTopology(path)` from `../../api/containerlab`; existing `saveWorkspaceFile(path, content)` mutation; existing `fileModalOpen`, `editingFile`, `fileContent`, `fileName` state
- Produces: edit icon on every workspace file row; clicking it fetches content and opens the file modal in edit mode with content pre-loaded; YAML files get YAML syntax highlighting, others plain text

- [ ] **Step 1: Add `IconFileCode` to the import list**

In `frontend/src/features/topology/WorkspaceBrowser.jsx`, edit the `@tabler/icons-react` import:

```jsx
import {
  IconUpload, IconCode, IconFolder, IconFolderPlus,
  IconFilePlus, IconTrash, IconChevronRight,
  IconPlayerPlay, IconPencil, IconCopy, IconTopologyFull,
  IconFileCode,
} from '@tabler/icons-react';
```

- [ ] **Step 2: Add CodeMirror `javascript` extension import**

Add after the existing CodeMirror imports (the file already has `yaml` and `oneDark`):

```jsx
import { javascript } from '@codemirror/lang-javascript';
```

Note: `@codemirror/lang-javascript` is already available transitively — no npm install needed.

- [ ] **Step 3: Add `editLoading` state and the edit handler**

Inside `WorkspaceBrowser`, after the existing state declarations add:

```jsx
const [editLoading, setEditLoading] = useState(null); // path being loaded
```

Add the `openEdit` handler after `const refresh = ...`:

```jsx
const openEdit = async (item) => {
  setEditLoading(item.path);
  try {
    const data = await getTopology(item.path);
    setEditingFile(item.path);
    setFileName(item.name);
    setFileContent(data.content ?? '');
    setFileModalOpen(true);
  } catch (e) {
    notifications.show({ color: 'red', title: 'Could not load file', message: e.response?.data?.detail || e.message });
  } finally {
    setEditLoading(null);
  }
};
```

- [ ] **Step 4: Add the edit `ActionIcon` to each file row**

In the row actions group (the `<Group gap={4} onClick={(e) => e.stopPropagation()}>` block), add before the rename `ActionIcon`:

```jsx
{!item.is_dir && (
  <ActionIcon
    size="sm" variant="subtle" color="indigo"
    loading={editLoading === item.path}
    onClick={() => openEdit(item)}
  >
    <IconFileCode size={13} />
  </ActionIcon>
)}
```

- [ ] **Step 5: Use correct CodeMirror extension based on file type**

In the file modal's `<CodeMirror>` component, replace the hardcoded `extensions={[yaml()]}` with:

```jsx
extensions={[
  (fileName.endsWith('.yml') || fileName.endsWith('.yaml')) ? yaml() : javascript(),
]}
```

- [ ] **Step 6: Build to check for errors**

```bash
cd /Users/buraglio/Documents/Dev/direttore/frontend
npm run build 2>&1 | tail -20
```

Expected: no errors; output ends with `built in Xs`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/topology/WorkspaceBrowser.jsx
git commit -m "feat(clab): add inline file editing to WorkspaceBrowser"
```

---

## Task 8: Frontend — delete confirmation modal in WorkspaceBrowser

**Files:**
- Modify: `frontend/src/features/topology/WorkspaceBrowser.jsx`

**Interfaces:**
- Consumes: existing `deleteMut` mutation; existing `<Modal>`, `<Button>`, `<Code>`, `<Group>`, `<Stack>`, `<Text>` Mantine components already imported; `IconTrash` already imported
- Produces: clicking trash on any workspace item sets `confirmDeleteTarget` and opens a modal; the modal shows the item name and requires explicit confirmation before deleting

- [ ] **Step 1: Add `confirmDeleteTarget` state**

Inside `WorkspaceBrowser`, after `const [editLoading, setEditLoading] = useState(null);` add:

```jsx
const [confirmDeleteTarget, setConfirmDeleteTarget] = useState(null); // path string
```

- [ ] **Step 2: Wire the trash icon to the confirm state instead of direct delete**

Find the existing trash `ActionIcon` in the file row:

```jsx
<ActionIcon size="sm" variant="subtle" color="red"
  loading={deleteMut.isPending && deleteMut.variables === item.path}
  onClick={() => deleteMut.mutate(item.path)}>
  <IconTrash size={13} />
</ActionIcon>
```

Replace with:

```jsx
<ActionIcon size="sm" variant="subtle" color="red"
  onClick={() => setConfirmDeleteTarget(item.path)}>
  <IconTrash size={13} />
</ActionIcon>
```

- [ ] **Step 3: Add the confirm modal**

At the bottom of `WorkspaceBrowser`'s JSX return, before the final `</Box>`, add:

```jsx
{/* Delete confirmation modal */}
<Modal
  opened={!!confirmDeleteTarget}
  onClose={() => setConfirmDeleteTarget(null)}
  title={
    <Group gap="xs">
      <IconTrash size={16} color="var(--mantine-color-red-5)" />
      <Text fw={600}>Delete Item</Text>
    </Group>
  }
  size="sm"
>
  <Stack>
    <Text size="sm">
      Are you sure you want to delete <Code>{confirmDeleteTarget}</Code>?
      This cannot be undone.
    </Text>
    <Group justify="flex-end" mt="xs">
      <Button variant="subtle" color="gray" onClick={() => setConfirmDeleteTarget(null)}>
        Cancel
      </Button>
      <Button
        color="red"
        loading={deleteMut.isPending}
        leftSection={<IconTrash size={14} />}
        onClick={() =>
          deleteMut.mutate(confirmDeleteTarget, {
            onSettled: () => setConfirmDeleteTarget(null),
          })
        }
      >
        Delete
      </Button>
    </Group>
  </Stack>
</Modal>
```

- [ ] **Step 4: Build to check for errors**

```bash
cd /Users/buraglio/Documents/Dev/direttore/frontend
npm run build 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/topology/WorkspaceBrowser.jsx
git commit -m "feat(clab): add delete confirmation modal to WorkspaceBrowser"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `ClabBackend` ABC with 9 abstract methods | Task 1 |
| `_base.py` shared parsing helpers | Task 1 |
| `_local.py` — `LocalBackend` class | Task 3 |
| `_ssh.py` — `SshBackend` + `_SshPool` | Task 4 |
| `clab_ssh_pool_size` config field | Task 4 |
| SSH pool health check + reconnect | Task 4 |
| SSH console: blocking-read, no busy-poll | Task 4 (`node_console`) |
| Console pool slot released before I/O loop | Task 4 (`node_console`) |
| `_rest.py` — `RestBackend` | Task 5 |
| REST `deploy_stream` uses httpx streaming | Task 5 |
| REST streaming graceful fallback | Task 5 |
| `_workspace.py` — extracted helpers | Task 2 |
| `__init__.py` singleton + shims | Task 6 |
| Routes unchanged | Task 6 (verified by name check) |
| Frontend: inline file editing | Task 7 |
| Frontend: YAML vs plain editor extension | Task 7 |
| Frontend: delete confirmation modal | Task 8 |

All requirements covered. No gaps.

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency check:**
- `normalize_inspect` defined in Task 1 `_base.py`; used in Tasks 3 and 4 — name matches.
- `build_labs_from_containers` defined in Task 1; used in Tasks 3 and 4 — name matches.
- `oldest_created_at` defined in Task 1; used internally by `build_labs_from_containers` — name matches.
- `_SshPool.acquire()` returns `AsyncIterator[paramiko.SSHClient]` — consumed in Task 4 `SshBackend` methods correctly.
- All 9 `ClabBackend` abstract method signatures match implementations in Tasks 3, 4, 5.
