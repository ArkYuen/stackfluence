"""
Quick link creation — the simple advertiser-facing endpoint.

POST /v1/links/quick

Input:
  {
    "destination_url": "https://mybrand.com/summer-collection",
    "creator": "emma",
    "campaign": "summer-drop"
  }

Output:
  {
    "wrapper_url": "https://stackfluence.com/c/emma/summer-drop",
    "destination_url": "https://mybrand.com/summer-collection",
    "creator": "emma",
    "campaign": "summer-drop",
    "status": "active"
  }

The API key identifies the org. Creator and campaign records are
auto-created if they don't exist. No UUIDs, no complexity.
"""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Campaign, Creator, Link
from app.middleware.auth import AuthContext, require_secret_key
from app.middleware.rate_limit import rate_limit_api_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/links", tags=["links"])


# --- Schemas ---

class QuickLinkRequest(BaseModel):
    destination_url: str
    creator: str
    campaign: str
    asset: str | None = None  # optional sub-asset


class QuickLinkResponse(BaseModel):
    wrapper_url: str
    destination_url: str
    creator: str
    campaign: str
    asset: str | None = None
    status: str


# --- Helpers ---

def _slugify(text: str) -> str:
    """Turn user input into a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\-_]", "-", text)  # replace non-alphanumeric
    text = re.sub(r"-+", "-", text)  # collapse multiple dashes
    text = text.strip("-")
    return text


def _validate_destination_url(url: str):
    """Prevent open redirect attacks."""
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="destination_url must start with https:// or http://")
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16."]
    host = url.split("//")[1].split("/")[0].split(":")[0]
    for b in blocked:
        if host.startswith(b) or host == b.rstrip("."):
            raise HTTPException(status_code=400, detail="destination_url cannot point to internal addresses")


# --- Endpoint ---

@router.post("/quick", response_model=QuickLinkResponse, status_code=201)
async def create_quick_link(
    req: QuickLinkRequest,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a tracked link with just a URL, creator name, and campaign name.

    Auto-creates creator and campaign records if they don't exist.
    The API key determines which organization the link belongs to.
    """
    rate_limit_api_key(str(auth.key_id))
    settings = get_settings()

    # Validate
    _validate_destination_url(req.destination_url)

    creator_handle = _slugify(req.creator)
    campaign_slug = _slugify(req.campaign)
    asset_slug = _slugify(req.asset) if req.asset else None

    if not creator_handle:
        raise HTTPException(status_code=400, detail="Creator name is required")
    if not campaign_slug:
        raise HTTPException(status_code=400, detail="Campaign name is required")

    # --- Find or create creator ---
    stmt = select(Creator).where(Creator.handle == creator_handle)
    result = await db.execute(stmt)
    creator = result.scalar_one_or_none()

    if not creator:
        creator = Creator(
            handle=creator_handle,
            display_name=req.creator.strip(),  # preserve original casing for display
        )
        db.add(creator)
        await db.flush()
        logger.info("creator_auto_created", handle=creator_handle)

    # --- Find or create campaign ---
    stmt = select(Campaign).where(
        Campaign.organization_id == auth.organization_id,
        Campaign.slug == campaign_slug,
    )
    result = await db.execute(stmt)
    campaign = result.scalar_one_or_none()

    if not campaign:
        campaign = Campaign(
            organization_id=auth.organization_id,
            name=req.campaign.strip(),  # preserve original casing
            slug=campaign_slug,
        )
        db.add(campaign)
        await db.flush()
        logger.info("campaign_auto_created", slug=campaign_slug)

    # --- Find or create link ---
    stmt = select(Link).where(
        Link.creator_handle == creator_handle,
        Link.campaign_slug == campaign_slug,
        Link.asset_slug == asset_slug,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Link already exists — return it (idempotent)
        path = f"/c/{creator_handle}/{campaign_slug}"
        if asset_slug:
            path += f"/{asset_slug}"

        return QuickLinkResponse(
            wrapper_url=f"{settings.base_url}{path}",
            destination_url=existing.destination_url,
            creator=creator_handle,
            campaign=campaign_slug,
            asset=asset_slug,
            status=existing.status,
        )

    # --- Create the link ---
    link = Link(
        organization_id=auth.organization_id,
        creator_id=creator.id,
        campaign_id=campaign.id,
        creator_handle=creator_handle,
        campaign_slug=campaign_slug,
        asset_slug=asset_slug,
        destination_url=req.destination_url.strip(),
    )
    db.add(link)
    await db.commit()

    path = f"/c/{creator_handle}/{campaign_slug}"
    if asset_slug:
        path += f"/{asset_slug}"
    wrapper_url = f"{settings.base_url}{path}"

    logger.info("quick_link_created", wrapper_url=wrapper_url, creator=creator_handle,
                campaign=campaign_slug, org=str(auth.organization_id))

    return QuickLinkResponse(
        wrapper_url=wrapper_url,
        destination_url=req.destination_url.strip(),
        creator=creator_handle,
        campaign=campaign_slug,
        asset=asset_slug,
        status="active",
    )
