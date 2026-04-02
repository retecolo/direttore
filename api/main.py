"""Direttore FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.db import init_db
from api.routes import proxmox, reservations, inventory, hardware, containerlab

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
# Show our own ERROR logs even when uvicorn is set to WARNING
logging.getLogger("api").setLevel(logging.DEBUG)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info(
        "Direttore API ready | mock=%s | cors_origins=%s",
        settings.proxmox_mock,
        settings.cors_origins,
    )
    yield


app = FastAPI(
    title="Direttore API",
    description="Lab infrastructure provisioning and reservation platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(proxmox.router)
app.include_router(reservations.router)
app.include_router(inventory.router)
app.include_router(hardware.router)
app.include_router(containerlab.router)


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.proxmox_mock}


@app.get("/api")
@app.get("/api/")
def api_root() -> dict:
    """Return a summary of available API route groups."""
    return {
        "status": "ok",
        "routes": {
            "proxmox":        "/api/proxmox/nodes",
            "reservations":   "/api/reservations/",
            "inventory":      "/api/inventory/netbox-status",
            "hardware":       "/api/hardware/devices",
            "containerlab":   "/api/containerlab/status",
            "docs":           "/docs",
            "health":         "/healthz",
        },
    }

