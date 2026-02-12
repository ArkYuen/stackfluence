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
from app.models.tables import ClickEvent, Link, Organization
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
