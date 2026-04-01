"""FastAPI router — ContainerLab topology management.

Mounted at /api/containerlab — only active when CLAB_MODE is configured.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from api.config import settings
from api.services import containerlab as clab

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/containerlab", tags=["containerlab"])


def _require_clab():
    """Raise 503 if CLAB_MODE is not configured."""
    if not settings.clab_mode:
        raise HTTPException(
            status_code=503,
            detail="ContainerLab is not configured. Set CLAB_MODE in .env to enable.",
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status")
async def containerlab_status() -> dict[str, Any]:
    """Return whether the configured clab backend is reachable, including mode and version."""
    _require_clab()
    status = await clab.get_status()
    # Also surface which optional sub-features are configured
    status["features"] = {
        "git_topologies": bool(settings.clab_topo_git_repo),
        "local_topo_dir": settings.clab_topo_dir,
        "mode": settings.clab_mode,
    }
    return status


# ---------------------------------------------------------------------------
# Labs — list / inspect / deploy / destroy
# ---------------------------------------------------------------------------

@router.get("/labs")
async def list_labs() -> list[dict[str, Any]]:
    """List all running containerlab labs."""
    _require_clab()
    try:
        return await clab.list_labs()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/labs/{name}")
async def inspect_lab(name: str) -> dict[str, Any]:
    """Inspect a specific running lab by name."""
    _require_clab()
    try:
        return await clab.inspect_lab(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class DeployRequest(BaseModel):
    topo_file: str
    """Filename (relative to CLAB_TOPO_DIR) of the topology to deploy."""


@router.post("/labs")
async def deploy_lab(req: DeployRequest) -> dict[str, Any]:
    """Deploy a containerlab topology from a file in CLAB_TOPO_DIR."""
    _require_clab()
    # Safety: reject path traversal
    if "/" in req.topo_file or ".." in req.topo_file:
        raise HTTPException(status_code=400, detail="topo_file must be a plain filename, not a path")
    try:
        return await clab.deploy(req.topo_file)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/labs/{name}")
async def destroy_lab(name: str) -> dict[str, Any]:
    """Destroy (stop and remove) a running lab."""
    _require_clab()
    try:
        return await clab.destroy(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Topology files — list / read / upload
# ---------------------------------------------------------------------------

@router.get("/topologies")
async def list_topologies() -> dict[str, Any]:
    """List available .yml topology files in CLAB_TOPO_DIR."""
    _require_clab()
    files = clab.list_topology_files()
    git_configured = bool(settings.clab_topo_git_repo)
    return {
        "topo_dir": settings.clab_topo_dir,
        "git_configured": git_configured,
        "files": files,
    }


@router.get("/topologies/{filename}")
async def get_topology(filename: str) -> dict[str, Any]:
    """Return the raw YAML content of a topology file."""
    _require_clab()
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="filename must be a plain filename, not a path")
    content = clab.read_topology_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Topology file not found: {filename}")
    history = []
    if settings.clab_topo_git_repo:
        history = clab.list_topology_git_history(filename)
    return {"filename": filename, "content": content, "git_history": history}


@router.post("/topologies")
async def upload_topology(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a new topology .yml file to CLAB_TOPO_DIR."""
    _require_clab()
    filename = Path(file.filename or "topology.yml").name
    if not filename.endswith((".yml", ".yaml")):
        raise HTTPException(status_code=400, detail="Only .yml / .yaml files are accepted")
    content = (await file.read()).decode()
    clab.write_topology_file(filename, content)
    return {"uploaded": True, "filename": filename, "size": len(content)}


# ---------------------------------------------------------------------------
# Git topology history (only shown when CLAB_TOPO_GIT_REPO is set)
# ---------------------------------------------------------------------------

@router.get("/topologies/{filename}/history")
async def topology_git_history(filename: str, limit: int = 30) -> dict[str, Any]:
    """Return Git commit history for a topology file (requires CLAB_TOPO_GIT_REPO)."""
    _require_clab()
    if not settings.clab_topo_git_repo:
        raise HTTPException(
            status_code=503,
            detail="CLAB_TOPO_GIT_REPO is not configured — Git topology history unavailable",
        )
    history = clab.list_topology_git_history(filename, limit=limit)
    return {"filename": filename, "history": history}
