"""
Pixel configuration management endpoints.
Agencies configure their Meta/TikTok/GA4 pixels here.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.tables import PixelConfig
from app.middleware.auth import AuthContext, require_auth, enforce_org_scope

router = APIRouter(prefix="/v1/pixels", tags=["pixel-settings"])

VALID_PLATFORMS = {"meta", "tiktok", "ga4", "google_ads", "snapchat", "linkedin", "reddit", "pinterest"}


class PixelConfigCreate(BaseModel):
    organization_id: UUID
    link_id: UUID | None = None
    platform: str
    pixel_id: str
    access_token: str | None = None
    test_event_code: str | None = None
    enabled: bool = True


class PixelConfigUpdate(BaseModel):
    pixel_id: str | None = None
    access_token: str | None = None
    test_event_code: str | None = None
    enabled: bool | None = None


@router.get("/{org_id}")
async def list_pixel_configs(
    org_id: UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    enforce_org_scope(auth, org_id)
    stmt = select(PixelConfig).where(PixelConfig.organization_id == org_id)
    result = await db.execute(stmt)
    configs = result.scalars().all()
    return [{"id": str(c.id), "platform": c.platform, "pixel_id": c.pixel_id,
             "link_id": str(c.link_id) if c.link_id else None,
             "enabled": c.enabled, "has_token": bool(c.access_token)} for c in configs]


@router.post("/", status_code=201)
async def create_pixel_config(
    payload: PixelConfigCreate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    enforce_org_scope(auth, payload.organization_id)
    if payload.platform not in VALID_PLATFORMS:
        raise HTTPException(400, f"Platform must be one of: {', '.join(VALID_PLATFORMS)}")
    config = PixelConfig(**payload.model_dump())
    db.add(config)
    await db.commit()
    return {"id": str(config.id), "status": "created"}


@router.patch("/{config_id}")
async def update_pixel_config(
    config_id: UUID,
    payload: PixelConfigUpdate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PixelConfig).where(PixelConfig.id == config_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Config not found")
    enforce_org_scope(auth, config.organization_id)
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(config, k, v)
    await db.commit()
    return {"status": "updated"}


@router.delete("/{config_id}", status_code=204)
async def delete_pixel_config(
    config_id: UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PixelConfig).where(PixelConfig.id == config_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, "Config not found")
    enforce_org_scope(auth, config.organization_id)
    await db.delete(config)
    await db.commit()
