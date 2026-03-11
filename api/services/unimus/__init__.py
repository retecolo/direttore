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


def _fmt_error(r: httpx.Response) -> str:
    """Format a non-success HTTP response for logging / error messages."""
    try:
        body = r.json()
    except Exception:
        body = r.text[:500]
    return f"HTTP {r.status_code} from {r.url}: {body}"


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

async def check_status() -> dict[str, Any]:
    """
    Return reachability info for the configured Unimus instance.

    Tries GET /api/v2/devices?size=1 as the probe — this is a real API
    endpoint present in all Unimus v2 versions, so it's more reliable than
    hitting /api/v2/ which may redirect or return HTML.
    """
    if not settings.unimus_url or not settings.unimus_token:
        return {
            "reachable": False,
            "reason":    "UNIMUS_URL or UNIMUS_TOKEN not configured in .env",
            "url":       settings.unimus_url or "(not set)",
        }

    probe_url = f"{_base()}/api/v2/devices"
    log.debug("Unimus status probe: GET %s", probe_url)
    try:
        async with httpx.AsyncClient(timeout=10, verify=VERIFY) as client:
            r = await client.get(probe_url, params={"size": 1}, headers=_headers())

        log.debug("Unimus probe response: %s", r.status_code)

        if r.status_code == 401:
            return {
                "reachable": False,
                "reason":    "Authentication failed (401) — check UNIMUS_TOKEN",
                "url":       settings.unimus_url,
                "http_status": 401,
            }
        if r.status_code == 403:
            return {
                "reachable": False,
                "reason":    "Forbidden (403) — token may lack API permissions",
                "url":       settings.unimus_url,
                "http_status": 403,
            }
        if not r.is_success:
            return {
                "reachable":   False,
                "reason":      _fmt_error(r),
                "url":         settings.unimus_url,
                "http_status": r.status_code,
            }

        # Parse version from response if available
        data = {}
        try:
            data = r.json()
        except Exception:
            pass

        version = (
            data.get("version")
            or (data.get("data") or {}).get("version")
            or "connected"
        )
        return {
            "reachable": True,
            "version":   version,
            "url":       settings.unimus_url,
        }

    except httpx.ConnectError as exc:
        return {
            "reachable": False,
            "reason":    f"Connection refused / unreachable: {exc}",
            "url":       settings.unimus_url,
        }
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "reason":    f"Connection timed out after 10s — is {settings.unimus_url} reachable from the server?",
            "url":       settings.unimus_url,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "reason":    f"{type(exc).__name__}: {exc}",
            "url":       settings.unimus_url,
        }


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
    """
    Find a Unimus device by its management IP address.

    Tries GET /api/v2/devices/findByAddress?address=x (query param form)
    first, then falls back to POST with JSON body if that returns 405/404,
    to handle differences between Unimus versions.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        # Attempt 1: GET with query param (common in newer Unimus builds)
        r = await client.get(
            f"{_base()}/api/v2/devices/findByAddress",
            params={"address": address},
            headers=_headers(),
        )
        log.debug("findByAddress GET %s → %s", address, r.status_code)

        if r.status_code == 405:
            # Attempt 2: POST with JSON body (older Unimus API spec)
            r = await client.post(
                f"{_base()}/api/v2/devices/findByAddress",
                json={"address": address},
                headers=_headers(),
            )
            log.debug("findByAddress POST %s → %s", address, r.status_code)

        if r.status_code == 404:
            return None
        if not r.is_success:
            log.warning("findByAddress error: %s", _fmt_error(r))
            return None

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
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.post(
            f"{_base()}/api/v2/jobs/backupDevices",
            json={"deviceIds": device_ids},
            headers=_headers(),
        )
        if not r.is_success:
            log.warning("trigger_backup error: %s", _fmt_error(r))
        r.raise_for_status()
        return r.json().get("data", {})


async def poll_job(job_id: str) -> dict[str, Any]:
    """Return current job status."""
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

    The config text is base64-encoded and submitted as a scheduled job.
    Returns the job object for polling.
    """
    encoded = base64.b64encode(config_text.encode("utf-8")).decode("ascii")
    payload: dict[str, Any] = {
        "deviceIds":     [device_id],
        "scriptContent": encoded,
        "note":          note or "Pushed by Direttore",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.post(
            f"{_base()}/api/v2/jobs/pushConfig",
            json=payload,
            headers=_headers(),
        )
        if not r.is_success:
            log.warning("push_config error: %s", _fmt_error(r))
        r.raise_for_status()
        return r.json().get("data", {})


# ---------------------------------------------------------------------------
# Debug helper (used by /api/hardware/debug-unimus)
# ---------------------------------------------------------------------------

async def raw_probe() -> dict[str, Any]:
    """
    Probe multiple Unimus endpoints and return raw results for debugging.
    Useful when diagnosing connectivity or auth problems.
    """
    if not settings.unimus_url:
        return {"error": "UNIMUS_URL not configured"}

    results: dict[str, Any] = {
        "base_url": _base(),
        "token_set": bool(settings.unimus_token),
        "token_prefix": settings.unimus_token[:6] + "…" if settings.unimus_token else "(empty)",
        "probes": {},
    }

    probes = [
        ("GET /api/v2/devices?size=1", "GET",  f"{_base()}/api/v2/devices", {"size": 1}),
        ("GET /api/v2/",              "GET",  f"{_base()}/api/v2/",          {}),
    ]

    async with httpx.AsyncClient(timeout=10, verify=VERIFY) as client:
        for label, method, url, params in probes:
            try:
                if method == "GET":
                    r = await client.get(url, params=params, headers=_headers())
                else:
                    r = await client.post(url, headers=_headers())

                try:
                    body = r.json()
                except Exception:
                    body = r.text[:300]

                results["probes"][label] = {
                    "status":   r.status_code,
                    "body":     body,
                }
            except Exception as exc:
                results["probes"][label] = {"error": f"{type(exc).__name__}: {exc}"}

    return results
