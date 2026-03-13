"""
Pixel Heartbeat + Identify endpoint — lightweight tracking for pixel health.

GET  /v1/pixel/heartbeat  → 1x1 transparent GIF, logs that the pixel is alive on a site
POST /v1/events/identify   → Links an external customer ID to a click ID
POST /v1/events/custom     → Generic custom event passthrough
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.tables import ClickEvent
from app.models.platform_connection import PlatformConnection
from app.middleware.auth import AuthContext, require_auth, enforce_org_scope
from app.middleware.rate_limit import rate_limit_api_key
from app.core.click_id import verify_click_id

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/v1", tags=["pixel"])

# 1x1 transparent GIF (43 bytes)
PIXEL_GIF = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00"
    b"\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"\x44\x01\x00\x3b"
)


@router.get("/pixel/heartbeat")
async def pixel_heartbeat(request: Request):
    """
    Fires on every page load where wrp.js is installed.
    No auth required — this is just a health check / install tracker.
    Logged for analytics: which domains have the pixel, how often it fires.
    """
    org = request.query_params.get("org", "")
    url = request.query_params.get("url", "")
    has_click = request.query_params.get("has_click", "0")

    logger.info(
        "pixel_heartbeat",
        org=org,
        domain=url,
        has_click=has_click == "1",
    )

    return Response(
        content=PIXEL_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Access-Control-Allow-Origin": "*",
        },
    )


# --- Identify endpoint (link external customer ID to click) ---

class IdentifyPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    external_customer_id: str | None = None
    email_hash: str | None = None
    uid2_token: str | None = None
    ramp_id: str | None = None
    ramp_envelope: str | None = None
    id5_id: str | None = None


@router.post("/events/identify", status_code=201)
async def identify_user(
    payload: IdentifyPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))

    from uuid import UUID
    from app.models.tables import UniversalEvent
    try:
        org_id = UUID(payload.organization_id)
    except ValueError:
        return {"status": "error", "detail": "Invalid org ID"}

    enforce_org_scope(auth, org_id)

    click = verify_click_id(payload.inf_click_id)
    if click is None:
        return {"status": "error", "detail": "Invalid click ID"}

    # Store identity signals in universal_events table
    identity_data = {}
    if payload.external_customer_id: identity_data["external_customer_id"] = payload.external_customer_id
    if payload.email_hash: identity_data["hashed_email"] = payload.email_hash
    if payload.uid2_token: identity_data["uid2_token"] = payload.uid2_token
    if payload.ramp_id: identity_data["ramp_id"] = payload.ramp_id
    if payload.ramp_envelope: identity_data["ramp_envelope"] = payload.ramp_envelope
    if payload.id5_id: identity_data["id5_id"] = payload.id5_id

    if identity_data:
        event = UniversalEvent(
            click_id=payload.inf_click_id,
            organization_id=payload.organization_id,
            event_type="identify",
            event_source="api_identify",
            event_data=identity_data,
        )
        db.add(event)
        await db.commit()

    logger.info(
        "identify_event",
        click_id=payload.inf_click_id,
        org=payload.organization_id,
        has_customer_id=bool(payload.external_customer_id),
        has_email_hash=bool(payload.email_hash),
        has_uid2=bool(payload.uid2_token),
        has_ramp_id=bool(payload.ramp_id),
        has_id5=bool(payload.id5_id),
    )

    return {"status": "ok", "event_type": "identify"}


# --- Custom event passthrough ---

class CustomEventPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    event_name: str
    metadata: dict | None = None
    page_url: str | None = None


@router.post("/events/custom", status_code=201)
async def custom_event(
    payload: CustomEventPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))

    from uuid import UUID
    try:
        org_id = UUID(payload.organization_id)
    except ValueError:
        return {"status": "error", "detail": "Invalid org ID"}

    enforce_org_scope(auth, org_id)

    click = verify_click_id(payload.inf_click_id)
    if click is None:
        return {"status": "error", "detail": "Invalid click ID"}

    logger.info(
        "custom_event",
        click_id=payload.inf_click_id,
        org=payload.organization_id,
        event_name=payload.event_name,
    )

    return {"status": "ok", "event_type": "custom", "event_name": payload.event_name}


@router.get("/px/{click_id}", response_class=HTMLResponse, include_in_schema=False)
async def pixel_fire_page(
    click_id: str,
    dst: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Intermediary HTML page that:
    1. Fires browser-side pixels (Meta, TikTok, GA4, Snapchat)
    2. JS-redirects to final destination

    This allows browser-side pixel events while also having CAPI server-side fallback.
    The click_id is used as event_id for deduplication.
    """
    # Look up click to get org + pixel configs
    click_stmt = select(ClickEvent).where(ClickEvent.click_id == click_id)
    click_result = await db.execute(click_stmt)
    click = click_result.scalar_one_or_none()

    pixel_scripts = ""

    if click:
        pixel_stmt = select(PlatformConnection).where(
            PlatformConnection.org_id == click.organization_id,
            PlatformConnection.enabled == True,
            PlatformConnection.status == "active",
            or_(PlatformConnection.link_id == click.link_id, PlatformConnection.link_id == None)
        )
        pixel_result = await db.execute(pixel_stmt)
        configs = pixel_result.scalars().all()

        for config in configs:
            if config.platform == "meta":
                pixel_scripts += f"""
                    !function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
                    n.callMethod.apply(n,arguments):n.queue.push(arguments)}};if(!f._fbq)f._fbq=n;
                    n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
                    t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}}(window,
                    document,'script','https://connect.facebook.net/en_US/fbevents.js');
                    fbq('init', '{config.platform_account_id}');
                    fbq('track', 'ViewContent', {{}}, {{eventID: '{click_id}'}});
                """
            elif config.platform == "tiktok":
                pixel_scripts += f"""
                    !function (w, d, t) {{
                      w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"],ttq.setAndDefer=function(t,e){{t[e]=function(){{t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}}}; for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){{for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e}},ttq.load=function(e,n){{var i="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{{}},ttq._i[e]=[],ttq._i[e]._u=i,ttq._t=ttq._t||{{}},ttq._t[e]=+new Date,ttq._o=ttq._o||{{}},ttq._o[e]=n||{{}};var o=document.createElement("script");o.type="text/javascript",o.async=!0,o.src=i+"?sdkid="+e+"&lib="+t;var a=document.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)}};
                      ttq.load('{config.platform_account_id}');
                      ttq.page();
                      ttq.track('ClickButton', {{}}, {{event_id: '{click_id}'}});
                    }}(window, document, 'ttq');
                """
            elif config.platform == "ga4":
                pixel_scripts += f"""
                    <script async src="https://www.googletagmanager.com/gtag/js?id={config.platform_account_id}"></script>
                    <script>
                    window.dataLayer = window.dataLayer || [];
                    function gtag(){{dataLayer.push(arguments);}}
                    gtag('js', new Date());
                    gtag('config', '{config.platform_account_id}');
                    gtag('event', 'influencer_click', {{'click_id': '{click_id}'}});
                    </script>
                """
            elif config.platform == "snapchat":
                pixel_scripts += f"""
                    (function(e,t,n){{if(e.snaptr)return;var a=e.snaptr=function()
                    {{a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)}};
                    a.queue=[];var s='script';r=t.createElement(s);r.async=!0;
                    r.src=n;var u=t.getElementsByTagName(s)[0];
                    u.parentNode.insertBefore(r,u);}})(window,document,
                    'https://sc-static.net/scevent.min.js');
                    snaptr('init', '{config.platform_account_id}');
                    snaptr('track', 'PAGE_VIEW', {{'client_dedup_id': '{click_id}'}});
                """
            elif config.platform == "pinterest":
                pixel_scripts += f"""
                    !function(e,t,n,s,i){{if(!e[s]){{e[s]=[];e[s].sharedData={{}}}}var a=t.createElement(n);a.src="https://s.pinimg.com/ct/core.js",a.async=!0,a.crossOrigin="use-credentials";var r=t.getElementsByTagName(n)[0];r.parentNode.insertBefore(a,r);a.onload=function(){{pintrk('load','{config.platform_account_id}',{{save_to_localstorage:false}});pintrk('page');pintrk('track','pagevisit',{{event_id:'{click_id}'}})}}}}(window,document,'script','pintrk');
                """

    # Wrap non-GA4 scripts in a single script tag
    # GA4 scripts already have their own tags
    ga4_scripts = ""
    other_scripts = ""
    for line in pixel_scripts.split("\n"):
        stripped = line.strip()
        if stripped.startswith("<script") or stripped.startswith("</script>"):
            ga4_scripts += line + "\n"
        else:
            other_scripts += line + "\n"

    script_block = ""
    if other_scripts.strip():
        script_block += f"<script>{other_scripts}</script>\n"
    script_block += ga4_scripts

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Redirecting...</title>
{script_block}
</head>
<body>
<script>
  setTimeout(function() {{
    window.location.replace("{dst}");
  }}, 150);
</script>
<noscript><meta http-equiv="refresh" content="0;url={dst}"></noscript>
</body>
</html>"""

    return HTMLResponse(content=html)
