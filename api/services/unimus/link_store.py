"""Persistent mapping from NetBox device IDs to Unimus device addresses.

Stored as a JSON file alongside the running process. This is the lightweight
alternative to a full database migration — it only needs to store one string
per device and persists across restarts without any ORM machinery.

File location: <GIT_CONFIG_LOCAL_PATH>/../unimus_links.json
             (falls back to ./unimus_links.json if git path is not configured)
"""

import json
import logging
from pathlib import Path
from typing import Any

from api.config import settings

log = logging.getLogger(__name__)


def _link_file() -> Path:
    if settings.git_config_local_path:
        base = Path(settings.git_config_local_path).parent
    else:
        base = Path(".")
    return base / "unimus_links.json"


def _load() -> dict[str, str]:
    f = _link_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not read unimus links file %s: %s", f, exc)
    return {}


def _save(links: dict[str, str]) -> None:
    f = _link_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(links, indent=2), encoding="utf-8")
    log.debug("Saved %d unimus link(s) to %s", len(links), f)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_link(netbox_device_id: int | str) -> str | None:
    """Return the manually linked Unimus address for a NetBox device, or None."""
    return _load().get(str(netbox_device_id))


def set_link(netbox_device_id: int | str, unimus_address: str) -> None:
    """Persist a NetBox device → Unimus address mapping."""
    links = _load()
    links[str(netbox_device_id)] = unimus_address
    _save(links)
    log.info("Linked NetBox device %s → Unimus address '%s'", netbox_device_id, unimus_address)


def delete_link(netbox_device_id: int | str) -> bool:
    """Remove a mapping.  Returns True if it existed."""
    links = _load()
    key = str(netbox_device_id)
    if key in links:
        del links[key]
        _save(links)
        log.info("Removed Unimus link for NetBox device %s", netbox_device_id)
        return True
    return False


def all_links() -> dict[str, str]:
    """Return {netbox_device_id: unimus_address} for all linked devices."""
    return _load()
