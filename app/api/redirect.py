"""
Click intake endpoint — /c/{creator_handle}/{campaign_slug}/{asset_slug?}

Captures:
  - Sec-Fetch metadata headers (site, mode, dest, user)
  - All request headers subset
  - Timing (server_received_at, server_responded_at)
  - Session cookie (inf_session_id) for repeat visit stitching
  - Click cookie (inf_click_id) for attribution
  - Geo lookup from IP (when MaxMind available)
  - Platform passthrough params
  - Full source intelligence

Flow:
  1. Look up link
  2. Bot detection + dedupe
  3. Analyze referrer + UA
  4. Capture sec-fetch, platform params, all headers
  5. Build destination URL with injected params
  6. Create click event in DB with timing
  7. Log to firehose
  8. Set cookies (click_id + session_id)
  9. If ?nocollect=1 → direct 302
     Otherwise → 302 to /r/{click_id} (collector hop)
"""

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.bot_detection import score_request
from app.core.click_id import mint_click_id
from app.core.referrer_intelligence import analyze_click
from app.core.param_injection import resolve_destination, extract_platform_params
from app.models.database import get_db
from app.models.tables import ClickEvent, ClickEventLog, Link
from app.middleware.rate_limit import rate_limit_ip, rate_limit_link, check_dedupe

import structlog

logger = structlog.get_logger()
router = APIRouter()


def _get_real_ip(request: Request) -> str:
    """Extract real client IP from x-forwarded-for or request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in chain is the client
        ips = [ip.strip() for ip in forwarded.split(",")]
        for ip in ips:
            # Skip private ranges
            if not ip.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                                  "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                                  "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                                  "172.30.", "172.31.", "192.168.", "127.", "::1")):
                return ip
        return ips[0]
    return request.client.host if request.client else "unknown"


def _geo_lookup(ip: str) -> dict:
    """
    Geo lookup from IP. Returns dict with country, region, city, asn, isp.
    Stub — returns empty until MaxMind is configured.
    To enable: pip install geoip2, download GeoLite2 DBs, set SF_GEOIP_PATH.
    """
    # TODO: implement with MaxMind GeoLite2
    # import geoip2.database
    # reader = geoip2.database.Reader(settings.geoip_path)
    # response = reader.city(ip)
    # return { "country_code": response.country.iso_code, ... }
    return {
        "country_code": None,
        "region": None,
        "city": None,
        "asn": None,
        "isp": None,
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
    server_start = time.monotonic()
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
                       reason=verdict.reason, ip=_get_real_ip(request))
        raise HTTPException(status_code=404, detail="Not found")

    # --- Dedupe check ---
    ip = _get_real_ip(request)
    slug = f"{creator_handle}/{campaign_slug}"
    is_dedupe = check_dedupe(ip, slug, ua or "")
    is_suspected_bot = verdict.risk_score >= settings.bot_risk_flag_threshold or is_dedupe
    bot_reason = None
    if is_dedupe:
        bot_reason = "dedupe_3s"
    elif verdict.risk_score >= settings.bot_risk_flag_threshold:
        bot_reason = verdict.reason

    # --- 3. Analyze click (referrer intelligence) ---
    referer = request.headers.get("referer")
    accept_lang = request.headers.get("accept-language")

    intel = analyze_click(
        user_agent=ua,
        referer=referer,
        accept_language=accept_lang,
        headers=headers_dict,
    )

    # --- 4. Capture sec-fetch metadata headers ---
    sec_fetch_site = request.headers.get("sec-fetch-site")
    sec_fetch_mode = request.headers.get("sec-fetch-mode")
    sec_fetch_dest = request.headers.get("sec-fetch-dest")
    sec_fetch_user = request.headers.get("sec-fetch-user")

    # --- 5. Capture platform-injected params ---
    all_query_params = dict(request.query_params)
    platform_params = extract_platform_params(all_query_params)

    # --- 6. Mint click_id ---
    click_id = mint_click_id()

    # --- 7. Session cookie (for repeat visit stitching) ---
    session_id = request.cookies.get("inf_session_id")
    new_session = False
    if not session_id:
        session_id = uuid.uuid4().hex
        new_session = True

    # --- 8. Resolve destination ---
    final_url, injected_params = resolve_destination(
        link=link,
        click_id=str(click_id),
        source_platform=intel.source_platform,
        source_medium=intel.source_medium,
        source_detail=intel.source_detail,
        is_mobile=intel.is_mobile,
        os_family=intel.os_family,
        platform_params=platform_params,
        referrer=referer,
    )

    # Extract UTM subset
    utm_params = {k: v for k, v in injected_params.items() if k.startswith("utm_")}

    # Build ua_parsed
    ua_parsed = {
        "os_family": intel.os_family,
        "os_version": intel.os_version,
        "browser_family": intel.browser_family,
        "browser_version": intel.browser_version,
        "device_class": intel.device_class,
        "is_mobile": intel.is_mobile,
    }

    # --- 9. Geo lookup ---
    geo = _geo_lookup(ip)

    # --- 10. Create click event ---
    now = datetime.now(timezone.utc)

    click_event = ClickEvent(
        click_id=str(click_id),
        session_id=session_id,
        link_id=link.id,
        organization_id=link.organization_id,
        creator_id=link.creator_id,
        campaign_id=link.campaign_id,

        # Destinations
        destination_url_raw=link.destination_url,
        destination_url_final=final_url,

        # Params
        utm=utm_params,
        injected_params=injected_params,
        platform_click_ids=platform_params if platform_params else None,
        query_params=all_query_params if all_query_params else None,

        # Source provenance
        referrer_header=referer,

        # Source intelligence
        source_platform=intel.source_platform,
        source_medium=intel.source_medium,
        source_detail=intel.source_detail,
        is_in_app_browser=intel.is_in_app_browser,
        in_app_platform=intel.in_app_platform,
        referer_domain=intel.referer_domain,

        # Network
        ip_address=ip,

        # Sec-Fetch headers
        sec_fetch_site=sec_fetch_site,
        sec_fetch_mode=sec_fetch_mode,
        sec_fetch_dest=sec_fetch_dest,
        sec_fetch_user=sec_fetch_user,

        # User agent
        user_agent=ua,
        ua_parsed=ua_parsed,
        is_webview_guess=intel.is_in_app_browser,

        # Device
        device_class=intel.device_class,
        os_family=intel.os_family,
        os_version=intel.os_version,
        browser_family=intel.browser_family,
        browser_version=intel.browser_version,
        is_mobile=intel.is_mobile,

        # Geo
        country_code=geo["country_code"],
        region=geo["region"],
        city=geo["city"],
        asn=geo["asn"],
        isp=geo["isp"],

        # Language
        language=intel.language,
        locale=intel.locale,

        # Bot / fraud
        risk_score=verdict.risk_score,
        bot_blocked=False,
        is_suspected_bot=is_suspected_bot,
        bot_reason=bot_reason,
        bot_signals={
            "ua_blocked": verdict.signals.ua_blocked,
            "ua_is_known_bot": verdict.signals.ua_is_known_bot,
            "missing_accept_language": verdict.signals.missing_accept_language,
            "missing_sec_fetch": verdict.signals.missing_sec_fetch,
            "is_datacenter_ip": verdict.signals.is_datacenter_ip,
            "rate_limited": verdict.signals.rate_limited,
            "dedupe_hit": is_dedupe,
            "sec_fetch_site": sec_fetch_site,
            "sec_fetch_mode": sec_fetch_mode,
            "sec_fetch_dest": sec_fetch_dest,
            "sec_fetch_user": sec_fetch_user,
        },

        # Timing
        server_received_at=now,
    )
    db.add(click_event)

    # --- 11. Log to firehose ---
    db.add(ClickEventLog(
        click_id=str(click_id),
        event_type="server_received",
        payload={
            "ip": ip,
            "ua": ua[:200] if ua else None,
            "referer": referer[:500] if referer else None,
            "platform_params": list(platform_params.keys()) if platform_params else [],
            "source": intel.source_platform,
            "risk": verdict.risk_score,
            "sec_fetch": {
                "site": sec_fetch_site,
                "mode": sec_fetch_mode,
                "dest": sec_fetch_dest,
                "user": sec_fetch_user,
            },
            "session_id": session_id,
            "new_session": new_session,
        },
    ))

    await db.commit()

    # Update server_responded_at (timing)
    server_elapsed_ms = int((time.monotonic() - server_start) * 1000)
    click_event.server_responded_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("click_received",
                click_id=str(click_id),
                session_id=session_id,
                creator=creator_handle,
                campaign=campaign_slug,
                source=intel.source_platform,
                medium=intel.source_medium,
                in_app=intel.is_in_app_browser,
                device=intel.device_class,
                risk=verdict.risk_score,
                elapsed_ms=server_elapsed_ms)

    # --- 12. Set cookies + redirect ---
    nocollect = request.query_params.get("nocollect") == "1"

    if nocollect:
        response = RedirectResponse(url=final_url, status_code=302)
    else:
        collector_url = f"{settings.base_url}/r/{click_id}"
        response = RedirectResponse(url=collector_url, status_code=302)

    # Click ID cookie (7 days — brand's site can read for attribution)
    response.set_cookie(
        key="inf_click_id",
        value=str(click_id),
        max_age=604800,
        path="/",
        samesite="lax",
        secure=True,
        httponly=True,
    )

    # Session cookie (30 days — stitches repeat clicks from same visitor)
    if new_session:
        response.set_cookie(
            key="inf_session_id",
            value=session_id,
            max_age=2592000,     # 30 days
            path="/",
            samesite="lax",
            secure=True,
            httponly=True,
        )

    return response
