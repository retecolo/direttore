# ContainerLab Optimization Design

**Date:** 2026-07-03  
**Branch:** ndb-branch  
**Scope:** Code quality, reliability, and UX improvements for the ContainerLab subsystem. Performance optimization (caching, poll reduction) is deferred to a follow-up pass after this work lands.

---

## Goals

1. Eliminate the ~890-line monolith in `api/services/containerlab/__init__.py` by introducing a proper backend abstraction
2. Replace per-call SSH connection creation with a small async-aware connection pool
3. Fix four concrete UX/reliability bugs: missing file edit, missing delete confirmation, SSH console busy-poll, and fake REST streaming

---

## Section 1: Backend Architecture

### File Structure

Split `api/services/containerlab/__init__.py` into five focused modules:

```text
api/services/containerlab/
    __init__.py       — public interface: get_backend() + module-level shims (routes unchanged)
    _base.py          — ClabBackend ABC + shared parsing helpers
    _local.py         — LocalBackend class
    _ssh.py           — SshBackend class + _SshPool
    _rest.py          — RestBackend class
    _workspace.py     — topology file / workspace / git helpers (no backend dependency)
```

### ClabBackend ABC (`_base.py`)

```python
class ClabBackend(ABC):
    @abstractmethod
    async def get_status(self) -> dict: ...
    @abstractmethod
    async def list_labs(self) -> list[dict]: ...
    @abstractmethod
    async def inspect_lab(self, name: str) -> dict: ...
    @abstractmethod
    async def deploy(self, topo_file: str, reconfigure: bool) -> dict: ...
    @abstractmethod
    async def deploy_stream(self, topo_file: str, reconfigure: bool): ...  # async generator
    @abstractmethod
    async def destroy(self, lab_name: str) -> dict: ...
    @abstractmethod
    async def validate(self, topo_file: str) -> dict: ...
    @abstractmethod
    async def node_action(self, lab_name: str, node_name: str, action: str) -> dict: ...
    @abstractmethod
    async def node_console(self, ws, lab_name: str, node_name: str) -> None: ...
```

### Shared Parsing Helpers (`_base.py`)

These are currently duplicated across local and SSH backends:

- `_oldest_created_at(containers)` — returns earliest container creation timestamp
- `_build_labs_from_containers(containers)` — groups flat container list into per-lab dicts
- `_normalize_inspect(data)` — JSON normalization logic for `inspect_lab` (handles list, `{"containers": [...]}`, and ContainerLab 0.74+ `{"lab-name": [...]}` formats)

All three backends import from `_base.py`.

### Backend Singleton (`__init__.py`)

```python
_backend: ClabBackend | None = None

def get_backend() -> ClabBackend:
    global _backend
    if _backend is None:
        m = settings.clab_mode.lower()
        if m == "local":   _backend = LocalBackend()
        elif m == "ssh":   _backend = SshBackend()
        elif m == "rest":  _backend = RestBackend()
        else: raise RuntimeError(f"Unknown CLAB_MODE: {m}")
    return _backend
```

Existing module-level functions (`list_labs()`, `deploy()`, etc.) become one-line shims:

```python
async def list_labs() -> list[dict]:
    return await get_backend().list_labs()
```

`api/routes/containerlab.py` requires **zero changes**.

---

## Section 2: SSH Connection Pool

### `_SshPool` class (`_ssh.py`)

```python
class _SshPool:
    def __init__(self, max_size: int = 4):
        self._max_size = max_size
        self._pool: list[paramiko.SSHClient] = []
        self._sem = asyncio.Semaphore(max_size)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[paramiko.SSHClient]:
        await self._sem.acquire()
        try:
            client = self._checkout()
            yield client
        finally:
            self._pool.append(client)
            self._sem.release()

    def _checkout(self) -> paramiko.SSHClient:
        while self._pool:
            client = self._pool.pop()
            if self._is_healthy(client):
                return client
            client.close()
        return self._connect()

    def _connect(self) -> paramiko.SSHClient: ...   # creates + connects one paramiko client
    def _is_healthy(self, client) -> bool:
        return client.get_transport() is not None and client.get_transport().is_active()
```

### Integration

- `SshBackend.__init__()` creates `self._pool = _SshPool(max_size=settings.clab_ssh_pool_size)`
- Every SSH command operation uses `async with self._pool.acquire() as client:`
- Pool is created lazily — `_SshPool` is instantiated at `SshBackend()` construction but makes no connections until first `acquire()` call
- New config field: `clab_ssh_pool_size: int = 4` in `api/config.py`

### SSH Console Channel

Console sessions get their own dedicated channel from the pool connection's transport — they do **not** hold a pool slot for the duration of the session:

```python
async def node_console(self, ws, lab_name, node_name):
    container = f"clab-{lab_name}-{node_name}"
    async with self._pool.acquire() as client:
        transport = client.get_transport()
        channel = transport.open_session()
        channel.get_pty()
        channel.invoke_shell()
        # invoke_shell and exec_command are mutually exclusive on a paramiko channel;
        # send the docker command as shell input instead
        await asyncio.to_thread(channel.sendall, f"docker exec -it {container} /bin/sh\n")
    # pool slot released here; channel stays open independently

    async def to_ws():
        while True:
            data = await asyncio.to_thread(channel.recv, 4096)
            if not data:
                return
            await ws.send_bytes(data)

    async def from_ws():
        while True:
            data = await ws.receive_bytes()
            await asyncio.to_thread(channel.sendall, data)

    tasks = [asyncio.create_task(to_ws()), asyncio.create_task(from_ws())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    channel.close()
```

This replaces the current busy-poll `channel.recv_ready()` thread loop entirely.

---

## Section 3: UX / Reliability Fixes

### Fix 1 — Inline File Editing (`WorkspaceBrowser.jsx`)

**Problem:** The pencil icon opens a rename modal. There is no way to open and edit an existing topology file's content.

**Change:**

- Add a distinct edit action icon (`IconFileCode`) next to topology files in the workspace item row
- On click: call `getTopology(item.path)`, populate `fileContent`, `fileName`, and `editingFile` state, open the existing file modal in edit mode
- The existing `saveMut` → `saveWorkspaceFile` path already handles updates correctly when `editingFile` is set — no backend changes needed
- Non-topology files (non-`.yml`/`.yaml`) show the edit icon too, but load raw content without syntax highlighting enforcement

### Fix 2 — Delete Confirmation (`WorkspaceBrowser.jsx`)

**Problem:** Clicking the trash icon on a workspace file immediately calls `deleteMut.mutate(item.path)` with no confirmation — inconsistent with the lab destroy flow which has a confirm modal.

**Change:**

- Add state: `const [confirmDeleteTarget, setConfirmDeleteTarget] = useState(null)`
- Replace `deleteMut.mutate(item.path)` with `setConfirmDeleteTarget(item.path)`
- Add a small modal (mirrors lab destroy pattern): displays `<Code>{filename}</Code>`, Cancel + red Delete button
- On confirm: call `deleteMut.mutate(confirmDeleteTarget, { onSettled: () => setConfirmDeleteTarget(null) })`

### Fix 3 — SSH Console Busy-Poll Elimination (`_ssh.py`)

**Problem:** Current `ssh_node_console()` spins a daemon thread calling `channel.recv_ready()` in a tight loop. This wastes CPU and silently hangs on abrupt client disconnect — the thread never exits cleanly.

**Fix:** Replace with the blocking-read-in-thread pattern (matching the local PTY backend's approach):

- Use `asyncio.to_thread(channel.recv, 4096)` — blocks cleanly in a thread until data arrives or EOF
- `channel.recv()` returning `b""` signals EOF/close — loop exits naturally
- Described in full in Section 2 SSH Console Channel above

### Fix 4 — REST Deploy Streaming (`_rest.py`)

**Problem:** `rest_deploy_stream()` calls the blocking `rest_deploy()` and emits two synthetic events — no real streaming occurs. The user sees the spinner until the entire deployment completes, then a single success event.

**Fix:**
- Use `httpx.AsyncClient.stream("POST", ...)` to consume the clab-api-server's chunked/SSE response line-by-line
- Each line is yielded as `{"type": "log", "line": line}`
- Final exit: parse last event for success/error and yield appropriately
- Graceful fallback: if the server returns a non-streaming response (e.g. older clab-api-server version), catch the non-chunked response and fall back to the current two-event behavior with a log note: `{"type": "log", "line": "[REST backend does not support streaming — deployment complete]\n"}`

---

## Out of Scope (Deferred)

The following are noted for the follow-up performance optimization pass:

- Query caching / stale-time tuning on `listLabs` and `getCLabStatus` React Query calls
- Lab list poll interval reduction with WebSocket-based push updates
- `inspect_lab` result caching in the drawer
- `rest_list_labs` / `rest_inspect_lab` response caching with short TTL

---

## Implementation Sequencing

1. **Backend refactor** — create `_base.py`, `_local.py`, `_ssh.py` (without pool), `_rest.py`, `_workspace.py`; update `__init__.py` shims; verify all existing routes still work
2. **SSH pool** — add `_SshPool` to `_ssh.py`; add `clab_ssh_pool_size` config; wire into `SshBackend`
3. **SSH console fix** — replace busy-poll in `SshBackend.node_console()`
4. **REST streaming fix** — update `RestBackend.deploy_stream()` with `httpx` streaming
5. **Frontend: file edit** — add edit icon + load-and-open flow to `WorkspaceBrowser.jsx`
6. **Frontend: delete confirm** — add confirm modal to `WorkspaceBrowser.jsx`
