"""
Collector Hop — the secret weapon for referrer capture.

GET  /r/{click_id}  → Tiny HTML page with inline JS that captures:
  - document.referrer (more reliable than server Referer header)
  - window.location.href (our own URL, includes params — useful for debugging)
  - UA Client Hints: brands, platform, mobile
  - High entropy: platformVersion, uaFullVersion, model, architecture, bitness, fullVersionList
  - Screen: width, height, devicePixelRatio
  - Timezone: Intl.DateTimeFormat
  - Language: navigator.language + navigator.languages
  - Connection: navigator.connection.effectiveType
  - Touch: navigator.maxTouchPoints
  - Timing: performance.now() for collector hop delta

POST /collect/{click_id}  → Ingests client telemetry, updates click event.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.tables import ClickEvent, ClickEventLog

import structlog

logger = structlog.get_logger()
router = APIRouter()


@router.get("/r/{click_id}")
async def collector_hop(
    click_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve collector hop HTML page."""
    stmt = select(ClickEvent).where(ClickEvent.click_id == click_id)
    result = await db.execute(stmt)
    click = result.scalar_one_or_none()

    if not click:
        raise HTTPException(status_code=404, detail="Not found")

    destination = click.destination_url_final

    # CSP nonce for inline script security
    nonce = secrets.token_urlsafe(16)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Redirecting\u2026</title>
</head>
<body>
<noscript>
<p>Redirecting\u2026 <a href="{_html_escape(destination)}">Click here</a> if not redirected.</p>
</noscript>
<script nonce="{nonce}">
(async function() {{
  var t0 = Date.now();
  var dest = {_js_string(destination)};
  var data = {{}};

  // 1. document.referrer — the main prize
  try {{ data.document_referrer = document.referrer || null; }} catch(e) {{}}

  // 2. window.location.href — our own URL with all params (useful for debugging)
  try {{ data.collector_page_url = window.location.href; }} catch(e) {{}}

  // 3. User agent string
  try {{ data.user_agent = navigator.userAgent; }} catch(e) {{}}

  // 4. UA Client Hints (modern browsers — gold when available)
  try {{
    if (navigator.userAgentData) {{
      data.ua_brands = navigator.userAgentData.brands;
      data.ua_platform = navigator.userAgentData.platform;
      data.ua_mobile = navigator.userAgentData.mobile;
      try {{
        var hi = await navigator.userAgentData.getHighEntropyValues([
          "platformVersion",
          "uaFullVersion",
          "model",
          "architecture",
          "bitness",
          "fullVersionList"
        ]);
        data.ua_platform_version = hi.platformVersion || null;
        data.ua_full_version = hi.uaFullVersion || null;
        data.ua_model = hi.model || null;
        data.ua_arch = hi.architecture || null;
        data.ua_bitness = hi.bitness || null;
        data.ua_full_version_list = hi.fullVersionList || null;
      }} catch(e) {{}}
    }}
  }} catch(e) {{}}

  // 5. Screen
  try {{
    data.screen_width = screen.width;
    data.screen_height = screen.height;
    data.device_pixel_ratio = window.devicePixelRatio;
    data.color_depth = screen.colorDepth;
  }} catch(e) {{}}

  // 6. Timezone + language
  try {{
    data.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    data.language = navigator.language;
    data.languages = navigator.languages ? Array.from(navigator.languages) : null;
  }} catch(e) {{}}

  // 7. Connection (full details)
  try {{
    if (navigator.connection) {{
      data.connection_type = navigator.connection.effectiveType;
      data.connection_rtt = navigator.connection.rtt;
      data.connection_downlink = navigator.connection.downlink;
      data.connection_save_data = navigator.connection.saveData;
    }}
  }} catch(e) {{}}

  // 8. Touch capability
  try {{ data.max_touch_points = navigator.maxTouchPoints; }} catch(e) {{}}

  // 9. Browser capabilities
  try {{ data.cookie_enabled = navigator.cookieEnabled; }} catch(e) {{}}
  try {{ data.hardware_concurrency = navigator.hardwareConcurrency; }} catch(e) {{}}
  try {{ data.device_memory = navigator.deviceMemory; }} catch(e) {{}}
  try {{
    data.localStorage_ok = typeof localStorage !== 'undefined';
    data.sessionStorage_ok = typeof sessionStorage !== 'undefined';
    data.indexedDB_ok = typeof indexedDB !== 'undefined';
  }} catch(e) {{}}

  // 10. Viewport
  try {{
    data.viewport_width = window.innerWidth;
    data.viewport_height = window.innerHeight;
  }} catch(e) {{}}

  // 11. Visibility state
  try {{ data.visibility_state = document.visibilityState; }} catch(e) {{}}

  // 12. Do Not Track
  try {{ data.do_not_track = navigator.doNotTrack === '1' || window.doNotTrack === '1'; }} catch(e) {{}}

  // 13. Ad blocker detection (try to load a bait element)
  try {{
    var bait = document.createElement('div');
    bait.className = 'ad-banner ads adsbox ad-placement';
    bait.style.cssText = 'position:absolute;top:-999px;left:-999px;width:1px;height:1px;';
    document.body.appendChild(bait);
    data.ad_blocker_detected = (bait.offsetHeight === 0 || bait.clientHeight === 0);
    document.body.removeChild(bait);
  }} catch(e) {{ data.ad_blocker_detected = null; }}

  // 14. Timing — how long collector JS took (bots often don't execute JS at all)
  data.collector_js_time_ms = Date.now() - t0;

  // Send telemetry (fire and forget with keepalive)
  try {{
    navigator.sendBeacon(
      "/collect/{click_id}",
      new Blob([JSON.stringify(data)], {{ type: "application/json" }})
    );
  }} catch(e) {{
    try {{
      fetch("/collect/{click_id}", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(data),
        keepalive: true
      }});
    }} catch(e2) {{}}
  }}

  // Redirect immediately — don't wait for beacon
  window.location.replace(dest);
}})();
</script>
</body>
</html>"""

    return HTMLResponse(
        content=html,
        headers={
            "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.post("/collect/{click_id}")
async def collect_telemetry(
    click_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Ingest client telemetry from the collector hop."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=204)

    stmt = select(ClickEvent).where(ClickEvent.click_id == click_id)
    result = await db.execute(stmt)
    click = result.scalar_one_or_none()

    if not click:
        return Response(status_code=204)  # silent fail

    # --- Update source provenance ---
    if body.get("document_referrer"):
        click.document_referrer = body["document_referrer"]

    if body.get("collector_page_url"):
        click.collector_page_url = body["collector_page_url"]

    # --- Write to dedicated columns ---
    # Screen & viewport
    if body.get("screen_width") is not None:
        click.screen_width = body["screen_width"]
    if body.get("screen_height") is not None:
        click.screen_height = body["screen_height"]
    if body.get("viewport_width") is not None:
        click.viewport_width = body["viewport_width"]
    if body.get("viewport_height") is not None:
        click.viewport_height = body["viewport_height"]
    if body.get("color_depth") is not None:
        click.color_depth = body["color_depth"]

    # Client environment
    if body.get("timezone"):
        click.timezone = body["timezone"]
    if body.get("connection_type"):
        click.connection_type = body["connection_type"]
    if body.get("max_touch_points") is not None:
        click.touch_support = body["max_touch_points"] > 0
    if body.get("hardware_concurrency") is not None:
        click.hardware_concurrency = body["hardware_concurrency"]
    if body.get("device_memory") is not None:
        click.device_memory = body["device_memory"]
    if body.get("do_not_track") is not None:
        click.do_not_track = body["do_not_track"]
    if body.get("ad_blocker_detected") is not None:
        click.ad_blocker_detected = body["ad_blocker_detected"]

    # Redirect latency (time from server redirect to collector JS execution)
    if click.server_received_at and body.get("collector_js_time_ms") is not None:
        now_ts = datetime.now(timezone.utc)
        delta = now_ts - click.server_received_at
        click.redirect_latency_ms = max(0, int(delta.total_seconds() * 1000) - body["collector_js_time_ms"])

    # --- Build client_meta from everything (keep full JSONB for extras) ---
    client_meta = {}
    for key in [
        # UA Client Hints
        "ua_brands", "ua_platform", "ua_mobile",
        "ua_platform_version", "ua_full_version", "ua_model",
        "ua_arch", "ua_bitness", "ua_full_version_list",
        # Screen + viewport
        "screen_width", "screen_height", "device_pixel_ratio",
        "viewport_width", "viewport_height",
        # Locale
        "timezone", "language", "languages",
        # Connection (full)
        "connection_type", "connection_rtt", "connection_downlink", "connection_save_data",
        # Touch
        "max_touch_points",
        # Browser capabilities
        "cookie_enabled", "hardware_concurrency", "device_memory",
        "localStorage_ok", "sessionStorage_ok", "indexedDB_ok",
        # Visibility
        "visibility_state",
        # Timing
        "collector_js_time_ms",
    ]:
        if body.get(key) is not None:
            client_meta[key] = body[key]

    if client_meta:
        click.client_meta = client_meta

    # --- Timing ---
    now = datetime.now(timezone.utc)
    click.used_collector = True
    click.collector_received_at = now

    # --- Log to firehose ---
    # Compute hop delta if we have server_received_at
    hop_delta_ms = None
    if click.server_received_at:
        delta = now - click.server_received_at
        hop_delta_ms = int(delta.total_seconds() * 1000)

    db.add(ClickEventLog(
        click_id=click_id,
        event_type="client_collected",
        payload={
            "document_referrer": body.get("document_referrer"),
            "collector_page_url": body.get("collector_page_url"),
            "has_ua_ch": bool(body.get("ua_brands")),
            "has_high_entropy": bool(body.get("ua_full_version")),
            "screen": f"{body.get('screen_width')}x{body.get('screen_height')}",
            "timezone": body.get("timezone"),
            "connection_type": body.get("connection_type"),
            "collector_js_time_ms": body.get("collector_js_time_ms"),
            "hop_delta_ms": hop_delta_ms,
        },
    ))

    await db.commit()

    logger.info("collector_received",
                click_id=click_id,
                has_doc_referrer=bool(body.get("document_referrer")),
                has_ua_ch=bool(body.get("ua_brands")),
                timezone=body.get("timezone"),
                hop_delta_ms=hop_delta_ms,
                js_time_ms=body.get("collector_js_time_ms"))

    return Response(status_code=204)


def _js_string(s: str) -> str:
    """Safely encode a string for inline JS."""
    return (
        '"'
        + s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("<", "\\x3c")
        .replace(">", "\\x3e")
        + '"'
    )


def _html_escape(s: str) -> str:
    """Basic HTML escaping for noscript fallback link."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
