"""
Demo link wrapping — public endpoint for the marketing site.

POST /demo/wrap
  - No auth required
  - Rate-limited: 10 links per IP per hour
  - Creates a real Link row under a demo org so /c/ redirect works
  - Returns the wrapped URL

GET /demo/admin/links  (admin only — your eyes only)
  - Lists all demo links with click counts
  - Protected by X-API-Key (your secret key)
"""

import hashlib
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Campaign, Creator, Link, Organization
from app.models.demo import DemoLink, _generate_slug
from app.middleware.auth import AuthContext, require_secret_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/demo", tags=["demo"])


# ---------------------------------------------------------------------------
# In-memory rate limiter for demo endpoint (simple, resets on restart)
# ---------------------------------------------------------------------------

_demo_rate_limits: dict[str, list[float]] = defaultdict(list)
DEMO_RATE_LIMIT = 10        # max links per IP
DEMO_RATE_WINDOW = 3600     # per hour

# Demo org/creator/campaign constants
DEMO_ORG_SLUG = "wrpper-demo"
DEMO_CREATOR_HANDLE = "demo"
DEMO_CAMPAIGN_SLUG = "website-demo"


def _check_demo_rate_limit(ip: str):
    """Simple in-memory rate limiter. 10 demo links per IP per hour."""
    now = time.time()
    window_start = now - DEMO_RATE_WINDOW

    # Clean old entries
    _demo_rate_limits[ip] = [t for t in _demo_rate_limits[ip] if t > window_start]

    if len(_demo_rate_limits[ip]) >= DEMO_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {DEMO_RATE_LIMIT} demo links per hour.",
        )

    _demo_rate_limits[ip].append(now)


def _get_real_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",")]
        for ip in ips:
            if not ip.startswith(("10.", "172.16.", "192.168.", "127.", "::1")):
                return ip
        return ips[0]
    return request.client.host if request.client else "unknown"


def _validate_url(url: str) -> str:
    """Validate and normalize the URL."""
    url = url.strip()

    # Auto-add https:// if missing
    if not url.startswith(("https://", "http://")):
        url = "https://" + url

    # Block internal/private IPs
    try:
        host = url.split("//")[1].split("/")[0].split(":")[0]
    except (IndexError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16."]
    for b in blocked:
        if host.startswith(b) or host == b.rstrip("."):
            raise HTTPException(status_code=400, detail="Cannot wrap internal URLs")

    if len(url) > 2048:
        raise HTTPException(status_code=400, detail="URL too long (max 2048 chars)")

    return url


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DemoWrapRequest(BaseModel):
    url: str


class DemoWrapResponse(BaseModel):
    wrapped_url: str
    original_url: str
    slug: str
    expires_in_hours: int = 72


class DemoLinkAdmin(BaseModel):
    id: str
    slug: str
    original_url: str
    wrapped_url: str
    creator_ip: str | None
    click_count: int
    is_active: bool
    created_at: datetime
    expires_at: datetime | None


class DemoAdminResponse(BaseModel):
    total: int
    links: list[DemoLinkAdmin]


# ---------------------------------------------------------------------------
# Helpers — ensure demo org/creator/campaign exist
# ---------------------------------------------------------------------------

async def _ensure_demo_org(db: AsyncSession) -> Organization:
    """Get or create the demo organization."""
    stmt = select(Organization).where(Organization.slug == DEMO_ORG_SLUG)
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()

    if not org:
        org = Organization(
            name="Wrpper Demo",
            slug=DEMO_ORG_SLUG,
        )
        db.add(org)
        await db.flush()
        logger.info("demo_org_created", slug=DEMO_ORG_SLUG)

    return org


async def _ensure_demo_creator(db: AsyncSession) -> Creator:
    """Get or create the demo creator."""
    stmt = select(Creator).where(Creator.handle == DEMO_CREATOR_HANDLE)
    result = await db.execute(stmt)
    creator = result.scalar_one_or_none()

    if not creator:
        creator = Creator(
            handle=DEMO_CREATOR_HANDLE,
            display_name="Demo User",
            platform="website",
        )
        db.add(creator)
        await db.flush()
        logger.info("demo_creator_created", handle=DEMO_CREATOR_HANDLE)

    return creator


async def _ensure_demo_campaign(db: AsyncSession, org_id: UUID) -> Campaign:
    """Get or create the demo campaign."""
    stmt = select(Campaign).where(
        Campaign.organization_id == org_id,
        Campaign.slug == DEMO_CAMPAIGN_SLUG,
    )
    result = await db.execute(stmt)
    campaign = result.scalar_one_or_none()

    if not campaign:
        campaign = Campaign(
            organization_id=org_id,
            name="Website Demo",
            slug=DEMO_CAMPAIGN_SLUG,
        )
        db.add(campaign)
        await db.flush()
        logger.info("demo_campaign_created", slug=DEMO_CAMPAIGN_SLUG)

    return campaign


# ---------------------------------------------------------------------------
# Public endpoint — POST /demo/wrap
# ---------------------------------------------------------------------------

@router.post("/wrap", response_model=DemoWrapResponse, status_code=201)
async def wrap_demo_link(
    req: DemoWrapRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint for the marketing site wrap bar.
    No auth required — rate-limited by IP.
    """
    settings = get_settings()
    ip = _get_real_ip(request)
    ua = request.headers.get("user-agent", "")

    # Rate limit
    _check_demo_rate_limit(ip)

    # Validate URL
    original_url = _validate_url(req.url)

    # Ensure demo infrastructure exists
    org = await _ensure_demo_org(db)
    creator = await _ensure_demo_creator(db)
    campaign = await _ensure_demo_campaign(db, org.id)

    # Generate unique slug
    for _ in range(10):  # retry on collision
        slug = _generate_slug(7)
        existing = await db.execute(
            select(DemoLink).where(DemoLink.slug == slug)
        )
        if not existing.scalar_one_or_none():
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique slug")

    # Check if this exact URL was already wrapped by this IP recently (dedup)
    fingerprint = hashlib.sha256(f"{ip}:{ua}".encode()).hexdigest()
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)

    stmt = select(DemoLink).where(
        DemoLink.creator_fingerprint == fingerprint,
        DemoLink.original_url == original_url,
        DemoLink.created_at > recent_cutoff,
    )
    result = await db.execute(stmt)
    existing_demo = result.scalar_one_or_none()

    if existing_demo:
        # Return the existing one instead of creating a duplicate
        return DemoWrapResponse(
            wrapped_url=existing_demo.wrapped_url,
            original_url=existing_demo.original_url,
            slug=existing_demo.slug,
            expires_in_hours=72,
        )

    # Create the real Link row (so /c/ redirect works)
    link = Link(
        organization_id=org.id,
        creator_id=creator.id,
        campaign_id=campaign.id,
        creator_handle=DEMO_CREATOR_HANDLE,
        campaign_slug=DEMO_CAMPAIGN_SLUG,
        asset_slug=slug,
        destination_url=original_url,
        metadata_={"source": "demo_website", "creator_ip_hash": fingerprint[:16]},
    )
    db.add(link)
    await db.flush()

    # Build the wrapped URL
    wrapper_path = f"/c/{DEMO_CREATOR_HANDLE}/{DEMO_CAMPAIGN_SLUG}/{slug}"
    wrapped_url = f"{settings.base_url}{wrapper_path}"

    # Create the DemoLink tracking row
    demo_link = DemoLink(
        slug=slug,
        original_url=original_url,
        wrapped_url=wrapped_url,
        link_id=link.id,
        creator_ip=ip,
        creator_user_agent=ua[:500] if ua else None,
        creator_fingerprint=fingerprint,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    db.add(demo_link)
    await db.commit()

    logger.info("demo_link_created",
                slug=slug,
                original_url=original_url[:100],
                ip=ip,
                wrapped_url=wrapped_url)

    return DemoWrapResponse(
        wrapped_url=wrapped_url,
        original_url=original_url,
        slug=slug,
        expires_in_hours=72,
    )


# ---------------------------------------------------------------------------
# Admin endpoint — GET /demo/admin/links (your eyes only)
# ---------------------------------------------------------------------------

@router.get("/admin/links", response_model=DemoAdminResponse)
async def list_demo_links(
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    active_only: bool = False,
):
    """
    List all demo links with metadata. Admin only.
    """
    stmt = select(DemoLink).order_by(DemoLink.created_at.desc())

    if active_only:
        stmt = stmt.where(DemoLink.is_active == True)

    # Get total count
    count_stmt = select(func.count()).select_from(DemoLink)
    if active_only:
        count_stmt = count_stmt.where(DemoLink.is_active == True)
    total = (await db.execute(count_stmt)).scalar()

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    links = result.scalars().all()

    return DemoAdminResponse(
        total=total,
        links=[
            DemoLinkAdmin(
                id=str(link.id),
                slug=link.slug,
                original_url=link.original_url,
                wrapped_url=link.wrapped_url,
                creator_ip=link.creator_ip,
                click_count=link.click_count,
                is_active=link.is_active,
                created_at=link.created_at,
                expires_at=link.expires_at,
            )
            for link in links
        ],
    )


# ---------------------------------------------------------------------------
# Admin endpoint — DELETE /demo/admin/links/{slug} (deactivate)
# ---------------------------------------------------------------------------

@router.delete("/admin/links/{slug}")
async def deactivate_demo_link(
    slug: str,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a demo link (also deactivates the underlying Link)."""
    stmt = select(DemoLink).where(DemoLink.slug == slug)
    result = await db.execute(stmt)
    demo_link = result.scalar_one_or_none()

    if not demo_link:
        raise HTTPException(status_code=404, detail="Demo link not found")

    demo_link.is_active = False

    # Also deactivate the real link
    await db.execute(
        update(Link).where(Link.id == demo_link.link_id).values(status="paused")
    )

    await db.commit()
    logger.info("demo_link_deactivated", slug=slug)

    return {"status": "deactivated", "slug": slug}
