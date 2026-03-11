#!/usr/bin/env python3
"""Unimus Pro REST API client.

Unimus API v2 reference: https://unimus.net/api/swagger-ui.html
Authentication: Bearer token (Settings → Security → API access tokens)

All functions use httpx async client with SSL verification disabled by default
(many Unimus installs use self-signed certs).
"""

import base64
import logging
import socket
from typing import Any

import httpx

from api.config import settings
from api.services.unimus import link_store as link_store  # noqa: F401 – re-exported

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


def _unwrap(body: dict[str, Any]) -> Any:
    """
    Normalise Unimus API response shapes.

    Older Unimus versions / some endpoints wrap the payload:
        { "data": <payload> }
    Newer versions (confirmed from live API) return the payload directly:
        { "content": [...], "paginator": {...} }   (for list endpoints)
        { "id": ..., ... }                          (for single-object endpoints)

    Returns the unwrapped payload dict/list.
    """
    if "data" in body:
        return body["data"]
    return body


def _unwrap_list(body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract the items list from a Unimus paginated response.

    Actual format (confirmed from live API):
        { "data": [...items...], "paginator": { "totalCount": N } }

    Legacy / alternate format:
        { "data": { "content": [...] }, "paginator": {...} }
        { "content": [...] }   (no wrapper)
    """
    if "data" in body:
        data = body["data"]
        if isinstance(data, list):
            return data                   # standard format ✓
        if isinstance(data, dict):
            return data.get("content", [])  # legacy nested format
    if "content" in body:
        return body["content"]           # no-wrapper fallback
    return []


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

async def check_status() -> dict[str, Any]:
    """
    Return reachability info for the configured Unimus instance.

    Uses GET /api/v2/devices?size=1 as the probe — the root /api/v2/ returns
    404 in many Unimus versions, so a real API endpoint is more reliable.
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
            return {"reachable": False, "reason": "Authentication failed (401) — check UNIMUS_TOKEN",
                    "url": settings.unimus_url, "http_status": 401}
        if r.status_code == 403:
            return {"reachable": False, "reason": "Forbidden (403) — token may lack API permissions",
                    "url": settings.unimus_url, "http_status": 403}
        if not r.is_success:
            return {"reachable": False, "reason": _fmt_error(r),
                    "url": settings.unimus_url, "http_status": r.status_code}

        body  = r.json()
        # paginator is always at the top level, regardless of data shape
        total = (body.get("paginator") or {}).get("totalCount", "?")

        return {
            "reachable":    True,
            "device_count": total,
            "url":          settings.unimus_url,
        }

    except httpx.ConnectError as exc:
        return {"reachable": False, "reason": f"Connection refused / unreachable: {exc}",
                "url": settings.unimus_url}
    except httpx.TimeoutException:
        return {"reachable": False,
                "reason": f"Timed out after 10s — is {settings.unimus_url} reachable?",
                "url": settings.unimus_url}
    except Exception as exc:
        return {"reachable": False, "reason": f"{type(exc).__name__}: {exc}",
                "url": settings.unimus_url}


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
        return _unwrap_list(r.json())


async def find_device_by_address(address: str) -> dict[str, Any] | None:
    """
    Find a Unimus device by its management IP address.

    Tries GET with query param first (newer Unimus), then POST with JSON body
    (older spec), to handle version differences.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        # Attempt 1: GET with query param
        r = await client.get(
            f"{_base()}/api/v2/devices/findByAddress",
            params={"address": address},
            headers=_headers(),
        )
        log.debug("findByAddress GET %s → %s", address, r.status_code)

        if r.status_code == 405:
            # Attempt 2: POST with JSON body
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

        payload = _unwrap(r.json())
        # May be a single object, a list, or wrapped
        if isinstance(payload, list):
            return payload[0] if payload else None
        if isinstance(payload, dict) and "content" in payload:
            items = payload["content"]
            return items[0] if items else None
        return payload if isinstance(payload, dict) and payload else None


async def find_device(
    address: str,
    name: str | None = None,
    netbox_id: int | str | None = None,
) -> dict[str, Any] | None:
    """
    Locate a Unimus device using multiple strategies, in order:

    0. Link store             — manually pinned NetBox ID → Unimus address
    1. findByAddress(address) — exact match on the stored address field
    2. findByAddress(rDNS)    — reverse-DNS FQDN of the IP
    3. findByAddress(name)    — NetBox device name as the Unimus address key
    4. Linear scan            — case-insensitive / substring match across all devices

    Pass netbox_id to enable Strategy 0 (manual link store lookup).
    """
    # Strategy 0 — check manual link store first (fastest, most reliable)
    if netbox_id is not None:
        linked_addr = link_store.get_link(netbox_id)
        if linked_addr:
            log.debug("find_device: strategy 0 — link store hit for device %s: %s",
                      netbox_id, linked_addr)
            device = await find_device_by_address(linked_addr)
            if device:
                return device
            log.warning("find_device: link store address '%s' not found in Unimus — "
                        "may be stale; falling through to other strategies", linked_addr)

    # Strategy 1 — exact IP / address match
    log.debug("find_device: strategy 1 — findByAddress(%s)", address)
    device = await find_device_by_address(address)
    if device:
        log.debug("find_device: found via address match")
        return device

    # Strategy 2 — reverse-DNS FQDN of the IP
    fqdn: str | None = None
    try:
        fqdn = socket.gethostbyaddr(address)[0]
        log.debug("find_device: rDNS(%s) → %s", address, fqdn)
    except Exception:
        pass

    if fqdn and fqdn.lower() != address.lower():
        log.debug("find_device: strategy 2 — findByAddress(%s)", fqdn)
        device = await find_device_by_address(fqdn)
        if device:
            log.debug("find_device: found via rDNS hostname")
            return device

    # Strategy 3 — NetBox device name as the Unimus address field
    if name and name.lower() not in (address.lower(), (fqdn or "").lower()):
        log.debug("find_device: strategy 3 — findByAddress(%s)", name)
        device = await find_device_by_address(name)
        if device:
            log.debug("find_device: found via device name")
            return device

    # Strategy 4 — linear scan (last resort; tolerates partial/case mismatches)
    log.debug("find_device: strategy 4 — linear scan of all Unimus devices")
    candidates: list[str] = [address.lower()]
    if fqdn:
        candidates.append(fqdn.lower())
    if name:
        candidates.append(name.lower())

    try:
        all_devices = await list_devices(size=1000)
        for d in all_devices:
            d_addr = (d.get("address") or "").lower()
            if d_addr in candidates or any(c in d_addr for c in candidates):
                log.info("find_device: matched '%s' via linear scan (candidates=%s)",
                         d_addr, candidates)
                return d
    except Exception as exc:
        log.warning("find_device: linear scan failed: %s", exc)

    log.warning("find_device: no match for address=%s name=%s", address, name)
    return None


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
        return _unwrap_list(r.json())


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
        backup = _unwrap(r.json())
        if isinstance(backup, list):
            backup = backup[0] if backup else None
        if not isinstance(backup, dict) or not backup:
            return None
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
        backup = _unwrap(r.json())
        if isinstance(backup, list):
            backup = backup[0] if backup else None
        if not isinstance(backup, dict) or not backup:
            return None
        return _decode_backup(backup)


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

# Known Unimus endpoint variants for triggering a device backup.
# Different Unimus builds/versions use different paths — we try each in order.
_BACKUP_JOB_VARIANTS: list[tuple[str, str]] = [
    # (HTTP method, URL path)
    ("POST", "/api/v2/jobs/backupDevices"),       # documented Pro API
    ("POST", "/api/v2/jobs/backup/devices"),       # alternate path format
    ("POST", "/api/v2/devices/backup"),            # some builds
    ("POST", "/api/v2/jobs"),                      # generic job creation
]


async def trigger_backup(
    device_ids: list[str | int],
) -> dict[str, Any]:
    """
    Attempt to trigger a backup job for the given device IDs.

    Tries each known Unimus endpoint variant in order until one succeeds
    (2xx response).  If all variants return 404 / 405, falls back to
    returning the latest existing backup for the first device ID so the
    caller can still archive whatever Unimus already has.

    Returns a dict with:
      {"triggered": bool, "job": {...} | None, "fallback_backup": {...} | None,
       "tried": ["POST /path → 404", ...], "error": str | None}
    """
    result: dict[str, Any] = {
        "triggered":        False,
        "job":              None,
        "fallback_backup":  None,
        "tried":            [],
        "error":            None,
    }

    # Body variants to try alongside each endpoint
    def _body(path: str) -> dict[str, Any]:
        """Construct the right request body for each endpoint style."""
        if "backupDevices" in path or "backup/devices" in path or "devices/backup" in path:
            return {"deviceIds": [str(d) for d in device_ids]}
        # Generic /api/v2/jobs endpoint
        return {"type": "BACKUP", "deviceIds": [str(d) for d in device_ids]}

    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        for method, path in _BACKUP_JOB_VARIANTS:
            url = f"{_base()}{path}"
            try:
                r = await client.post(url, json=_body(path), headers=_headers())
                label = f"{method} {path} → {r.status_code}"
                result["tried"].append(label)
                log.debug("trigger_backup: %s", label)

                if r.is_success:
                    result["triggered"] = True
                    result["job"]       = _unwrap(r.json()) or {}
                    log.info("trigger_backup: succeeded via %s", path)
                    return result

                if r.status_code not in (404, 405, 400):
                    # Unexpected failure (auth, server error) — stop trying
                    result["error"] = _fmt_error(r)
                    log.warning("trigger_backup: stopping on %s: %s",
                                r.status_code, result["error"])
                    return result
                # 404 / 405 — endpoint doesn’t exist, try next variant

            except Exception as exc:
                label = f"{method} {path} → {type(exc).__name__}: {exc}"
                result["tried"].append(label)
                log.warning("trigger_backup: %s", label)

    # All trigger endpoints failed — fetch latest existing backup as fallback
    if device_ids:
        log.warning(
            "trigger_backup: all job endpoints returned 404/405 — "
            "falling back to latest existing Unimus backup for device %s",
            device_ids[0],
        )
        try:
            backup = await get_latest_backup(str(device_ids[0]))
            result["fallback_backup"] = backup
            if backup:
                result["error"] = (
                    "Could not trigger a fresh backup (no working job endpoint found). "
                    "Returning the latest backup already stored in Unimus."
                )
            else:
                result["error"] = (
                    "Could not trigger a fresh backup and no existing backup found in Unimus."
                )
        except Exception as exc:
            result["error"] = f"Fallback get_latest_backup failed: {exc}"

    return result


async def poll_job(job_id: str) -> dict[str, Any]:
    """Return current job status."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=VERIFY) as client:
        r = await client.get(
            f"{_base()}/api/v2/jobs/{job_id}",
            headers=_headers(),
        )
        r.raise_for_status()
        return _unwrap(r.json()) or {}


# ---------------------------------------------------------------------------
# Config push (Unimus Pro)
# ---------------------------------------------------------------------------

async def push_config(device_id: str, config_text: str, note: str = "") -> dict[str, Any]:
    """Push a configuration to a device via Unimus Pro."""
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
        return _unwrap(r.json()) or {}


# ---------------------------------------------------------------------------
# Debug helper (used by /api/hardware/debug-unimus)
# ---------------------------------------------------------------------------

async def raw_probe() -> dict[str, Any]:
    """Probe multiple Unimus endpoints and return raw results for debugging."""
    if not settings.unimus_url:
        return {"error": "UNIMUS_URL not configured"}

    results: dict[str, Any] = {
        "base_url":    _base(),
        "token_set":   bool(settings.unimus_token),
        "token_prefix": settings.unimus_token[:6] + "\u2026" if settings.unimus_token else "(empty)",
        "probes":      {},
    }

    # (label, method, url, params, body)
    probes: list[tuple[str, str, str, dict, dict | None]] = [
        # Device list — confirms connectivity + auth
        ("GET /api/v2/devices?size=1", "GET",
         f"{_base()}/api/v2/devices", {"size": 1}, None),

        # Backup history (requires an actual device ID — use dummy 0)
        ("GET /api/v2/devices/0/backups", "GET",
         f"{_base()}/api/v2/devices/0/backups", {}, None),

        # Job trigger endpoint variants — POST with minimal body
        ("POST /api/v2/jobs/backupDevices", "POST",
         f"{_base()}/api/v2/jobs/backupDevices", {}, {"deviceIds": []}),

        ("POST /api/v2/jobs/backup/devices", "POST",
         f"{_base()}/api/v2/jobs/backup/devices", {}, {"deviceIds": []}),

        ("POST /api/v2/devices/backup", "POST",
         f"{_base()}/api/v2/devices/backup", {}, {"deviceIds": []}),

        ("POST /api/v2/jobs", "POST",
         f"{_base()}/api/v2/jobs", {}, {"type": "BACKUP", "deviceIds": []}),

        # Config push (Pro feature)
        ("POST /api/v2/jobs/pushConfig", "POST",
         f"{_base()}/api/v2/jobs/pushConfig", {},
         {"deviceIds": [], "scriptContent": ""}),
    ]

    async with httpx.AsyncClient(timeout=10, verify=VERIFY) as client:
        for label, method, url, params, body in probes:
            try:
                if method == "POST":
                    r = await client.post(url, json=body, headers=_headers())
                else:
                    r = await client.get(url, params=params, headers=_headers())
                try:
                    rb = r.json()
                except Exception:
                    rb = r.text[:300]
                results["probes"][label] = {"status": r.status_code, "body": rb}
            except Exception as exc:
                results["probes"][label] = {"error": f"{type(exc).__name__}: {exc}"}

    return results
