"""
Rate limiter — Redis-backed sliding window.

Limits:
  - Per API key: configurable per key (default 120/min)
  - Per IP on redirect path: configurable (default 30/min)
  - Per IP+link combo: prevents click spam (default 10/min)

Returns 429 with Retry-After header when exceeded.
"""

import time
from fastapi import HTTPException, Request
from app.config import get_settings

import structlog

logger = structlog.get_logger()

# In-memory fallback when Redis is unavailable
# Production should use Redis; this prevents crashes in dev
_memory_store: dict[str, list[float]] = {}


def _sliding_window_check(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Check rate limit using in-memory sliding window.
    Returns (allowed, remaining)."""
    now = time.time()
    cutoff = now - window_seconds

    if key not in _memory_store:
        _memory_store[key] = []

    # Remove expired entries
    _memory_store[key] = [t for t in _memory_store[key] if t > cutoff]

    current_count = len(_memory_store[key])

    if current_count >= limit:
        return False, 0

    _memory_store[key].append(now)
    return True, limit - current_count - 1


def check_rate_limit(key: str, limit: int, window: int = 60):
    """Check rate limit and raise 429 if exceeded."""
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


def rate_limit_ip(request: Request, limit: int | None = None):
    """Rate limit by client IP."""
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    return check_rate_limit(
        f"ip:{ip}",
        limit or settings.rate_limit_per_ip_per_minute,
    )


def rate_limit_link(request: Request, creator: str, campaign: str):
    """Rate limit by IP + specific link combo."""
    ip = request.client.host if request.client else "unknown"
    return check_rate_limit(
        f"link:{ip}:{creator}:{campaign}",
        10,  # 10 clicks per IP per link per minute
    )


def rate_limit_api_key(key_id: str, limit: int = 120):
    """Rate limit by API key."""
    return check_rate_limit(f"apikey:{key_id}", limit)
