"""
Rate limiter — sliding window + 3-second dedupe.

Limits:
  - Per API key: configurable (default 120/min)
  - Per IP on redirect path: configurable (default 30/min)
  - Per IP+link combo: prevents click spam (default 10/min)

Dedupe:
  - Same IP + slug + UA within 3 seconds = suspected bot / double-click
"""

import hashlib
import time
from fastapi import HTTPException, Request
from app.config import get_settings

import structlog

logger = structlog.get_logger()

_memory_store: dict[str, list[float]] = {}
_dedupe_store: dict[str, float] = {}


def _sliding_window_check(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - window_seconds

    if key not in _memory_store:
        _memory_store[key] = []

    _memory_store[key] = [t for t in _memory_store[key] if t > cutoff]
    current_count = len(_memory_store[key])

    if current_count >= limit:
        return False, 0

    _memory_store[key].append(now)
    return True, limit - current_count - 1


def check_rate_limit(key: str, limit: int, window: int = 60):
    allowed, remaining = _sliding_window_check(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Slow down.",
            headers={
                "Retry-After": str(window),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return remaining


def check_dedupe(ip: str, slug: str, ua: str, window_seconds: int = 3) -> bool:
    """
    Same IP + slug + UA within 3 seconds = suspected bot / double-click.
    Returns True if duplicate detected.
    """
    sig = hashlib.sha256(f"{ip}:{slug}:{ua}".encode()).hexdigest()[:16]
    key = f"dd:{sig}"
    now = time.time()

    last_seen = _dedupe_store.get(key)
    _dedupe_store[key] = now

    # Periodic cleanup
    if len(_dedupe_store) > 10000:
        cutoff = now - 60
        to_delete = [k for k, v in _dedupe_store.items() if v < cutoff]
        for k in to_delete:
            del _dedupe_store[k]

    if last_seen and (now - last_seen) < window_seconds:
        logger.info("dedupe_hit", ip_hash=sig, slug=slug)
        return True

    return False


def _get_real_ip(request: Request) -> str:
    """Extract real client IP from x-forwarded-for or request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",")]
        for ip in ips:
            if not ip.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                                  "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                                  "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                                  "172.30.", "172.31.", "192.168.", "127.", "::1")):
                return ip
        return ips[0]
    return request.client.host if request.client else "unknown"


def rate_limit_ip(request: Request, limit: int | None = None):
    settings = get_settings()
    ip = _get_real_ip(request)
    return check_rate_limit(
        f"ip:{ip}",
        limit or settings.rate_limit_per_ip_per_minute,
    )


def rate_limit_link(request: Request, creator: str, campaign: str):
    ip = _get_real_ip(request)
    return check_rate_limit(
        f"link:{ip}:{creator}:{campaign}",
        10,
    )


def rate_limit_api_key(key_id: str, limit: int = 120):
    return check_rate_limit(f"apikey:{key_id}", limit)
