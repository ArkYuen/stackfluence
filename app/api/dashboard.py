"""
Dashboard API — Supabase-authenticated endpoints for the frontend.
All queries scoped by auth.organization_id.
"""

import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.supabase_auth import require_supabase_auth, SupabaseAuthContext
from app.models.database import get_db
from app.models.tables import ClickEvent, ConversionEvent, RefundEvent, Creator, Link, Organization
from app.middleware.supabase_auth import User

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _period_filter(org_id: str, days: int = 30):
    """Return a WHERE clause for org + last N days."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return and_(
        ClickEvent.organization_id == org_id,
        ClickEvent.created_at >= cutoff,
    )


def _prev_period_filter(org_id: str, days: int = 30):
    """Return a WHERE clause for the previous period (for pct change)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    prev_cutoff = now - datetime.timedelta(days=days * 2)
    return and_(
        ClickEvent.organization_id == org_id,
        ClickEvent.created_at >= prev_cutoff,
        ClickEvent.created_at < cutoff,
    )


@router.get("/summary")
async def dashboard_summary(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Total clicks, bots filtered, unique visitors, pct change vs previous period."""
    current = _period_filter(auth.organization_id, days)
    previous = _prev_period_filter(auth.organization_id, days)

    cur_result = await db.execute(
        select(
            func.count(ClickEvent.id).label("total_clicks"),
            func.count(ClickEvent.id).filter(ClickEvent.bot_blocked == True).label("bots_filtered"),
            func.count(func.distinct(ClickEvent.ip_address)).label("unique_visitors"),
        ).where(current)
    )
    cur = cur_result.one()

    prev_result = await db.execute(
        select(func.count(ClickEvent.id).label("total_clicks")).where(previous)
    )
    prev_total = prev_result.scalar_one()

    pct_change = (
        round((cur.total_clicks - prev_total) / prev_total * 100, 1)
        if prev_total > 0
        else None
    )

    return {
        "total_clicks": cur.total_clicks,
        "bots_filtered": cur.bots_filtered,
        "unique_visitors": cur.unique_visitors,
        "pct_change": pct_change,
        "period_days": days,
    }


@router.get("/platforms")
async def dashboard_platforms(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Clicks grouped by source_platform."""
    result = await db.execute(
        select(
            ClickEvent.source_platform,
            func.count(ClickEvent.id).label("clicks"),
        )
        .where(_period_filter(auth.organization_id, days))
        .group_by(ClickEvent.source_platform)
        .order_by(func.count(ClickEvent.id).desc())
    )
    return [{"platform": row.source_platform, "clicks": row.clicks} for row in result.all()]


@router.get("/devices")
async def dashboard_devices(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Clicks grouped by device_class."""
    result = await db.execute(
        select(
            ClickEvent.device_class,
            func.count(ClickEvent.id).label("clicks"),
        )
        .where(_period_filter(auth.organization_id, days))
        .group_by(ClickEvent.device_class)
        .order_by(func.count(ClickEvent.id).desc())
    )
    return [{"device": row.device_class, "clicks": row.clicks} for row in result.all()]


@router.get("/geo")
async def dashboard_geo(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Clicks grouped by country_code, top 10."""
    result = await db.execute(
        select(
            ClickEvent.country_code,
            func.count(ClickEvent.id).label("clicks"),
        )
        .where(_period_filter(auth.organization_id, days))
        .group_by(ClickEvent.country_code)
        .order_by(func.count(ClickEvent.id).desc())
        .limit(10)
    )
    return [{"country": row.country_code, "clicks": row.clicks} for row in result.all()]


@router.get("/clicks")
async def dashboard_clicks(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    platform: Optional[str] = None,
    creator: Optional[str] = None,
):
    """Paginated recent clicks table with optional platform/creator filters."""
    conditions = _period_filter(auth.organization_id, days)

    query = select(
        ClickEvent.id,
        ClickEvent.click_id,
        ClickEvent.created_at,
        ClickEvent.source_platform,
        ClickEvent.device_class,
        ClickEvent.country_code,
        ClickEvent.ip_address,
        ClickEvent.bot_blocked,
        ClickEvent.risk_score,
        ClickEvent.destination_url_final,
        ClickEvent.creator_id,
    ).where(conditions)

    if platform:
        query = query.where(ClickEvent.source_platform == platform)
    if creator:
        query = query.where(ClickEvent.creator_id == creator)

    query = query.order_by(ClickEvent.created_at.desc())

    # Count total
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    # Paginate
    offset = (page - 1) * per_page
    rows = await db.execute(query.offset(offset).limit(per_page))

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "clicks": [
            {
                "id": str(row.id),
                "click_id": row.click_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "source_platform": row.source_platform,
                "device_class": row.device_class,
                "country_code": row.country_code,
                "ip_address": row.ip_address,
                "bot_blocked": row.bot_blocked,
                "risk_score": row.risk_score,
                "destination_url": row.destination_url_final,
                "creator_id": str(row.creator_id),
            }
            for row in rows.all()
        ],
    }


@router.get("/conversions")
async def dashboard_conversions(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Conversion and refund KPIs: total conversions, revenue, refunds, net revenue, conversion rate."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    org_id = auth.organization_id

    # Total clicks (for conversion rate)
    clicks_result = await db.execute(
        select(func.count(ClickEvent.id))
        .where(and_(ClickEvent.organization_id == org_id, ClickEvent.created_at >= cutoff))
    )
    total_clicks = clicks_result.scalar_one()

    # Conversions
    conv_result = await db.execute(
        select(
            func.count(ConversionEvent.id).label("total_conversions"),
            func.coalesce(func.sum(ConversionEvent.revenue_cents), 0).label("total_revenue_cents"),
        )
        .where(and_(ConversionEvent.organization_id == org_id, ConversionEvent.created_at >= cutoff))
    )
    conv = conv_result.one()

    # Conversions by type
    conv_by_type_result = await db.execute(
        select(
            ConversionEvent.event_type,
            func.count(ConversionEvent.id).label("count"),
            func.coalesce(func.sum(ConversionEvent.revenue_cents), 0).label("revenue_cents"),
        )
        .where(and_(ConversionEvent.organization_id == org_id, ConversionEvent.created_at >= cutoff))
        .group_by(ConversionEvent.event_type)
        .order_by(func.count(ConversionEvent.id).desc())
    )
    by_type = [
        {"event_type": row.event_type, "count": row.count, "revenue_cents": row.revenue_cents}
        for row in conv_by_type_result.all()
    ]

    # Refunds
    refund_result = await db.execute(
        select(
            func.count(RefundEvent.id).label("total_refunds"),
            func.coalesce(func.sum(RefundEvent.refund_amount_cents), 0).label("total_refund_cents"),
        )
        .where(and_(RefundEvent.organization_id == org_id, RefundEvent.created_at >= cutoff))
    )
    refund = refund_result.one()

    net_revenue_cents = conv.total_revenue_cents - refund.total_refund_cents
    conversion_rate = (
        round(conv.total_conversions / total_clicks * 100, 2)
        if total_clicks > 0
        else 0.0
    )
    refund_rate = (
        round(refund.total_refunds / conv.total_conversions * 100, 2)
        if conv.total_conversions > 0
        else 0.0
    )

    return {
        "total_clicks": total_clicks,
        "total_conversions": conv.total_conversions,
        "total_revenue_cents": conv.total_revenue_cents,
        "total_refunds": refund.total_refunds,
        "total_refund_cents": refund.total_refund_cents,
        "net_revenue_cents": net_revenue_cents,
        "conversion_rate": conversion_rate,
        "refund_rate": refund_rate,
        "by_type": by_type,
        "period_days": days,
    }


@router.get("/creators")
async def dashboard_creators(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Performance by creator: clicks, conversions, revenue, refund rate."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    org_id = auth.organization_id

    # Clicks per creator
    clicks_result = await db.execute(
        select(
            ClickEvent.creator_id,
            func.count(ClickEvent.id).label("clicks"),
        )
        .where(and_(ClickEvent.organization_id == org_id, ClickEvent.created_at >= cutoff))
        .group_by(ClickEvent.creator_id)
    )
    clicks_by_creator = {str(row.creator_id): row.clicks for row in clicks_result.all()}

    # Conversions per creator (join via click_id)
    conv_result = await db.execute(
        select(
            ClickEvent.creator_id,
            func.count(ConversionEvent.id).label("conversions"),
            func.coalesce(func.sum(ConversionEvent.revenue_cents), 0).label("revenue_cents"),
        )
        .select_from(
            ConversionEvent.__table__.join(
                ClickEvent.__table__,
                ConversionEvent.click_id == ClickEvent.click_id,
            )
        )
        .where(and_(ConversionEvent.organization_id == org_id, ConversionEvent.created_at >= cutoff))
        .group_by(ClickEvent.creator_id)
    )
    conv_by_creator = {
        str(row.creator_id): {"conversions": row.conversions, "revenue_cents": row.revenue_cents}
        for row in conv_result.all()
    }

    # Refunds per creator (join via click_id)
    refund_result = await db.execute(
        select(
            ClickEvent.creator_id,
            func.count(RefundEvent.id).label("refunds"),
            func.coalesce(func.sum(RefundEvent.refund_amount_cents), 0).label("refund_cents"),
        )
        .select_from(
            RefundEvent.__table__.join(
                ClickEvent.__table__,
                RefundEvent.click_id == ClickEvent.click_id,
            )
        )
        .where(and_(RefundEvent.organization_id == org_id, RefundEvent.created_at >= cutoff))
        .group_by(ClickEvent.creator_id)
    )
    refund_by_creator = {
        str(row.creator_id): {"refunds": row.refunds, "refund_cents": row.refund_cents}
        for row in refund_result.all()
    }

    # Get creator details
    all_creator_ids = set(clicks_by_creator.keys()) | set(conv_by_creator.keys())
    creators_result = await db.execute(
        select(Creator.id, Creator.handle, Creator.display_name)
        .where(Creator.id.in_([UUID(cid) for cid in all_creator_ids]))
    )
    creator_info = {str(row.id): {"handle": row.handle, "display_name": row.display_name} for row in creators_result.all()}

    # Merge
    creators = []
    for cid in all_creator_ids:
        info = creator_info.get(cid, {"handle": "unknown", "display_name": None})
        conv = conv_by_creator.get(cid, {"conversions": 0, "revenue_cents": 0})
        ref = refund_by_creator.get(cid, {"refunds": 0, "refund_cents": 0})
        clicks = clicks_by_creator.get(cid, 0)

        creators.append({
            "creator_id": cid,
            "handle": info["handle"],
            "display_name": info["display_name"],
            "clicks": clicks,
            "conversions": conv["conversions"],
            "revenue_cents": conv["revenue_cents"],
            "refunds": ref["refunds"],
            "refund_cents": ref["refund_cents"],
            "net_revenue_cents": conv["revenue_cents"] - ref["refund_cents"],
            "conversion_rate": round(conv["conversions"] / clicks * 100, 2) if clicks > 0 else 0.0,
            "refund_rate": round(ref["refunds"] / conv["conversions"] * 100, 2) if conv["conversions"] > 0 else 0.0,
        })

    # Sort by clicks descending
    creators.sort(key=lambda x: x["clicks"], reverse=True)

    return {
        "creators": creators,
        "period_days": days,
    }


@router.get("/links")
async def dashboard_links(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
):
    """All links for the org."""
    result = await db.execute(
        select(Link)
        .where(Link.organization_id == auth.organization_id)
        .order_by(Link.created_at.desc())
    )
    links = result.scalars().all()
    return [
        {
            "id": str(link.id),
            "creator_handle": link.creator_handle,
            "campaign_slug": link.campaign_slug,
            "asset_slug": link.asset_slug,
            "destination_url": link.destination_url,
            "status": link.status,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        }
        for link in links
    ]


@router.get("/me")
async def dashboard_me(
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
):
    """User profile + org name."""
    user_result = await db.execute(select(User).where(User.id == auth.user_id))
    user = user_result.scalar_one()

    org_result = await db.execute(select(Organization).where(Organization.id == auth.organization_id))
    org = org_result.scalar_one()

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
        },
    }


# ---------------------------------------------------------------------------
# Link creation (Supabase-authed, simplified for dashboard users)
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class CreateDashboardLinkRequest(BaseModel):
    destination_url: str
    creator_handle: str
    campaign_slug: str
    asset_slug: str | None = None


def _validate_destination_url(url: str):
    """Prevent open redirect attacks."""
    from fastapi import HTTPException
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="destination_url must start with https:// or http://")
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "172.16."]
    for b in blocked:
        if b in url.split("//")[1].split("/")[0]:
            raise HTTPException(status_code=400, detail="destination_url cannot point to internal addresses")


@router.post("/links")
async def create_dashboard_link(
    req: CreateDashboardLinkRequest,
    auth: SupabaseAuthContext = Depends(require_supabase_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a wrapped link from the dashboard. Auto-creates creator + campaign if needed."""
    from uuid import uuid4
    from app.config import get_settings

    settings = get_settings()
    _validate_destination_url(req.destination_url)

    org_id = auth.organization_id

    # Find or create creator by handle within this org
    creator_result = await db.execute(
        select(Creator).where(Creator.handle == req.creator_handle)
    )
    creator = creator_result.scalar_one_or_none()
    if not creator:
        creator = Creator(
            id=uuid4(),
            handle=req.creator_handle,
            display_name=req.creator_handle,
        )
        db.add(creator)
        await db.flush()

    # Find or create campaign by slug within this org
    from app.models.tables import Campaign
    campaign_result = await db.execute(
        select(Campaign).where(
            Campaign.slug == req.campaign_slug,
            Campaign.organization_id == org_id,
        )
    )
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        campaign = Campaign(
            id=uuid4(),
            organization_id=org_id,
            name=req.campaign_slug,
            slug=req.campaign_slug,
        )
        db.add(campaign)
        await db.flush()

    # Check for duplicate route
    dup_result = await db.execute(
        select(Link).where(
            Link.creator_handle == req.creator_handle,
            Link.campaign_slug == req.campaign_slug,
            Link.asset_slug == req.asset_slug,
        )
    )
    if dup_result.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="A link with this creator/campaign/asset combination already exists")

    link = Link(
        id=uuid4(),
        organization_id=org_id,
        creator_id=creator.id,
        campaign_id=campaign.id,
        creator_handle=req.creator_handle,
        campaign_slug=req.campaign_slug,
        asset_slug=req.asset_slug,
        destination_url=req.destination_url,
        source="member",
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    path = f"/c/{link.creator_handle}/{link.campaign_slug}"
    if link.asset_slug:
        path += f"/{link.asset_slug}"
    wrapper_url = f"{settings.base_url}{path}"

    return {
        "id": str(link.id),
        "wrapper_url": wrapper_url,
        "destination_url": link.destination_url,
        "creator_handle": link.creator_handle,
        "campaign_slug": link.campaign_slug,
        "asset_slug": link.asset_slug,
        "status": link.status,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }
