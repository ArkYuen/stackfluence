"""
Link management API — create and manage tracked wrapper links.

Security:
  - Requires SECRET API key (sf_sec_...)
  - All queries scoped to the key's organization (cannot see other orgs' links)
  - Rate limited per API key
  - No organization_id in request body — derived from the API key
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Link
from app.middleware.auth import AuthContext, require_secret_key
from app.middleware.rate_limit import rate_limit_api_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/links", tags=["links"])


class CreateLinkRequest(BaseModel):
    creator_id: UUID
    campaign_id: UUID
    creator_handle: str
    campaign_slug: str
    asset_slug: str | None = None
    destination_url: str


class LinkResponse(BaseModel):
    id: UUID
    wrapper_url: str
    destination_url: str
    creator_handle: str
    campaign_slug: str
    asset_slug: str | None
    status: str

    model_config = {"from_attributes": True}


def _validate_destination_url(url: str):
    """Prevent open redirect attacks — only allow http/https destinations."""
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="destination_url must start with https:// or http://")
    # Block internal/private URLs
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16."]
    for b in blocked:
        if b in url.split("//")[1].split("/")[0]:
            raise HTTPException(status_code=400, detail="destination_url cannot point to internal addresses")


@router.post("", response_model=LinkResponse, status_code=201)
async def create_link(
    req: CreateLinkRequest,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    settings = get_settings()

    # Validate destination URL
    _validate_destination_url(req.destination_url)

    # Check for duplicate route
    stmt = select(Link).where(
        Link.creator_handle == req.creator_handle,
        Link.campaign_slug == req.campaign_slug,
        Link.asset_slug == req.asset_slug,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Link with this route already exists")

    # Organization comes from the API key, not the request body
    link = Link(
        organization_id=auth.organization_id,
        creator_id=req.creator_id,
        campaign_id=req.campaign_id,
        creator_handle=req.creator_handle,
        campaign_slug=req.campaign_slug,
        asset_slug=req.asset_slug,
        destination_url=str(req.destination_url),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    path = f"/c/{link.creator_handle}/{link.campaign_slug}"
    if link.asset_slug:
        path += f"/{link.asset_slug}"
    wrapper_url = f"{settings.base_url}{path}"

    logger.info("link_created", link_id=str(link.id), wrapper_url=wrapper_url)

    return LinkResponse(
        id=link.id, wrapper_url=wrapper_url, destination_url=link.destination_url,
        creator_handle=link.creator_handle, campaign_slug=link.campaign_slug,
        asset_slug=link.asset_slug, status=link.status,
    )


@router.get("", response_model=list[LinkResponse])
async def list_links(
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    """List links — automatically scoped to the API key's organization."""
    rate_limit_api_key(str(auth.key_id))
    settings = get_settings()

    # Only returns links for the authenticated org — no cross-org leakage
    stmt = (
        select(Link)
        .where(Link.organization_id == auth.organization_id)
        .order_by(Link.created_at.desc())
    )
    result = await db.execute(stmt)
    links = result.scalars().all()

    responses = []
    for link in links:
        path = f"/c/{link.creator_handle}/{link.campaign_slug}"
        if link.asset_slug:
            path += f"/{link.asset_slug}"
        responses.append(LinkResponse(
            id=link.id, wrapper_url=f"{settings.base_url}{path}",
            destination_url=link.destination_url,
            creator_handle=link.creator_handle, campaign_slug=link.campaign_slug,
            asset_slug=link.asset_slug, status=link.status,
        ))
    return responses


@router.patch("/{link_id}/pause")
async def pause_link(
    link_id: UUID,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    stmt = select(Link).where(Link.id == link_id, Link.organization_id == auth.organization_id)
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.status = "paused"
    await db.commit()
    return {"status": "paused"}


@router.patch("/{link_id}/activate")
async def activate_link(
    link_id: UUID,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    stmt = select(Link).where(Link.id == link_id, Link.organization_id == auth.organization_id)
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.status = "active"
    await db.commit()
    return {"status": "active"}
