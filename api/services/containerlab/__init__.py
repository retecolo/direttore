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
