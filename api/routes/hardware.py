#!/usr/bin/env python3
"""FastAPI router — physical hardware management.

Surfaces NetBox physical devices and provides:
  - Config backup to Git and/or Unimus
  - Golden-config provisioning from Git or Unimus (selectable source of truth)
"""

import asyncio
import logging
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.config import settings
from api.services import unimus
from api.services import git_config as git
from api.services.netbox import client as nb

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hardware", tags=["hardware"])

# ---------------------------------------------------------------------------
# Helpers — NetBox device enrichment
# ---------------------------------------------------------------------------

def _mgmt_ip_from_device(device: dict[str, Any]) -> str | None:
    """
    Extract the best management IP from a NetBox device object.
    Priority: primary_ip4 > primary_ip > primary_ip6
    """
    for key in ("primary_ip4", "primary_ip", "primary_ip6"):
        obj = device.get(key)
        if obj:
            addr = obj.get("address", "") if isinstance(obj, dict) else str(obj)
            if addr:
                return addr.split("/")[0]   # strip CIDR mask
    return None


def _slim_device(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id":          d.get("id"),
        "name":        d.get("name") or "",
        "status":      (d.get("status") or {}).get("value", ""),
        "device_type": (d.get("device_type") or {}).get("display", ""),
        "manufacturer": ((d.get("device_type") or {}).get("manufacturer") or {}).get("name", ""),
        "site":        (d.get("site") or {}).get("name", ""),
        "rack":        (d.get("rack") or {}).get("display", ""),
        "role":        (d.get("device_role") or d.get("role") or {}).get("name", ""),
        "primary_ip":  _mgmt_ip_from_device(d),
        "tags":        [t.get("name", "") for t in (d.get("tags") or [])],
        "custom_fields": d.get("custom_fields") or {},
    }


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

@router.get("/status")
async def hardware_status() -> dict[str, Any]:
    """Check reachability of Unimus and the Git config repo."""
    unimus_status = await unimus.check_status()

    git_status: dict[str, Any]
    if not settings.git_config_repo:
        git_status = {"configured": False, "reason": "GIT_CONFIG_REPO not set"}
    else:
        git_status = {
            "configured": True,
            "repo": settings.git_config_repo,
            "branch": settings.git_config_branch,
            "local_path": settings.git_config_local_path,
        }

    return {"unimus": unimus_status, "git": git_status}


# ---------------------------------------------------------------------------
# Device list
# ---------------------------------------------------------------------------

@router.get("/devices")
async def list_devices(
    site: str | None = None,
    role: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Return physical devices from NetBox, enriched with management IP.
    Optionally filter by site slug, role slug, or status value.
    """
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]
    params: dict[str, Any] = {"limit": limit}
    if site:
        params["site"] = site
    if role:
        params["role"] = role
    if status:
        params["status"] = status

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(
                f"{settings.netbox_url}/api/dcim/devices/",
                params=params,
                headers=_nb_headers(),
            )
            r.raise_for_status()
            devices = r.json().get("results", [])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    return [_slim_device(d) for d in devices]


# ---------------------------------------------------------------------------
# Device detail
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}")
async def get_device(device_id: int) -> dict[str, Any]:
    """Return full NetBox device detail including all interfaces and IPs."""
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            dev_r, iface_r = await asyncio.gather(
                client.get(
                    f"{settings.netbox_url}/api/dcim/devices/{device_id}/",
                    headers=_nb_headers(),
                ),
                client.get(
                    f"{settings.netbox_url}/api/dcim/interfaces/",
                    params={"device_id": device_id, "limit": 100},
                    headers=_nb_headers(),
                ),
            )
            dev_r.raise_for_status()
            iface_r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    device    = dev_r.json()
    interfaces = iface_r.json().get("results", [])

    slim = _slim_device(device)
    slim["interfaces"] = [
        {
            "id":       i.get("id"),
            "name":     i.get("name"),
            "type":     (i.get("type") or {}).get("label", ""),
            "mgmt_only": i.get("mgmt_only", False),
            "enabled":  i.get("enabled", True),
            "mac":      i.get("mac_address", ""),
            "description": i.get("description", ""),
        }
        for i in interfaces
    ]
    return slim


# ---------------------------------------------------------------------------
# Backup (synchronous: Unimus → Git)
# ---------------------------------------------------------------------------

class BackupRequest(BaseModel):
    targets: list[Literal["unimus", "git"]] = ["unimus", "git"]
    """Which backends to archive to. Default: both."""


@router.post("/devices/{device_id}/backup")
async def backup_device(device_id: int, req: BackupRequest) -> dict[str, Any]:
    """
    Synchronously back up a device config via Unimus and/or commit to Git.

    Flow:
      1. Resolve management IP from NetBox
      2. Locate device in Unimus by management IP
      3. Trigger Unimus backup job and wait for completion
      4. Retrieve the latest config text from Unimus
      5. If 'git' is in targets: commit + push to the Git config repo

    Returns: { hostname, management_ip, unimus_device_id, git_ref,
               config_preview, timestamp }
    """
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]

    # Step 1 — get device from NetBox
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(
                f"{settings.netbox_url}/api/dcim/devices/{device_id}/",
                headers=_nb_headers(),
            )
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    device     = r.json()
    hostname   = device.get("name") or f"device-{device_id}"
    mgmt_ip    = _mgmt_ip_from_device(device)

    if not mgmt_ip:
        raise HTTPException(
            status_code=422,
            detail=f"No management IP found for device '{hostname}' in NetBox. "
                   "Set primary_ip or mark a management-only interface.",
        )

    result: dict[str, Any] = {
        "hostname":    hostname,
        "management_ip": mgmt_ip,
        "unimus_device_id": None,
        "git_ref":     None,
        "config_preview": None,
        "timestamp":   None,
        "warnings":    [],
    }

    config_text: str | None = None

    # Step 2–4 — Unimus backup
    if "unimus" in req.targets or "git" in req.targets:
        if not settings.unimus_url:
            result["warnings"].append("UNIMUS_URL not configured — skipping Unimus backup")
        else:
            unimus_device = await unimus.find_device_by_address(mgmt_ip)
            if not unimus_device:
                result["warnings"].append(
                    f"Device {mgmt_ip} not found in Unimus. "
                    "Ensure it is added to Unimus and reachable."
                )
            else:
                uid = unimus_device.get("id")
                result["unimus_device_id"] = uid

                # Trigger synchronous backup
                try:
                    job = await unimus.trigger_backup([uid])
                    job_id = job.get("id") or job.get("jobId")

                    # Poll until done (synchronous — up to 2 min)
                    if job_id:
                        for _ in range(24):   # 24 × 5s = 2 min max
                            await asyncio.sleep(5)
                            status_obj = await unimus.poll_job(job_id)
                            state = status_obj.get("status", "").upper()
                            if state in ("FINISHED", "COMPLETED", "SUCCESS"):
                                break
                            if state in ("FAILED", "ERROR", "ABORTED"):
                                result["warnings"].append(f"Unimus backup job {job_id} ended with status: {state}")
                                break

                    # Retrieve config text
                    backup = await unimus.get_latest_backup(uid)
                    if backup:
                        config_text = backup.get("content_text", "")
                        result["timestamp"] = backup.get("created")
                        result["config_preview"] = (config_text or "")[:500]
                    else:
                        result["warnings"].append("Unimus backup triggered but no backup found afterward")

                except Exception as exc:
                    result["warnings"].append(f"Unimus backup error: {exc}")
                    log.warning("Unimus backup failed for %s: %s", hostname, exc)

    # Step 5 — Git commit
    if "git" in req.targets and config_text:
        if not settings.git_config_repo:
            result["warnings"].append("GIT_CONFIG_REPO not configured — skipping Git commit")
        else:
            try:
                sha = await asyncio.to_thread(git.write_config, hostname, config_text)
                result["git_ref"] = sha
            except Exception as exc:
                result["warnings"].append(f"Git commit failed: {exc}")
                log.warning("Git commit failed for %s: %s", hostname, exc)

    return result


# ---------------------------------------------------------------------------
# Config history (Git)
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}/configs")
async def config_history(device_id: int, limit: int = 30) -> dict[str, Any]:
    """
    Return git log history for this device's config file.
    Requires GIT_CONFIG_REPO to be configured and cloned.
    """
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]

    # Resolve hostname
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(
                f"{settings.netbox_url}/api/dcim/devices/{device_id}/",
                headers=_nb_headers(),
            )
            r.raise_for_status()
        hostname = r.json().get("name") or f"device-{device_id}"
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    try:
        history = await asyncio.to_thread(git.config_history, hostname, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Git error: {exc}")

    return {"hostname": hostname, "history": history}


@router.get("/devices/{device_id}/configs/{ref}")
async def config_at_ref(device_id: int, ref: str) -> dict[str, Any]:
    """Return config file contents at a specific git commit ref."""
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(
                f"{settings.netbox_url}/api/dcim/devices/{device_id}/",
                headers=_nb_headers(),
            )
            r.raise_for_status()
        hostname = r.json().get("name") or f"device-{device_id}"
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    content = await asyncio.to_thread(git.read_config_at_ref, hostname, ref)
    if content is None:
        raise HTTPException(status_code=404, detail=f"No config found for {hostname} at ref {ref}")

    return {"hostname": hostname, "ref": ref, "content": content}


# ---------------------------------------------------------------------------
# Provision — push golden config
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    source: Literal["git", "unimus"]
    """Which source of truth to use for the golden config."""
    git_ref: str | None = None
    """Specific git commit SHA to use (default: HEAD / latest)."""
    note: str = ""
    """Optional human-readable note attached to the Unimus push job."""


@router.post("/devices/{device_id}/provision")
async def provision_device(device_id: int, req: ProvisionRequest) -> dict[str, Any]:
    """
    Push a golden config to a device via Unimus Pro.

    Source of truth options:
      source='git'    — read config from Git repo (req.git_ref selects version;
                        defaults to HEAD / latest committed config)
      source='unimus' — use the latest backup stored in Unimus as the golden config

    The config is then pushed to the live device via Unimus Pro's
    push-config job endpoint.
    """
    from api.services.netbox.client import _nb_headers, TIMEOUT  # type: ignore[attr-defined]

    # Resolve device name + management IP from NetBox
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(
                f"{settings.netbox_url}/api/dcim/devices/{device_id}/",
                headers=_nb_headers(),
            )
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"NetBox error: {exc}")

    device   = r.json()
    hostname = device.get("name") or f"device-{device_id}"
    mgmt_ip  = _mgmt_ip_from_device(device)

    if not mgmt_ip:
        raise HTTPException(
            status_code=422,
            detail=f"No management IP for '{hostname}' in NetBox",
        )

    if not settings.unimus_url:
        raise HTTPException(status_code=503, detail="UNIMUS_URL not configured")

    # Locate device in Unimus
    unimus_device = await unimus.find_device_by_address(mgmt_ip)
    if not unimus_device:
        raise HTTPException(
            status_code=404,
            detail=f"Device {mgmt_ip} ({hostname}) not found in Unimus",
        )
    uid = unimus_device.get("id")

    # Retrieve config from selected source
    config_text: str | None = None
    source_label: str

    if req.source == "git":
        if not settings.git_config_repo:
            raise HTTPException(status_code=503, detail="GIT_CONFIG_REPO not configured")
        if req.git_ref:
            config_text = await asyncio.to_thread(git.read_config_at_ref, hostname, req.git_ref)
            source_label = f"git:{req.git_ref[:8]}"
        else:
            config_text = await asyncio.to_thread(git.read_config, hostname)
            source_label = "git:HEAD"

        if config_text is None:
            raise HTTPException(
                status_code=404,
                detail=f"No config found in Git for '{hostname}'"
                       + (f" at ref {req.git_ref}" if req.git_ref else ""),
            )

    else:  # source == "unimus"
        backup = await unimus.get_latest_backup(uid)
        if not backup:
            raise HTTPException(
                status_code=404,
                detail=f"No Unimus backup found for '{hostname}' ({mgmt_ip})",
            )
        config_text = backup.get("content_text", "")
        source_label = f"unimus:{backup.get('id', '')[:8]}"

    if not config_text:
        raise HTTPException(status_code=422, detail="Config text is empty — refusing to push")

    # Push via Unimus Pro
    note = req.note or f"Direttore golden-config push from {source_label}"
    try:
        job = await unimus.push_config(uid, config_text, note=note)
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.json()
        except Exception:
            body = exc.response.text
        raise HTTPException(status_code=502, detail=f"Unimus push failed: {body}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unimus push error: {exc}")

    return {
        "hostname":     hostname,
        "management_ip": mgmt_ip,
        "source":       req.source,
        "source_label": source_label,
        "unimus_job":   job,
        "note":         note,
    }
