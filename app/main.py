"""
Stackfluence — influencer measurement infrastructure.
Main application entry point.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.redirect import router as redirect_router
from app.api.collector import router as collector_router
from app.api.events import router as events_router
from app.api.links import router as links_router
from app.api.quick_link import router as quick_link_router
from app.api.admin import router as admin_router
from app.api.dashboard import router as dashboard_router
from app.api.demo import router as demo_router
from app.api.pixel import router as pixel_router
from app.config import get_settings

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer() if get_settings().debug else structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("stackfluence_starting", base_url=get_settings().base_url)
    yield
    logger.info("stackfluence_shutting_down")


app = FastAPI(
    title="Stackfluence",
    description="Influencer measurement infrastructure — from click to conversion, cleanly.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().debug else None,
    redoc_url="/redoc" if get_settings().debug else None,
    openapi_url="/openapi.json" if get_settings().debug else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---
app.include_router(redirect_router)
app.include_router(collector_router)
app.include_router(events_router)
app.include_router(links_router)
app.include_router(quick_link_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(demo_router)
app.include_router(pixel_router)

# --- Static files ---
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stackfluence", "version": "0.2.0"}
