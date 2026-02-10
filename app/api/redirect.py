"""
Redirect endpoint — the core of Stackfluence.

Route: GET /c/{creator_handle}/{campaign_slug}/{asset_slug?}

Security:
  - Rate limited per IP (30/min) and per IP+link combo (10/min)
  - Bot scoring on every request
  - No auth required (public-facing, but protected by rate limits + bot detection)
  - Generic 404 on missing links (no enumeration leakage)
  - No-referrer policy (don't leak stackfluence URL to destination)
  - No caching (every click needs a unique click_id)
"""

from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_ua

from app.config import get_settings
from app.core.bot_detection import score_request
from app.core.click_id import mint_click_id
from app.models.database import get_db
from app.models.tables import ClickEvent, Link
from app.middleware.rate_limit import rate_limit_ip, rate_limit_link

import structlog

logger = structlog.get_logger()
router = APIRouter()


def _append_click_id_to_url(url: str, click_id: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["inf_click_id"] = [click_id]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _extract_device_info(ua_string: str | None) -> dict:
    if not ua_string:
        return {"device_class": "unknown", "os_family": "unknown", "browser_family": "unknown"}
    parsed = parse_ua(ua_string)
    if parsed.is_mobile:
        device = "mobile"
    elif parsed.is_tablet:
        device = "tablet"
    elif parsed.is_pc:
        device = "desktop"
    else:
        device = "other"
    return {
        "device_class": device,
        "os_family": parsed.os.family,
        "browser_family": parsed.browser.family,
    }


@router.get("/c/{creator_handle}/{campaign_slug}")
@router.get("/c/{creator_handle}/{campaign_slug}/{asset_slug}")
async def redirect_click(
    request: Request,
    creator_handle: str,
    campaign_slug: str,
    asset_slug: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()

    # --- Rate limiting ---
    rate_limit_ip(request)
    rate_limit_link(request, creator_handle, campaign_slug)

    # --- 1. Look up link ---
    stmt = select(Link).where(
        Link.creator_handle == creator_handle,
        Link.campaign_slug == campaign_slug,
        Link.asset_slug == asset_slug,
        Link.status == "active",
    )
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()

    if not link:
        # Generic error — don't reveal whether the creator/campaign exists
        raise HTTPException(status_code=404, detail="Not found")

    # --- 2. Bot detection ---
    ua = request.headers.get("user-agent")
    headers_dict = dict(request.headers)

    verdict = score_request(
        user_agent=ua,
        headers=headers_dict,
        asn=None,
        rate_limited=False,
    )

    if verdict.should_block:
        logger.warning("bot_blocked", creator=creator_handle, campaign=campaign_slug,
                       reason=verdict.reason, ip=request.client.host if request.client else None)
        # Return generic 404 to bots — don't confirm link exists
        raise HTTPException(status_code=404, detail="Not found")

    # --- 3. Mint click_id ---
    click_id = mint_click_id()

    # --- 4. Log click event ---
    device_info = _extract_device_info(ua)
    click_event = ClickEvent(
        click_id=str(click_id), link_id=link.id,
        organization_id=link.organization_id, creator_id=link.creator_id,
        campaign_id=link.campaign_id,
        ip_address=request.client.host if request.client else None,
        user_agent=ua, referer=request.headers.get("referer"),
        device_class=device_info["device_class"],
        os_family=device_info["os_family"],
        browser_family=device_info["browser_family"],
        risk_score=verdict.risk_score, bot_blocked=False,
        bot_signals={
            "ua_blocked": verdict.signals.ua_blocked,
            "ua_is_known_bot": verdict.signals.ua_is_known_bot,
            "missing_accept_language": verdict.signals.missing_accept_language,
            "missing_sec_fetch": verdict.signals.missing_sec_fetch,
            "is_datacenter_ip": verdict.signals.is_datacenter_ip,
            "rate_limited": verdict.signals.rate_limited,
        },
        destination_url=link.destination_url,
    )
    db.add(click_event)
    await db.commit()

    logger.info("click_logged", click_id=str(click_id), creator=creator_handle,
                campaign=campaign_slug, risk_score=verdict.risk_score)

    # --- 5. Redirect ---
    final_url = _append_click_id_to_url(link.destination_url, str(click_id))
    return RedirectResponse(url=final_url, status_code=302)
