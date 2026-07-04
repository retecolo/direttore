"""FastAPI router — ContainerLab topology management.

Mounted at /api/containerlab — only active when CLAB_MODE is configured.
"""

import logging
from pathlib import Path
from typing import Any, Literal

import json
from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
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
    status["features"] = {
        "git_topologies": bool(settings.clab_topo_git_repo),
        "local_topo_dir": settings.clab_topo_dir,
        "mode": settings.clab_mode,
        "ssh_host": settings.clab_ssh_host if settings.clab_mode == "ssh" else None,
        "ssh_user": settings.clab_ssh_user if settings.clab_mode == "ssh" else None,
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
        log.exception("Error in list_labs:")
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
    reconfigure: bool = True


def _check_topo_file(topo_file: str) -> None:
    if "/" in topo_file or ".." in topo_file:
        raise HTTPException(status_code=400, detail="topo_file must be a plain filename, not a path")


@router.post("/labs")
async def deploy_lab(req: DeployRequest) -> dict[str, Any]:
    """Deploy a containerlab topology from a file in CLAB_TOPO_DIR."""
    _require_clab()
    _check_topo_file(req.topo_file)
    try:
        return await clab.deploy(req.topo_file, reconfigure=req.reconfigure)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/labs/validate")
async def validate_lab(req: DeployRequest) -> dict[str, Any]:
    """Validate a topology file without deploying (runs clab deploy --check)."""
    _require_clab()
    _check_topo_file(req.topo_file)
    try:
        return await clab.validate(req.topo_file)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/labs/deploy-stream")
async def deploy_lab_stream(req: DeployRequest) -> StreamingResponse:
    """Deploy a containerlab topology and stream the output back via SSE."""
    _require_clab()
    _check_topo_file(req.topo_file)

    async def event_generator():
        try:
            async for chunk in clab.deploy_stream(req.topo_file, reconfigure=req.reconfigure):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.delete("/labs/{name}")
async def destroy_lab(name: str) -> dict[str, Any]:
    """Destroy (stop and remove) a running lab."""
    _require_clab()
    try:
        return await clab.destroy(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Node actions — restart / stop / start
# ---------------------------------------------------------------------------

class NodeActionRequest(BaseModel):
    action: Literal["restart", "stop", "start"]


@router.post("/labs/{lab_name}/nodes/{node_name}/action")
async def node_action(lab_name: str, node_name: str, req: NodeActionRequest) -> dict[str, Any]:
    """Run restart, stop, or start on a single node container."""
    _require_clab()
    try:
        return await clab.node_action(lab_name, node_name, req.action)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Node console — WebSocket SSH/exec terminal
# ---------------------------------------------------------------------------

@router.websocket("/labs/{lab_name}/nodes/{node_name}/console")
async def node_console(ws: WebSocket, lab_name: str, node_name: str):
    """WebSocket terminal session for a node container."""
    if not settings.clab_mode:
        await ws.close(code=1008, reason="ContainerLab not configured")
        return
    await ws.accept()
    try:
        await clab.node_console(ws, lab_name, node_name)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_bytes(f"\r\n[Error: {exc}]\r\n".encode())
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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
    if not content:
        raise HTTPException(status_code=404, detail=f"Topology file not found: {filename}")
    history = []
    if settings.clab_topo_git_repo:
        history = clab.list_topology_git_history(filename)
    return {"filename": filename, "content": content, "git_history": history}


@router.post("/topologies")
async def upload_topology(file: UploadFile = File(...), path: str = "") -> dict[str, Any]:
    """Upload a new topology .yml or config file to CLAB_TOPO_DIR."""
    _require_clab()
    safe_path = path.lstrip("/")
    filename = Path(file.filename or "file").name
    full_path = str(Path(safe_path) / filename) if safe_path else filename

    content = (await file.read()).decode(errors='replace')
    try:
        clab.write_topology_file(full_path, content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"uploaded": True, "filename": full_path, "size": len(content)}


# ---------------------------------------------------------------------------
# Workspace — browse / CRUD / rename / duplicate
# ---------------------------------------------------------------------------

class CreateFolderRequest(BaseModel):
    path: str


@router.post("/workspace/folder")
async def create_folder(req: CreateFolderRequest) -> dict[str, Any]:
    _require_clab()
    topo_dir = Path(settings.clab_topo_dir).resolve()
    target = (topo_dir / req.path).resolve()
    if topo_dir not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid path")
    target.mkdir(parents=True, exist_ok=True)
    return {"created": True, "path": req.path}


class WriteFileRequest(BaseModel):
    path: str
    content: str


@router.get("/workspace/file")
async def read_workspace_file(path: str) -> dict[str, Any]:
    """Read a workspace file's content by relative path (supports subdirectories)."""
    _require_clab()
    content = clab.read_topology_file(path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    return {"path": path, "content": content}


@router.post("/workspace/file")
async def save_workspace_file(req: WriteFileRequest) -> dict[str, Any]:
    _require_clab()
    try:
        clab.write_topology_file(req.path, req.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"saved": True, "path": req.path}


@router.delete("/workspace/file")
async def delete_workspace_file(path: str) -> dict[str, Any]:
    _require_clab()
    if not clab.delete_topology_file(path):
        raise HTTPException(status_code=404, detail="File or directory not found")
    return {"deleted": True, "path": path}


class RenameRequest(BaseModel):
    old_path: str
    new_name: str


@router.post("/workspace/rename")
async def rename_workspace_item(req: RenameRequest) -> dict[str, Any]:
    """Rename a file or directory within the workspace."""
    _require_clab()
    try:
        new_path = clab.rename_workspace_item(req.old_path, req.new_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"renamed": True, "old_path": req.old_path, "new_path": new_path}


class DuplicateRequest(BaseModel):
    path: str
    new_name: str


@router.post("/workspace/duplicate")
async def duplicate_workspace_file(req: DuplicateRequest) -> dict[str, Any]:
    """Copy a file to a new name in the same directory."""
    _require_clab()
    try:
        new_path = clab.duplicate_workspace_file(req.path, req.new_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"duplicated": True, "source": req.path, "new_path": new_path}


@router.get("/workspace/{subpath:path}")
async def list_workspace(subpath: str = "") -> dict[str, Any]:
    """List directory contents for the topology workspace."""
    _require_clab()
    files = clab.list_workspace(subpath)
    return {
        "path": subpath,
        "items": files,
    }


# ---------------------------------------------------------------------------
# Git topology history
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
