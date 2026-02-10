"""
Bot detection — Layer 1 (MVP).

Produces a risk_score 0.0–1.0:
  0.0  = definitely human
  1.0  = definitely bot

Layers:
  1. User-Agent blocklist / parsing
  2. Header sanity (Accept-Language, Sec-Fetch-*)
  3. Datacenter ASN flagging (stubbed for now, filled by GeoIP later)
  4. Rate-limit signals (passed in from middleware)

Design: suspicious traffic is NOT blocked — it's scored.
Billing policy decides what's billable downstream.
"""

from dataclasses import dataclass, field
from user_agents import parse as parse_ua
import re

# --- Known bot UA substrings (hard block = risk 1.0) ---
HARD_BLOCK_UA_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"curl/",
        r"wget/",
        r"python-requests",
        r"python-urllib",
        r"Go-http-client",
        r"scrapy",
        r"aiohttp",
        r"node-fetch",
        r"axios/",
        r"java/",
        r"libwww-perl",
        r"HeadlessChrome",
        r"PhantomJS",
        r"Selenium",
        r"puppeteer",
    ]
]

# Known search/social bots (not malicious, but not billable)
KNOWN_BOT_UA_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"Googlebot",
        r"bingbot",
        r"Slurp",
        r"DuckDuckBot",
        r"facebookexternalhit",
        r"Twitterbot",
        r"LinkedInBot",
        r"Slackbot",
        r"TelegramBot",
        r"Discordbot",
        r"WhatsApp",
    ]
]

# Known datacenter / cloud ASNs (flag, don't block)
DATACENTER_ASNS: set[int] = {
    14061,   # DigitalOcean
    16509,   # Amazon AWS
    15169,   # Google Cloud
    8075,    # Microsoft Azure
    13335,   # Cloudflare
    20473,   # Vultr
    63949,   # Linode/Akamai
    14618,   # Amazon
    396982,  # Google
}


@dataclass
class BotSignals:
    """Raw signals collected during bot analysis."""
    ua_blocked: bool = False
    ua_is_known_bot: bool = False
    ua_is_bot_lib: bool = False  # python-requests, etc.
    missing_accept_language: bool = False
    missing_sec_fetch: bool = False
    is_datacenter_ip: bool = False
    rate_limited: bool = False
    # Extensible: add JS proof, captcha, etc. later
    details: dict = field(default_factory=dict)


@dataclass
class BotVerdict:
    risk_score: float
    should_block: bool  # hard block (don't even redirect)
    signals: BotSignals
    reason: str = ""


def score_request(
    user_agent: str | None,
    headers: dict[str, str],
    asn: int | None = None,
    rate_limited: bool = False,
) -> BotVerdict:
    """Compute bot risk score from request metadata."""
    signals = BotSignals()
    score = 0.0

    ua_str = user_agent or ""

    # --- Layer 1: UA blocklist ---
    for pattern in HARD_BLOCK_UA_PATTERNS:
        if pattern.search(ua_str):
            signals.ua_blocked = True
            return BotVerdict(
                risk_score=1.0,
                should_block=True,
                signals=signals,
                reason=f"Blocked UA: {pattern.pattern}",
            )

    # Known (benign) bots
    for pattern in KNOWN_BOT_UA_PATTERNS:
        if pattern.search(ua_str):
            signals.ua_is_known_bot = True
            score += 0.6

    # UA library detection via user-agents lib
    if ua_str:
        parsed = parse_ua(ua_str)
        if parsed.is_bot:
            signals.ua_is_bot_lib = True
            score += 0.4

    # --- Layer 2: Header sanity ---
    if not headers.get("accept-language"):
        signals.missing_accept_language = True
        score += 0.15

    # Sec-Fetch-* headers (present in real browsers since ~2020)
    has_sec_fetch = any(k.lower().startswith("sec-fetch") for k in headers)
    if not has_sec_fetch and ua_str and "Mozilla" in ua_str:
        # Claims to be a browser but missing Sec-Fetch → suspicious
        signals.missing_sec_fetch = True
        score += 0.2

    # --- Layer 3: Datacenter ASN ---
    if asn and asn in DATACENTER_ASNS:
        signals.is_datacenter_ip = True
        score += 0.25

    # --- Layer 4: Rate limit ---
    if rate_limited:
        signals.rate_limited = True
        score += 0.3

    # Clamp
    score = min(score, 1.0)

    return BotVerdict(
        risk_score=round(score, 3),
        should_block=False,
        signals=signals,
        reason="",
    )
