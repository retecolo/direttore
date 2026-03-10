#!/usr/bin/env python3
"""Unimus Pro REST API client.

Unimus API v2 reference: https://unimus.net/api/swagger-ui.html
Authentication: Bearer token (Settings → Security → API access tokens)

All functions use httpx async client with SSL verification disabled by default
(many Unimus installs use self-signed certs).
"""

import base64
import logging
from typing import Any

import httpx

from api.config import settings

log = logging.getLogger(__name__)
TIMEOUT = 30          # Unimus can be slow on large device sets
VERIFY  = False       # Most Unimus installs use self-signed TLS


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.unimus_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return settings.unimus_url.rstrip("/")


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

async def check_status() -> dict[str, Any]:
    """Return reachability info for the configured Unimus instance."""
    if not settings.unimus_url or not settings.unimus_token:
        return {"reachable": False, "reason": "UNIMUS_URL or UNIMUS_TOKEN not configured"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
            r = await client.get(f"{_base()}/api/v2/", headers=_headers())
            r.raise_for_status()
            data = r.json()
            return {
                "reachable": True,
                "version": data.get("version", "unknown"),
                "url": settings.unimus_url,
            }
    except Exception as exc:
        return {"reachable": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Device lookup
# ---------------------------------------------------------------------------

async def list_devices(page: int = 0, size: int = 500) -> list[dict[str, Any]]:
    """Return all Unimus-managed devices (paginated, flattened)."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/devices",
            params={"page": page, "size": size},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("content", [])


async def find_device_by_address(address: str) -> dict[str, Any] | None:
    """Find a Unimus device by its management IP address.

    POST /api/v2/devices/findByAddress accepts a JSON body with an
    'address' field and returns the first matching device, or null.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.post(
            f"{_base()}/api/v2/devices/findByAddress",
            json={"address": address},
            headers=_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json().get("data")
        # May return a list or a single object depending on version
        if isinstance(data, list):
            return data[0] if data else None
        return data


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

async def list_backups(device_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent backups for a device (metadata only, no content)."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/devices/{device_id}/backups",
            params={"size": limit},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("content", [])


async def get_latest_backup(device_id: str) -> dict[str, Any] | None:
    """Return the latest backup object for a device (with decoded content)."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/devices/{device_id}/backups/latest",
            headers=_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        backup = r.json().get("data", {})
        return _decode_backup(backup)


async def get_backup_by_id(device_id: str, backup_id: str) -> dict[str, Any] | None:
    """Return a specific backup object with decoded config content."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/devices/{device_id}/backups/{backup_id}",
            headers=_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return _decode_backup(r.json().get("data", {}))


def _decode_backup(backup: dict[str, Any]) -> dict[str, Any]:
    """Decode base64-encoded config content in a backup object."""
    content = backup.get("content", "")
    if content:
        try:
            backup["content_text"] = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            backup["content_text"] = content  # fall back to raw
    else:
        backup["content_text"] = ""
    return backup


# ---------------------------------------------------------------------------
# Trigger backup job
# ---------------------------------------------------------------------------

async def trigger_backup(device_ids: list[str]) -> dict[str, Any]:
    """
    Trigger a backup job for one or more Unimus-managed devices.

    Returns the job object: { jobId, status, ... }
    The caller should poll /api/v2/jobs/{jobId} for completion.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.post(
            f"{_base()}/api/v2/jobs/backupDevices",
            json={"deviceIds": device_ids},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("data", {})


async def poll_job(job_id: str) -> dict[str, Any]:
    """Return current job status. Poll until status is FINISHED or FAILED."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/jobs/{job_id}",
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("data", {})


# ---------------------------------------------------------------------------
# Config push (Unimus Pro)
# ---------------------------------------------------------------------------

async def push_config(device_id: str, config_text: str, note: str = "") -> dict[str, Any]:
    """
    Push a configuration to a device via Unimus Pro.

    Unimus Pro provides a 'scheduled config push' job.  The config text is
    base64-encoded and submitted as a one-time job.

    Returns the job object for polling.
    """
    encoded = base64.b64encode(config_text.encode("utf-8")).decode("ascii")
    payload: dict[str, Any] = {
        "deviceIds": [device_id],
        "scriptContent": encoded,
        "note": note or "Pushed by Direttore",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.post(
            f"{_base()}/api/v2/jobs/pushConfig",
            json=payload,
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json().get("data", {})
