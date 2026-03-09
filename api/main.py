"""Direttore FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.db import init_db
from api.routes import proxmox, reservations, inventory

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
# Show our own ERROR logs even when uvicorn is set to WARNING
logging.getLogger("api").setLevel(logging.DEBUG)


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


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.proxmox_mock}
