"""Tests for Shopify integration — helpers, HMAC, webhooks, idempotency."""

import base64
import hashlib
import hmac as hmac_mod
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.shopify import (
    _extract_click_id_from_note_attributes,
    _shopify_money_to_cents,
    _verify_shopify_hmac,
)
from app.core.click_id import mint_click_id


# ---------------------------------------------------------------------------
# Helper: _verify_shopify_hmac
# ---------------------------------------------------------------------------

class TestVerifyShopifyHmac:
    def _sign(self, body: bytes, secret: str) -> str:
        digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def test_valid_hmac_accepted(self):
        secret = "my-webhook-secret"
        body = b'{"id": 123}'
        sig = self._sign(body, secret)
        assert _verify_shopify_hmac(body, secret, sig) is True

    def test_wrong_secret_rejected(self):
        body = b'{"id": 123}'
        sig = self._sign(body, "correct-secret")
        assert _verify_shopify_hmac(body, "wrong-secret", sig) is False

    def test_tampered_body_rejected(self):
        secret = "my-webhook-secret"
        sig = self._sign(b'{"id": 123}', secret)
        assert _verify_shopify_hmac(b'{"id": 999}', secret, sig) is False

    def test_empty_hmac_header_rejected(self):
        body = b'{"id": 123}'
        assert _verify_shopify_hmac(body, "secret", "") is False

    def test_empty_body(self):
        secret = "s"
        sig = self._sign(b"", secret)
        assert _verify_shopify_hmac(b"", secret, sig) is True


# ---------------------------------------------------------------------------
# Helper: _extract_click_id_from_note_attributes
# ---------------------------------------------------------------------------

class TestExtractClickId:
    def test_extracts_click_id(self):
        attrs = [
            {"name": "gift_message", "value": "Happy birthday"},
            {"name": "inf_click_id", "value": "abc:123:def"},
        ]
        assert _extract_click_id_from_note_attributes(attrs) == "abc:123:def"

    def test_returns_none_when_missing(self):
        attrs = [{"name": "gift_message", "value": "Hi"}]
        assert _extract_click_id_from_note_attributes(attrs) is None

    def test_returns_none_for_empty_list(self):
        assert _extract_click_id_from_note_attributes([]) is None

    def test_returns_none_for_none(self):
        assert _extract_click_id_from_note_attributes(None) is None

    def test_strips_whitespace(self):
        attrs = [{"name": "inf_click_id", "value": "  abc:123:def  "}]
        assert _extract_click_id_from_note_attributes(attrs) == "abc:123:def"

    def test_ignores_empty_string_value(self):
        attrs = [{"name": "inf_click_id", "value": ""}]
        assert _extract_click_id_from_note_attributes(attrs) is None

    def test_ignores_whitespace_only_value(self):
        attrs = [{"name": "inf_click_id", "value": "   "}]
        assert _extract_click_id_from_note_attributes(attrs) is None

    def test_ignores_non_string_value(self):
        attrs = [{"name": "inf_click_id", "value": 12345}]
        assert _extract_click_id_from_note_attributes(attrs) is None


# ---------------------------------------------------------------------------
# Helper: _shopify_money_to_cents
# ---------------------------------------------------------------------------

class TestShopifyMoneyToCents:
    def test_whole_dollars(self):
        assert _shopify_money_to_cents("29.00") == 2900

    def test_dollars_and_cents(self):
        assert _shopify_money_to_cents("29.99") == 2999

    def test_zero(self):
        assert _shopify_money_to_cents("0") == 0
        assert _shopify_money_to_cents("0.00") == 0

    def test_large_amount(self):
        assert _shopify_money_to_cents("1234.56") == 123456

    def test_single_cent(self):
        assert _shopify_money_to_cents("0.01") == 1

    def test_invalid_string_returns_zero(self):
        assert _shopify_money_to_cents("not-a-number") == 0

    def test_none_returns_zero(self):
        assert _shopify_money_to_cents(None) == 0

    def test_empty_string_returns_zero(self):
        assert _shopify_money_to_cents("") == 0

    def test_rounding(self):
        # 19.995 should round to 2000 cents, not 1999
        assert _shopify_money_to_cents("19.995") == 2000


# ---------------------------------------------------------------------------
# Webhook endpoint integration tests (using FastAPI TestClient)
# ---------------------------------------------------------------------------

# We need to set up an in-process ASGI test client that hits the real
# router but with a mocked database session.

def _make_hmac(body: bytes, secret: str) -> str:
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _make_store(org_id=None, domain="test-store.myshopify.com", secret="webhook-secret-123"):
    """Create a mock ShopifyStore object."""
    store = MagicMock()
    store.organization_id = org_id or uuid4()
    store.shop_domain = domain
    store.webhook_secret = secret
    store.is_active = True
    return store


def _make_order_body(order_id=5551234, click_id=None, total_price="49.99", currency="USD"):
    """Build a Shopify order webhook payload."""
    note_attributes = []
    if click_id:
        note_attributes.append({"name": "inf_click_id", "value": click_id})
    return {
        "id": order_id,
        "order_number": 1001,
        "total_price": total_price,
        "currency": currency,
        "note_attributes": note_attributes,
    }


def _make_refund_body(order_id=5551234, refund_id=9991, amount="10.00"):
    """Build a Shopify refund webhook payload."""
    return {
        "id": refund_id,
        "order_id": order_id,
        "transactions": [{"kind": "refund", "amount": amount}],
    }


@pytest.fixture
def valid_click_id():
    """Mint a real, valid click_id for testing."""
    return str(mint_click_id())


class TestWebhookOrdersCreate:
    """Test POST /v1/shopify/webhooks/orders-create"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        # Import here so conftest env vars are already set
        from fastapi.testclient import TestClient
        from app.api.shopify import router
        from fastapi import FastAPI

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.store = _make_store()
        self.secret = self.store.webhook_secret

    def _post_order(self, order_body, store=None, db_mocks=None):
        """Send an order webhook with valid HMAC."""
        store = store or self.store
        body_bytes = json.dumps(order_body).encode()
        sig = _make_hmac(body_bytes, store.webhook_secret)

        # Mock the DB dependency
        mock_db = AsyncMock(spec=["execute", "add", "commit", "flush"])

        # Default: _get_store_by_domain returns our store
        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = store

        # Default: idempotency check returns None (no duplicate)
        no_dup_result = MagicMock()
        no_dup_result.scalar_one_or_none.return_value = None

        execute_results = [store_result, no_dup_result]
        if db_mocks:
            execute_results = db_mocks

        mock_db.execute = AsyncMock(side_effect=execute_results)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # Override get_db dependency
        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp = self.client.post(
            "/v1/shopify/webhooks/orders-create",
            content=body_bytes,
            headers={
                "X-Shopify-Shop-Domain": store.shop_domain,
                "X-Shopify-Hmac-Sha256": sig,
                "Content-Type": "application/json",
            },
        )
        return resp, mock_db

    def test_valid_order_creates_conversion(self, valid_click_id):
        order = _make_order_body(click_id=valid_click_id, total_price="49.99")
        resp, mock_db = self._post_order(order)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["order_id"] == "shopify:5551234"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

        # Verify the ConversionEvent was built correctly
        event = mock_db.add.call_args[0][0]
        assert event.click_id == valid_click_id
        assert event.organization_id == self.store.organization_id
        assert event.event_type == "purchase"
        assert event.order_id == "shopify:5551234"
        assert event.revenue_cents == 4999
        assert event.currency == "USD"

    def test_unknown_store_returns_ignored(self, valid_click_id):
        order = _make_order_body(click_id=valid_click_id)
        body_bytes = json.dumps(order).encode()

        mock_db = AsyncMock()
        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=store_result)

        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp = self.client.post(
            "/v1/shopify/webhooks/orders-create",
            content=body_bytes,
            headers={
                "X-Shopify-Shop-Domain": "unknown.myshopify.com",
                "X-Shopify-Hmac-Sha256": "bogus",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["reason"] == "unknown_store"

    def test_invalid_hmac_returns_401(self, valid_click_id):
        order = _make_order_body(click_id=valid_click_id)
        body_bytes = json.dumps(order).encode()

        mock_db = AsyncMock()
        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store
        mock_db.execute = AsyncMock(return_value=store_result)

        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp = self.client.post(
            "/v1/shopify/webhooks/orders-create",
            content=body_bytes,
            headers={
                "X-Shopify-Shop-Domain": self.store.shop_domain,
                "X-Shopify-Hmac-Sha256": "definitely-wrong-hmac",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_organic_order_no_click_id_ignored(self):
        order = _make_order_body(click_id=None)
        resp, _ = self._post_order(order)

        assert resp.status_code == 200
        assert resp.json()["reason"] == "no_click_id"

    def test_invalid_click_id_ignored(self):
        order = _make_order_body(click_id="tampered:0:0000000000000000")
        resp, _ = self._post_order(order)

        assert resp.status_code == 200
        assert resp.json()["reason"] == "invalid_click_id"

    def test_duplicate_order_returns_duplicate(self, valid_click_id):
        order = _make_order_body(click_id=valid_click_id)

        # Mock: store found, then idempotency check finds existing conversion
        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = MagicMock()  # existing conversion

        resp, mock_db = self._post_order(order, db_mocks=[store_result, dup_result])

        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"
        mock_db.add.assert_not_called()

    def test_revenue_extracted_correctly(self, valid_click_id):
        order = _make_order_body(click_id=valid_click_id, total_price="129.50", currency="CAD")
        resp, mock_db = self._post_order(order)

        assert resp.status_code == 200
        event = mock_db.add.call_args[0][0]
        assert event.revenue_cents == 12950
        assert event.currency == "CAD"


class TestWebhookOrdersRefund:
    """Test POST /v1/shopify/webhooks/orders-refund"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from fastapi.testclient import TestClient
        from app.api.shopify import router
        from fastapi import FastAPI

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.store = _make_store()

    def _post_refund(self, refund_body, store=None, db_mocks=None):
        store = store or self.store
        body_bytes = json.dumps(refund_body).encode()
        sig = _make_hmac(body_bytes, store.webhook_secret)

        mock_db = AsyncMock(spec=["execute", "add", "commit", "flush"])

        if db_mocks:
            mock_db.execute = AsyncMock(side_effect=db_mocks)
        else:
            # Default: store found, conversion found, no duplicate refund
            store_result = MagicMock()
            store_result.scalar_one_or_none.return_value = store

            conv_result = MagicMock()
            conv_mock = MagicMock()
            conv_mock.click_id = "test-click-id"
            conv_mock.organization_id = store.organization_id
            conv_result.scalar_one_or_none.return_value = conv_mock

            no_dup_result = MagicMock()
            no_dup_result.scalar_one_or_none.return_value = None

            mock_db.execute = AsyncMock(side_effect=[store_result, conv_result, no_dup_result])

        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp = self.client.post(
            "/v1/shopify/webhooks/orders-refund",
            content=body_bytes,
            headers={
                "X-Shopify-Shop-Domain": store.shop_domain,
                "X-Shopify-Hmac-Sha256": sig,
                "Content-Type": "application/json",
            },
        )
        return resp, mock_db

    def test_valid_refund_creates_refund_event(self):
        refund = _make_refund_body(amount="10.00")
        resp, mock_db = self._post_refund(refund)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_db.add.assert_called_once()

        event = mock_db.add.call_args[0][0]
        assert event.click_id == "test-click-id"
        assert event.refund_amount_cents == 1000
        assert event.original_order_id == "shopify_refund:9991"

    def test_refund_no_original_conversion_ignored(self):
        refund = _make_refund_body()

        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store

        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = None  # no conversion

        resp, mock_db = self._post_refund(refund, db_mocks=[store_result, conv_result])

        assert resp.status_code == 200
        assert resp.json()["reason"] == "no_original_conversion"
        mock_db.add.assert_not_called()

    def test_duplicate_refund_returns_duplicate(self):
        refund = _make_refund_body()

        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store

        conv_result = MagicMock()
        conv_mock = MagicMock()
        conv_mock.click_id = "test-click-id"
        conv_mock.organization_id = self.store.organization_id
        conv_result.scalar_one_or_none.return_value = conv_mock

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = MagicMock()  # existing refund

        resp, mock_db = self._post_refund(
            refund, db_mocks=[store_result, conv_result, dup_result]
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"
        mock_db.add.assert_not_called()

    def test_refund_invalid_hmac_returns_401(self):
        refund = _make_refund_body()
        body_bytes = json.dumps(refund).encode()

        mock_db = AsyncMock()
        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store
        mock_db.execute = AsyncMock(return_value=store_result)

        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp = self.client.post(
            "/v1/shopify/webhooks/orders-refund",
            content=body_bytes,
            headers={
                "X-Shopify-Shop-Domain": self.store.shop_domain,
                "X-Shopify-Hmac-Sha256": "wrong-hmac",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_refund_with_line_items_fallback(self):
        """When transactions array has no refund entries, fall back to refund_line_items."""
        refund = {
            "id": 9991,
            "order_id": 5551234,
            "transactions": [],
            "refund_line_items": [
                {"subtotal": "15.00"},
                {"subtotal": "5.50"},
            ],
        }
        resp, mock_db = self._post_refund(refund)

        assert resp.status_code == 200
        event = mock_db.add.call_args[0][0]
        assert event.refund_amount_cents == 2050


class TestFullFlow:
    """End-to-end: order webhook → conversion, then refund webhook → refund event."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from fastapi.testclient import TestClient
        from app.api.shopify import router
        from fastapi import FastAPI

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.store = _make_store()

    def test_order_then_refund(self, valid_click_id):
        org_id = self.store.organization_id

        # --- Step 1: Send order webhook ---
        order = _make_order_body(order_id=7777, click_id=valid_click_id, total_price="99.00")
        order_bytes = json.dumps(order).encode()
        order_sig = _make_hmac(order_bytes, self.store.webhook_secret)

        mock_db = AsyncMock(spec=["execute", "add", "commit", "flush"])

        store_result = MagicMock()
        store_result.scalar_one_or_none.return_value = self.store
        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[store_result, no_dup])
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        from app.models.database import get_db
        self.app.dependency_overrides[get_db] = lambda: mock_db

        resp1 = self.client.post(
            "/v1/shopify/webhooks/orders-create",
            content=order_bytes,
            headers={
                "X-Shopify-Shop-Domain": self.store.shop_domain,
                "X-Shopify-Hmac-Sha256": order_sig,
                "Content-Type": "application/json",
            },
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "ok"

        # Capture the created ConversionEvent
        created_conversion = mock_db.add.call_args[0][0]
        assert created_conversion.order_id == "shopify:7777"
        assert created_conversion.revenue_cents == 9900
        assert created_conversion.click_id == valid_click_id

        # --- Step 2: Send refund webhook ---
        refund = _make_refund_body(order_id=7777, refund_id=8888, amount="30.00")
        refund_bytes = json.dumps(refund).encode()
        refund_sig = _make_hmac(refund_bytes, self.store.webhook_secret)

        mock_db2 = AsyncMock(spec=["execute", "add", "commit", "flush"])

        store_result2 = MagicMock()
        store_result2.scalar_one_or_none.return_value = self.store

        # Return the conversion from step 1
        conv_result = MagicMock()
        conv_mock = MagicMock()
        conv_mock.click_id = valid_click_id
        conv_mock.organization_id = org_id
        conv_result.scalar_one_or_none.return_value = conv_mock

        no_dup2 = MagicMock()
        no_dup2.scalar_one_or_none.return_value = None

        mock_db2.execute = AsyncMock(side_effect=[store_result2, conv_result, no_dup2])
        mock_db2.commit = AsyncMock()
        mock_db2.add = MagicMock()

        self.app.dependency_overrides[get_db] = lambda: mock_db2

        resp2 = self.client.post(
            "/v1/shopify/webhooks/orders-refund",
            content=refund_bytes,
            headers={
                "X-Shopify-Shop-Domain": self.store.shop_domain,
                "X-Shopify-Hmac-Sha256": refund_sig,
                "Content-Type": "application/json",
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "ok"

        refund_event = mock_db2.add.call_args[0][0]
        assert refund_event.click_id == valid_click_id
        assert refund_event.refund_amount_cents == 3000
        assert refund_event.original_order_id == "shopify_refund:8888"
