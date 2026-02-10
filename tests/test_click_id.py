"""Tests for click_id minting and verification."""

import time
from unittest.mock import patch

import pytest
from app.core.click_id import ClickId, mint_click_id, verify_click_id


def test_mint_returns_valid_click_id():
    cid = mint_click_id()
    assert isinstance(cid, ClickId)
    assert cid.uid
    assert cid.expiry > time.time()
    assert len(cid.signature) == 16


def test_roundtrip_mint_verify():
    cid = mint_click_id()
    raw = str(cid)
    verified = verify_click_id(raw)
    assert verified is not None
    assert verified.uid == cid.uid
    assert verified.expiry == cid.expiry
    assert verified.signature == cid.signature


def test_tampered_signature_rejected():
    cid = mint_click_id()
    raw = f"{cid.uid}:{cid.expiry}:{'0' * 16}"
    assert verify_click_id(raw) is None


def test_tampered_expiry_rejected():
    cid = mint_click_id()
    raw = f"{cid.uid}:{cid.expiry + 9999}:{cid.signature}"
    assert verify_click_id(raw) is None


def test_expired_click_id_rejected():
    cid = mint_click_id()
    # Force expiry into the past
    expired_raw = f"{cid.uid}:{int(time.time()) - 100}:placeholder"
    # Re-sign with correct sig for the past expiry
    from app.core.click_id import _sign
    from app.config import get_settings
    settings = get_settings()
    past_expiry = int(time.time()) - 100
    sig = _sign(f"{cid.uid}:{past_expiry}", settings.click_id_secret)
    expired_raw = f"{cid.uid}:{past_expiry}:{sig}"
    assert verify_click_id(expired_raw) is None


def test_malformed_strings_rejected():
    assert verify_click_id("") is None
    assert verify_click_id("just-one-part") is None
    assert verify_click_id("a:b") is None
    assert verify_click_id("a:not-a-number:c") is None
    assert verify_click_id("a:b:c:d") is None


def test_click_id_str_format():
    cid = mint_click_id()
    parts = str(cid).split(":")
    assert len(parts) == 3
