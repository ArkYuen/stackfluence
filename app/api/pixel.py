"""
Pixel Heartbeat + Identify endpoint — lightweight tracking for pixel health.

GET  /v1/pixel/heartbeat  → 1x1 transparent GIF, logs that the pixel is alive on a site
POST /v1/events/identify   → Links an external customer ID to a click ID
POST /v1/events/custom     → Generic custom event passthrough
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
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


@router.post("/events/identify", status_code=201)
async def identify_user(
    payload: IdentifyPayload,
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
        "identify_event",
        click_id=payload.inf_click_id,
        org=payload.organization_id,
        has_customer_id=bool(payload.external_customer_id),
        has_email_hash=bool(payload.email_hash),
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
