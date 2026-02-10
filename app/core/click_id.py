"""
Click ID minting & verification.

Format:  {uuid}:{expiry_ts}:{hmac_sig}
- uuid       → unique click identifier (UUIDv7 for time-sortability)
- expiry_ts  → unix timestamp when this click_id expires
- hmac_sig   → HMAC-SHA256(uuid:expiry_ts, secret), hex-truncated to 16 chars

Downstream events referencing an invalid/expired click_id are non-billable.
"""

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

from app.config import get_settings


def _uuid7() -> str:
    """Generate a UUIDv7 (time-ordered) as hex string.
    Falls back to uuid4 if uuid7 isn't available (Python <3.13)."""
    try:
        return uuid.uuid7().hex
    except AttributeError:
        # Pre-3.13: use uuid4 (still globally unique, just not time-sorted)
        return uuid.uuid4().hex


def _sign(payload: str, secret: str) -> str:
    """HMAC-SHA256, truncated to 16 hex chars."""
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return sig[:16]


@dataclass(frozen=True)
class ClickId:
    uid: str
    expiry: int
    signature: str

    def __str__(self) -> str:
        return f"{self.uid}:{self.expiry}:{self.signature}"

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expiry


def mint_click_id() -> ClickId:
    """Create a new signed click_id."""
    settings = get_settings()
    uid = _uuid7()
    expiry = int(time.time()) + settings.click_id_expiry_seconds
    payload = f"{uid}:{expiry}"
    sig = _sign(payload, settings.click_id_secret)
    return ClickId(uid=uid, expiry=expiry, signature=sig)


def verify_click_id(raw: str) -> ClickId | None:
    """Parse and verify a click_id string.
    Returns ClickId if valid and not expired, else None."""
    settings = get_settings()
    parts = raw.split(":")
    if len(parts) != 3:
        return None

    uid, expiry_str, sig = parts
    try:
        expiry = int(expiry_str)
    except ValueError:
        return None

    # Check signature
    expected = _sign(f"{uid}:{expiry}", settings.click_id_secret)
    if not hmac.compare_digest(sig, expected):
        return None

    click = ClickId(uid=uid, expiry=expiry, signature=sig)

    # Check expiry
    if click.is_expired:
        return None

    return click
