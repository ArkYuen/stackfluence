"""
Shopify integration — webhook receivers + store connection.

Webhook endpoints use Shopify's HMAC-SHA256 authentication (no API key needed).
The connect endpoint requires a secret API key (sf_sec_*).
"""

import base64
import hashlib
import hmac
import math
import secrets
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.click_id import verify_click_id
from app.models.database import get_db
from app.models.tables import ConversionEvent, RefundEvent, ShopifyStore
from app.middleware.auth import AuthContext, require_secret_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/shopify", tags=["shopify"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_shopify_hmac(body: bytes, secret: str, hmac_header: str) -> bool:
    """Validate X-Shopify-Hmac-Sha256 against the raw request body."""
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    computed = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(computed, hmac_header)


def _extract_click_id_from_note_attributes(note_attributes: list[dict] | None) -> str | None:
    """Parse Shopify's note_attributes array for inf_click_id."""
    if not note_attributes:
        return None
    for attr in note_attributes:
        if attr.get("name") == "inf_click_id":
            value = attr.get("value")
            if value and isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _shopify_money_to_cents(amount: str) -> int:
    """Convert Shopify money string like '29.99' to integer cents 2999."""
    try:
        return int(round(float(amount) * 100))
    except (ValueError, TypeError):
        return 0


async def _get_store_by_domain(db: AsyncSession, shop_domain: str) -> ShopifyStore | None:
    """Look up an active ShopifyStore by domain."""
    stmt = select(ShopifyStore).where(
        ShopifyStore.shop_domain == shop_domain,
        ShopifyStore.is_active == True,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Webhook: orders/create
# ---------------------------------------------------------------------------

@router.post("/webhooks/orders-create", status_code=200)
async def webhook_orders_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    # --- Identify the store ---
    shop_domain = request.headers.get("X-Shopify-Shop-Domain", "")
    store = await _get_store_by_domain(db, shop_domain)
    if not store:
        logger.warning("shopify_webhook_unknown_store", shop_domain=shop_domain)
        return {"status": "ignored", "reason": "unknown_store"}

    # --- Verify HMAC ---
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not _verify_shopify_hmac(body, store.webhook_secret, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature.")

    # --- Parse order ---
    try:
        order = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    shopify_order_id = order.get("id")
    if not shopify_order_id:
        return {"status": "ignored", "reason": "missing_order_id"}

    order_id = f"shopify:{shopify_order_id}"

    # --- Extract click_id from note_attributes ---
    note_attributes = order.get("note_attributes", [])
    click_id_raw = _extract_click_id_from_note_attributes(note_attributes)

    if not click_id_raw:
        # Organic order (no influencer attribution) — return 200 to avoid Shopify retries
        logger.debug("shopify_order_no_click_id", order_id=order_id)
        return {"status": "ignored", "reason": "no_click_id"}

    # --- Verify click_id signature ---
    click = verify_click_id(click_id_raw)
    if click is None:
        logger.warning("shopify_order_invalid_click_id", order_id=order_id, click_id=click_id_raw)
        return {"status": "ignored", "reason": "invalid_click_id"}

    # --- Idempotency: check if conversion already exists ---
    existing_stmt = select(ConversionEvent).where(ConversionEvent.order_id == order_id)
    existing = await db.execute(existing_stmt)
    if existing.scalar_one_or_none():
        logger.info("shopify_order_duplicate", order_id=order_id)
        return {"status": "duplicate", "order_id": order_id}

    # --- Extract revenue ---
    total_price = order.get("total_price", "0")
    revenue_cents = _shopify_money_to_cents(total_price)
    currency = order.get("currency", "USD")

    # --- Create ConversionEvent ---
    event = ConversionEvent(
        click_id=click_id_raw,
        organization_id=store.organization_id,
        event_type="purchase",
        order_id=order_id,
        revenue_cents=revenue_cents,
        currency=currency,
        metadata_={
            "source": "shopify_webhook",
            "shopify_order_number": order.get("order_number"),
            "shop_domain": shop_domain,
        },
    )
    db.add(event)
    await db.commit()

    logger.info(
        "shopify_conversion_created",
        order_id=order_id,
        click_id=click_id_raw,
        revenue_cents=revenue_cents,
        org=str(store.organization_id),
    )
    return {"status": "ok", "order_id": order_id}


# ---------------------------------------------------------------------------
# Webhook: orders/refund (refunds/create)
# ---------------------------------------------------------------------------

@router.post("/webhooks/orders-refund", status_code=200)
async def webhook_orders_refund(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    # --- Identify the store ---
    shop_domain = request.headers.get("X-Shopify-Shop-Domain", "")
    store = await _get_store_by_domain(db, shop_domain)
    if not store:
        logger.warning("shopify_refund_unknown_store", shop_domain=shop_domain)
        return {"status": "ignored", "reason": "unknown_store"}

    # --- Verify HMAC ---
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not _verify_shopify_hmac(body, store.webhook_secret, hmac_header):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature.")

    # --- Parse refund ---
    try:
        refund = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    shopify_order_id = refund.get("order_id")
    shopify_refund_id = refund.get("id")
    if not shopify_order_id:
        return {"status": "ignored", "reason": "missing_order_id"}

    order_id = f"shopify:{shopify_order_id}"
    refund_order_id = f"shopify_refund:{shopify_refund_id}" if shopify_refund_id else None

    # --- Find original ConversionEvent ---
    conv_stmt = select(ConversionEvent).where(ConversionEvent.order_id == order_id)
    conv_result = await db.execute(conv_stmt)
    original_conversion = conv_result.scalar_one_or_none()

    if not original_conversion:
        # No attributed conversion for this order — ignore
        logger.debug("shopify_refund_no_conversion", order_id=order_id)
        return {"status": "ignored", "reason": "no_original_conversion"}

    # --- Idempotency: check if refund already exists ---
    if refund_order_id:
        existing_stmt = select(RefundEvent).where(RefundEvent.original_order_id == refund_order_id)
        existing = await db.execute(existing_stmt)
        if existing.scalar_one_or_none():
            logger.info("shopify_refund_duplicate", refund_id=refund_order_id)
            return {"status": "duplicate", "refund_id": refund_order_id}

    # --- Calculate refund amount ---
    refund_amount_cents = 0
    for transaction in refund.get("transactions", []):
        if transaction.get("kind") == "refund":
            refund_amount_cents += _shopify_money_to_cents(transaction.get("amount", "0"))

    # Fallback: if no transactions, sum refund_line_items
    if refund_amount_cents == 0:
        for line in refund.get("refund_line_items", []):
            refund_amount_cents += _shopify_money_to_cents(line.get("subtotal", "0"))

    # --- Create RefundEvent ---
    event = RefundEvent(
        click_id=original_conversion.click_id,
        organization_id=original_conversion.organization_id,
        original_order_id=refund_order_id or order_id,
        refund_amount_cents=refund_amount_cents,
        reason=f"shopify_refund:{shopify_refund_id}",
    )
    db.add(event)
    await db.commit()

    logger.info(
        "shopify_refund_created",
        order_id=order_id,
        refund_id=refund_order_id,
        refund_amount_cents=refund_amount_cents,
        click_id=original_conversion.click_id,
    )
    return {"status": "ok", "order_id": order_id}


# ---------------------------------------------------------------------------
# Setup: connect a Shopify store
# ---------------------------------------------------------------------------

class ShopifyConnectRequest(BaseModel):
    shop_domain: str
    access_token: str


@router.post("/connect", status_code=201)
async def connect_shopify_store(
    payload: ShopifyConnectRequest,
    auth: AuthContext = Depends(require_secret_key),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    shop_domain = payload.shop_domain.strip().lower()

    # --- Validate access token against Shopify Admin API ---
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"https://{shop_domain}/admin/api/{settings.shopify_api_version}/shop.json",
                headers={"X-Shopify-Access-Token": payload.access_token},
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=400, detail=f"Cannot reach Shopify store: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Shopify returned {resp.status_code}. Check shop_domain and access_token.",
        )

    # --- Check if store already connected ---
    existing_stmt = select(ShopifyStore).where(ShopifyStore.shop_domain == shop_domain)
    existing_result = await db.execute(existing_stmt)
    existing_store = existing_result.scalar_one_or_none()

    if existing_store:
        raise HTTPException(
            status_code=409,
            detail=f"Store {shop_domain} is already connected.",
        )

    # --- Generate webhook secret ---
    webhook_secret = secrets.token_urlsafe(32)

    # --- Store access token (base64 for v1 — TODO: Fernet/KMS) ---
    access_token_encrypted = base64.b64encode(payload.access_token.encode()).decode()

    # --- Create ShopifyStore record ---
    store = ShopifyStore(
        organization_id=auth.organization_id,
        shop_domain=shop_domain,
        access_token_encrypted=access_token_encrypted,
        webhook_secret=webhook_secret,
        is_active=True,
    )
    db.add(store)
    await db.flush()  # get store.id before registering webhooks

    # --- Register webhooks with Shopify ---
    webhook_base = f"{settings.base_url}/v1/shopify/webhooks"
    webhooks_to_register = [
        {"topic": "orders/create", "address": f"{webhook_base}/orders-create"},
        {"topic": "refunds/create", "address": f"{webhook_base}/orders-refund"},
    ]

    async with httpx.AsyncClient() as client:
        for wh in webhooks_to_register:
            try:
                resp = await client.post(
                    f"https://{shop_domain}/admin/api/{settings.shopify_api_version}/webhooks.json",
                    headers={"X-Shopify-Access-Token": payload.access_token},
                    json={
                        "webhook": {
                            "topic": wh["topic"],
                            "address": wh["address"],
                            "format": "json",
                        }
                    },
                    timeout=10.0,
                )
                if resp.status_code not in (200, 201):
                    logger.warning(
                        "shopify_webhook_register_failed",
                        topic=wh["topic"],
                        status=resp.status_code,
                        body=resp.text[:500],
                    )
            except httpx.RequestError as e:
                logger.warning("shopify_webhook_register_error", topic=wh["topic"], error=str(e))

    await db.commit()

    logger.info(
        "shopify_store_connected",
        shop_domain=shop_domain,
        org=str(auth.organization_id),
    )
    return {
        "status": "ok",
        "shop_domain": shop_domain,
        "webhook_secret": webhook_secret,
        "message": "Store connected. Webhooks registered.",
    }
