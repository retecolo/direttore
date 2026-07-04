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
