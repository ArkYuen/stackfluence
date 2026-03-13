"""
Server-side pixel firing service.
Fires events to Meta CAPI, TikTok Events API, GA4 Measurement Protocol,
Google Ads, Snapchat, LinkedIn, Reddit, and Pinterest CAPI.

All fires are non-blocking — failures are logged but never raise.
Deduplication: event_id = click_id (same value used in browser pixel)
"""
import asyncio
import hashlib
import time
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_token
from app.models.platform_connection import PlatformConnection

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


async def fire_linkedin_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str):
    """Fire conversion event to LinkedIn Conversions API"""
    try:
        payload = {
            "conversion": f"urn:lla:llaPartnerConversion:{pixel_id}",
            "conversionHappenedAt": int(time.time() * 1000),
            "eventId": click_id,
            "user": {
                "userIds": [],
                "userInfo": {
                    "firstName": None,
                }
            },
            "attribution": {
                "userActionAt": int(time.time() * 1000),
                "page": page_url,
            }
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://api.linkedin.com/rest/conversionEvents",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "LinkedIn-Version": "202401",
                    "Content-Type": "application/json",
                    "X-RestLi-Protocol-Version": "2.0.0",
                },
                json=payload,
            )
            logger.info("linkedin_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("linkedin_capi_failed", error=str(e), click_id=click_id)


async def fire_reddit_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str):
    """Fire PageVisit event to Reddit Conversions API"""
    try:
        payload = {
            "test_mode": False,
            "events": [{
                "event_type": "PageVisit",
                "event_id": click_id,
                "event_at": f"{int(time.time())}",
                "user": {
                    "ip_address": hashlib.sha256(ip.encode()).hexdigest() if ip else None,
                    "user_agent": ua,
                },
                "screen": {
                    "dimensions": {}
                },
                "click_id": click_id,
            }]
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://ads-api.reddit.com/api/v2.0/conversions/events/{pixel_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            logger.info("reddit_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("reddit_capi_failed", error=str(e), click_id=click_id)


async def fire_pinterest_capi(pixel_id: str, access_token: str, click_id: str, ip: str, ua: str, page_url: str):
    """Fire page_visit event to Pinterest Conversions API"""
    try:
        payload = {
            "data": [{
                "event_name": "page_visit",
                "action_source": "web",
                "event_time": int(time.time()),
                "event_id": click_id,
                "event_source_url": page_url,
                "user_data": {
                    "client_ip_address": hashlib.sha256(ip.encode()).hexdigest() if ip else None,
                    "client_user_agent": ua,
                },
            }]
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://api.pinterest.com/v5/ad_accounts/{pixel_id}/events",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            logger.info("pinterest_capi_fired", status=resp.status_code, click_id=click_id)
    except Exception as e:
        logger.warning("pinterest_capi_failed", error=str(e), click_id=click_id)


async def fire_pixels_for_click(org_id: str, click_id: str, ip: str, ua: str,
                                destination_url: str, db: AsyncSession):
    """
    Fire all configured server-side pixels for a click event.
    Queries PlatformConnection, decrypts tokens, fires CAPI calls.
    Called as asyncio.create_task() — non-blocking.
    """
    try:
        result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.org_id == org_id,
                PlatformConnection.enabled == True,
                PlatformConnection.status == "active",
                PlatformConnection.link_id == None,
            )
        )
        connections = result.scalars().all()
    except Exception as e:
        logger.warning("pixel_fire_query_failed", error=str(e), org_id=org_id)
        return

    tasks = []
    for conn in connections:
        access_token = (
            decrypt_token(conn.access_token_encrypted)
            if conn.access_token_encrypted
            else conn.platform_account_id
        )
        pixel_id = conn.platform_account_id

        if conn.platform == "meta" and access_token:
            tasks.append(fire_meta_capi(pixel_id, access_token, click_id, ip, ua, destination_url))
        elif conn.platform == "tiktok" and access_token:
            tasks.append(fire_tiktok_capi(pixel_id, access_token, click_id, ip, ua, destination_url))
        elif conn.platform == "ga4" and conn.secondary_id:
            tasks.append(fire_ga4_mp(pixel_id, conn.secondary_id, click_id, destination_url))
        elif conn.platform == "snapchat" and access_token:
            tasks.append(fire_snapchat_capi(pixel_id, access_token, click_id, ip, ua, destination_url))
        elif conn.platform == "linkedin" and access_token:
            tasks.append(fire_linkedin_capi(pixel_id, access_token, click_id, ip, ua, destination_url))
        elif conn.platform == "reddit" and access_token:
            tasks.append(fire_reddit_capi(pixel_id, access_token, click_id, ip, ua, destination_url))
        elif conn.platform == "pinterest" and access_token:
            tasks.append(fire_pinterest_capi(pixel_id, access_token, click_id, ip, ua, destination_url))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Update event stats per connection
    try:
        for conn in connections:
            conn.last_event_at = datetime.now(timezone.utc)
            conn.last_event_status = "success"
            conn.total_events_fired = (conn.total_events_fired or 0) + 1
        await db.commit()
    except Exception as e:
        logger.warning("pixel_fire_stats_update_failed", error=str(e))
