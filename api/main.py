"""Direttore FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import init_db, get_db
from api.routes import proxmox, reservations, inventory, topology
from api.services.proxmox import client as px_client
from api.services.netbox import client as nb_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
app.include_router(topology.router)


@app.get("/healthz")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Detailed health check endpoint.
    Verifies connectivity to Database, Proxmox, and NetBox.
    """
    # 1. Check Database
    db_status = "ok"
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    # 2. Check Proxmox (Mock or Live)
    proxmox_status = px_client.check_status()

    # 3. Check NetBox
    netbox_status = await nb_client.check_status()

    # Overall summary status
    is_healthy = (
        db_status == "ok" and 
        proxmox_status["status"] != "offline" and 
        netbox_status["reachable"]
    )

    return {
        "status": "ok" if is_healthy else "degraded",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "version": "0.1.0",
        "components": {
            "database": {
                "status": "online" if db_status == "ok" else "offline",
                "details": db_status if db_status != "ok" else "SQLite connected"
            },
            "proxmox": {
                "status": proxmox_status["status"],
                "host": proxmox_status["host"],
                "details": f"{proxmox_status.get('nodes_count', 0)} nodes available" if proxmox_status["status"] != "offline" else proxmox_status.get("error")
            },
            "netbox": {
                "status": "online" if netbox_status["reachable"] else "offline",
                "url": netbox_status.get("url"),
                "version": netbox_status.get("version"),
                "details": netbox_status.get("reason") if not netbox_status["reachable"] else "API reachable"
            }
        },
        "mock_mode": settings.proxmox_mock
    }
