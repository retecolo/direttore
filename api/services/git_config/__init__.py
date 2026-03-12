#!/usr/bin/env python3
"""Git-backed config repository service.

Manages a local git clone of a network config repository.

Layout inside the repo:
    <hostname>.txt     — current running config for each device
    (flat, no subdirectories — keeps history simple and grep-friendly)

Operations are synchronous (gitpython uses subprocess internally) and
wrapped in asyncio.to_thread() at the route layer so FastAPI stays async.
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import git
from git import Actor, InvalidGitRepositoryError, Repo

from api.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitise(hostname: str) -> str:
    """Turn a hostname into a safe filename (strip path separators etc.)."""
    safe = re.sub(r"[^\w.\-]", "_", hostname)
    return safe.lower()


def _repo_path() -> Path:
    return Path(settings.git_config_local_path)


def _author() -> Actor:
    return Actor(settings.git_config_author_name, settings.git_config_author_email)


def _authenticated_url() -> str:
    """Inject PAT credentials into an HTTPS clone URL if configured."""
    url = settings.git_config_repo
    token = settings.git_config_auth_token
    if token and url.startswith("https://"):
        # https://token@github.com/org/repo.git
        url = url.replace("https://", f"https://{token}@", 1)
    return url


# ---------------------------------------------------------------------------
# Repo initialisation
# ---------------------------------------------------------------------------

def ensure_repo() -> Repo:
    """
    Return a gitpython Repo, cloning from remote if the local path doesn't
    exist yet, or pulling the latest changes if it does.

    Raises RuntimeError if GIT_CONFIG_REPO is not configured.
    """
    if not settings.git_config_repo:
        raise RuntimeError("GIT_CONFIG_REPO is not configured in .env")

    path = _repo_path()

    if not path.exists() or not (path / ".git").exists():
        log.info("Cloning config repo %s → %s", settings.git_config_repo, path)
        path.mkdir(parents=True, exist_ok=True)
        repo = Repo.clone_from(
            _authenticated_url(),
            str(path),
            branch=settings.git_config_branch,
        )
    else:
        repo = Repo(str(path))
        origin = repo.remotes.origin
        origin.set_url(_authenticated_url())
        log.debug("Pulling latest from config repo")
        origin.pull(settings.git_config_branch)

    return repo


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def read_config(hostname: str) -> str | None:
    """Return the current config text for a hostname, or None if not found."""
    path = _repo_path() / f"{_sanitise(hostname)}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def config_history(hostname: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return the git log for a device's config file."""
    try:
        repo = Repo(str(_repo_path()))
    except InvalidGitRepositoryError:
        return []

    filename = f"{_sanitise(hostname)}.txt"
    commits = list(repo.iter_commits(settings.git_config_branch, paths=filename, max_count=limit))

    return [
        {
            "ref":       c.hexsha,
            "short_ref": c.hexsha[:8],
            "message":   c.message.strip(),
            "author":    str(c.author),
            "timestamp": datetime.fromtimestamp(c.committed_date, tz=timezone.utc).isoformat(),
        }
        for c in commits
    ]


def read_config_at_ref(hostname: str, ref: str) -> str | None:
    """Return the config text as it was at a specific git commit."""
    try:
        repo = Repo(str(_repo_path()))
        filename = f"{_sanitise(hostname)}.txt"
        blob = repo.commit(ref).tree / filename
        return blob.data_stream.read().decode("utf-8", errors="replace")
    except (KeyError, Exception) as exc:
        log.warning("Could not read %s at ref %s: %s", hostname, ref, exc)
        return None


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def write_config(hostname: str, content: str, commit_message: str | None = None) -> str:
    """
    Write (or update) a device config file and push to the remote.

    Returns the commit SHA.
    """
    repo = ensure_repo()
    filename = f"{_sanitise(hostname)}.txt"
    file_path = _repo_path() / filename

    file_path.write_text(content, encoding="utf-8")
    repo.index.add([filename])

    if not repo.index.diff("HEAD") and not repo.untracked_files:
        # Nothing changed — return the current HEAD SHA
        log.info("Config for %s unchanged — nothing to commit", hostname)
        return repo.head.commit.hexsha

    ts  = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = commit_message or f"chore: backup {hostname} config [{ts}]"
    commit = repo.index.commit(msg, author=_author(), committer=_author())

    # Push
    origin = repo.remotes.origin
    origin.set_url(_authenticated_url())
    push_result = origin.push(settings.git_config_branch)
    for info in push_result:
        if info.flags & git.PushInfo.ERROR:
            raise RuntimeError(f"Git push failed: {info.summary}")

    log.info("Committed and pushed config for %s: %s", hostname, commit.hexsha[:8])
    return commit.hexsha
