"""RestBackend — delegates to a remote clab-api-server HTTP REST API."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from api.services.containerlab._base import ClabBackend

log = logging.getLogger(__name__)


def _settings():
    from api.config import settings
    return settings


class RestBackend(ClabBackend):

    def _base(self) -> str:
        return _settings().clab_api_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        s = _settings()
        h: dict[str, str] = {"Content-Type": "application/json"}
        if s.clab_api_token:
            h["Authorization"] = f"Bearer {s.clab_api_token}"
        elif s.clab_api_username and s.clab_api_password:
            creds = base64.b64encode(
                f"{s.clab_api_username}:{s.clab_api_password}".encode()
            ).decode()
            h["Authorization"] = f"Basic {creds}"
        return h

    def _verify(self) -> bool:
        return _settings().clab_api_verify_ssl

    def _topo_path(self, filename: str) -> str:
        return str(Path(_settings().clab_topo_dir) / filename)

    async def get_status(self) -> dict[str, Any]:
        s = _settings()
        if not s.clab_api_url:
            return {"ok": False, "mode": "rest", "error": "CLAB_API_URL not configured"}
        try:
            async with httpx.AsyncClient(timeout=10, verify=self._verify()) as c:
                r = await c.get(f"{self._base()}/api/v1/version", headers=self._headers())
            r.raise_for_status()
            return {"ok": True, "mode": "rest", "url": s.clab_api_url, "version": r.json()}
        except Exception as exc:
            return {"ok": False, "mode": "rest", "url": s.clab_api_url, "error": str(exc)}

    async def list_labs(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30, verify=self._verify()) as c:
            r = await c.get(f"{self._base()}/api/v1/labs", headers=self._headers())
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("labs", [])

    async def inspect_lab(self, name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, verify=self._verify()) as c:
            r = await c.get(f"{self._base()}/api/v1/labs/{name}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def deploy(self, topo_file: str, reconfigure: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120, verify=self._verify()) as c:
            r = await c.post(
                f"{self._base()}/api/v1/labs",
                headers=self._headers(),
                json={"topoFile": self._topo_path(topo_file), "reconfigure": reconfigure},
            )
        r.raise_for_status()
        return r.json()

    async def deploy_stream(self, topo_file: str, reconfigure: bool = True):
        """Stream deployment output line-by-line from clab-api-server.

        Falls back to two synthetic events if the server does not support
        chunked streaming (older clab-api-server versions).
        """
        url = f"{self._base()}/api/v1/labs"
        payload = {"topoFile": self._topo_path(topo_file), "reconfigure": reconfigure}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=30, read=None, write=None, pool=None),
                verify=self._verify(),
            ) as c:
                async with c.stream(
                    "POST", url, headers=self._headers(), json=payload
                ) as response:
                    response.raise_for_status()
                    streamed_any = False
                    async for line in response.aiter_lines():
                        if line:
                            streamed_any = True
                            yield {"type": "log", "line": line + "\n"}
                    if not streamed_any:
                        yield {
                            "type": "log",
                            "line": "[REST backend: no streaming output — deployment complete]\n",
                        }
                    yield {"type": "success", "message": "Deployed successfully"}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    async def destroy(self, lab_name: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60, verify=self._verify()) as c:
            r = await c.delete(
                f"{self._base()}/api/v1/labs/{lab_name}",
                headers=self._headers(),
            )
        r.raise_for_status()
        return {"destroyed": True, "lab_name": lab_name}

    async def validate(self, topo_file: str) -> dict[str, Any]:
        return {
            "valid": None,
            "output": "Validation not supported for REST backend — deploy will catch errors.",
        }

    async def node_action(
        self, lab_name: str, node_name: str, action: str
    ) -> dict[str, Any]:
        return {"ok": False, "error": "Node actions are not supported for REST backend."}

    async def node_console(self, ws: Any, lab_name: str, node_name: str) -> None:
        await ws.send_bytes(b"\r\nNode console is not supported for REST backend.\r\n")
