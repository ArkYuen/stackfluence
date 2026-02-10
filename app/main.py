"""
Stackfluence — influencer measurement infrastructure.
Main application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.redirect import router as redirect_router
from app.api.collector import router as collector_router
from app.api.events import router as events_router
from app.api.links import router as links_router
from app.api.quick_link import router as quick_link_router
from app.api.admin import router as admin_router
from app.middleware.security import SecurityHeadersMiddleware
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

# Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# CORS — tighten to your actual domains in production
ALLOWED_ORIGINS = ["*"] if get_settings().debug else [
    "https://stackfluence.com",
    "https://app.stackfluence.com",
    "https://www.stackfluence.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# --- Routes ---
app.include_router(redirect_router)
app.include_router(collector_router)
app.include_router(events_router)
app.include_router(links_router)
app.include_router(quick_link_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stackfluence", "version": "0.2.0"}
