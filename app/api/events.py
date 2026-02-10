"""
Event ingestion API — receives events from advertiser connectors.

Security:
  - Requires API key (publishable OR secret)
  - Organization scoped: key's org must match the payload org
  - Rate limited per API key
  - Click ID signature validated before persisting
  - No data returned in responses (write-only for publishable keys)
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.click_id import verify_click_id
from app.models.database import get_db
from app.models.tables import ConversionEvent, PageViewEvent, RefundEvent, SessionEvent
from app.middleware.auth import AuthContext, require_auth, enforce_org_scope
from app.middleware.rate_limit import rate_limit_api_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/events", tags=["events"])


# --- Request schemas ---

class SessionPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    session_id: str | None = None
    page_url: str | None = None
    referrer: str | None = None


class PageViewPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    page_url: str | None = None
    time_on_page_ms: int | None = None


class ConversionPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    event_type: Literal["add_to_cart", "signup", "purchase", "lead", "custom"] = "purchase"
    order_id: str | None = None
    revenue_cents: int | None = None
    currency: str = "USD"
    metadata: dict | None = None


class RefundPayload(BaseModel):
    inf_click_id: str
    organization_id: str
    original_order_id: str
    refund_amount_cents: int | None = None
    reason: str | None = None


# --- Shared validation ---

def _validate_click_id(raw: str) -> str:
    click = verify_click_id(raw)
    if click is None:
        raise HTTPException(status_code=400, detail="Invalid or expired inf_click_id.")
    return raw


def _validate_org(auth: AuthContext, org_id_str: str):
    """Enforce that the API key's org matches the payload org."""
    from uuid import UUID
    try:
        org_id = UUID(org_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization_id format.")
    enforce_org_scope(auth, org_id)


# --- Endpoints ---

@router.post("/session", status_code=201)
async def ingest_session(
    payload: SessionPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    _validate_org(auth, payload.organization_id)
    _validate_click_id(payload.inf_click_id)

    event = SessionEvent(
        click_id=payload.inf_click_id,
        organization_id=payload.organization_id,
        session_id=payload.session_id,
        page_url=payload.page_url,
        referrer=payload.referrer,
    )
    db.add(event)
    await db.commit()

    logger.info("session_event", click_id=payload.inf_click_id, org=payload.organization_id)
    return {"status": "ok", "event_type": "session"}


@router.post("/pageview", status_code=201)
async def ingest_pageview(
    payload: PageViewPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    _validate_org(auth, payload.organization_id)
    _validate_click_id(payload.inf_click_id)

    event = PageViewEvent(
        click_id=payload.inf_click_id,
        organization_id=payload.organization_id,
        page_url=payload.page_url,
        time_on_page_ms=payload.time_on_page_ms,
    )
    db.add(event)
    await db.commit()

    logger.info("pageview_event", click_id=payload.inf_click_id)
    return {"status": "ok", "event_type": "pageview"}


@router.post("/conversion", status_code=201)
async def ingest_conversion(
    payload: ConversionPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    _validate_org(auth, payload.organization_id)
    _validate_click_id(payload.inf_click_id)

    event = ConversionEvent(
        click_id=payload.inf_click_id,
        organization_id=payload.organization_id,
        event_type=payload.event_type,
        order_id=payload.order_id,
        revenue_cents=payload.revenue_cents,
        currency=payload.currency,
        metadata_=payload.metadata,
    )
    db.add(event)
    await db.commit()

    logger.info("conversion_event", click_id=payload.inf_click_id,
                event_type=payload.event_type, revenue_cents=payload.revenue_cents)
    return {"status": "ok", "event_type": "conversion"}


@router.post("/refund", status_code=201)
async def ingest_refund(
    payload: RefundPayload,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rate_limit_api_key(str(auth.key_id))
    _validate_org(auth, payload.organization_id)
    _validate_click_id(payload.inf_click_id)

    event = RefundEvent(
        click_id=payload.inf_click_id,
        organization_id=payload.organization_id,
        original_order_id=payload.original_order_id,
        refund_amount_cents=payload.refund_amount_cents,
        reason=payload.reason,
    )
    db.add(event)
    await db.commit()

    logger.info("refund_event", click_id=payload.inf_click_id, order_id=payload.original_order_id)
    return {"status": "ok", "event_type": "refund"}
