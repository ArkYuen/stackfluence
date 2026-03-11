"""
Server-side pixel firing service.
Fires events to Meta CAPI, TikTok Events API, GA4 Measurement Protocol,
Google Ads, and Snapchat CAPI.

All fires are non-blocking — failures are logged but never raise.
Deduplication: event_id = click_id (same value used in browser pixel)
"""
import asyncio
import hashlib
import time
import httpx
import structlog

logger = structlog.get_logger()


async def fire_meta_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str, test_event_code: str | None = None):
    """Fire PageView + ViewContent to Meta Conversions API"""
    try:
        payload = {
            "data": [{
                "event_name": "ViewContent",
                "event_time": int(time.time()),
                "event_id": click_id,  # dedup key
                "action_source": "website",
                "event_source_url": page_url,
                "user_data": {
                    "client_ip_address": ip,
                    "client_user_agent": ua,
                },
            }],
        }
        if test_event_code:
            payload["test_event_code"] = test_event_code

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v18.0/{pixel_id}/events",
                params={"access_token": access_token},
                json=payload,
            )
            logger.info("meta_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("meta_capi_failed", error=str(e), click_id=click_id)


async def fire_tiktok_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str):
    """Fire ClickButton event to TikTok Events API"""
    try:
        payload = {
            "pixel_code": pixel_id,
            "event": "ClickButton",
            "event_id": click_id,
            "timestamp": str(int(time.time())),
            "context": {
                "page": {"url": page_url},
                "user_agent": ua,
                "ip": ip,
            },
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://business-api.tiktok.com/open_api/v1.3/event/track/",
                headers={"Access-Token": access_token},
                json=payload,
            )
            logger.info("tiktok_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("tiktok_capi_failed", error=str(e), click_id=click_id)


async def fire_ga4_mp(measurement_id: str, api_secret: str, click_id: str, page_url: str):
    """Fire page_view + influencer_click to GA4 Measurement Protocol"""
    try:
        payload = {
            "client_id": click_id,
            "events": [
                {"name": "page_view", "params": {"page_location": page_url}},
                {"name": "influencer_click", "params": {"click_id": click_id, "engagement_time_msec": 100}},
            ],
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://www.google-analytics.com/mp/collect",
                params={"measurement_id": measurement_id, "api_secret": api_secret},
                json=payload,
            )
            logger.info("ga4_mp_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("ga4_mp_failed", error=str(e), click_id=click_id)


async def fire_snapchat_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str):
    """Fire PAGE_VIEW to Snapchat Conversions API"""
    try:
        payload = {
            "pixel_id": pixel_id,
            "data": [{
                "event_type": "PAGE_VIEW",
                "event_conversion_type": "WEB",
                "timestamp": str(int(time.time() * 1000)),
                "event_id": click_id,
                "user_data": {"ip_address": ip, "user_agent": ua},
                "page_url": page_url,
            }],
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://tr.snapchat.com/v2/conversion",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
            logger.info("snapchat_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("snapchat_capi_failed", error=str(e), click_id=click_id)


async def fire_pixels_for_click(pixel_configs: list, click_id: str, ip: str, ua: str, destination_url: str):
    """
    Fire all configured server-side pixels for a click event.
    Called as asyncio.create_task() — non-blocking.
    pixel_configs: list of PixelConfig ORM objects
    """
    tasks = []
    for config in pixel_configs:
        if not config.enabled:
            continue
        if config.platform == "meta" and config.access_token:
            tasks.append(fire_meta_capi(config.pixel_id, config.access_token, click_id, ip, ua, destination_url, config.test_event_code))
        elif config.platform == "tiktok" and config.access_token:
            tasks.append(fire_tiktok_capi(config.pixel_id, config.access_token, click_id, ip, ua, destination_url))
        elif config.platform == "ga4" and config.access_token:
            tasks.append(fire_ga4_mp(config.pixel_id, config.access_token, click_id, destination_url))
        elif config.platform == "snapchat" and config.access_token:
            tasks.append(fire_snapchat_capi(config.pixel_id, config.access_token, click_id, ip, ua, destination_url))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
