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
    if path.exists() and path.is_dir():
        raise ValueError("Invalid path: is a directory")
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
