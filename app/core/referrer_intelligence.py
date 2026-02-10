"""
Referrer Intelligence — extract maximum context from every click.

Classifies:
  - Source platform (instagram, tiktok, youtube, twitter, facebook, etc.)
  - Source medium (social, search, email, messaging, direct, paid, referral)
  - In-app browser detection (more reliable than referer for social platforms)
  - Referrer path parsing (post, story, bio, DM, feed)
  - Language and locale from Accept-Language
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ClickIntelligence:
    """Everything we can extract from a single click request."""

    # Source classification
    source_platform: str = "direct"       # instagram, tiktok, youtube, twitter, facebook, google, email, etc.
    source_medium: str = "direct"         # social, search, email, messaging, paid, referral, direct
    source_detail: str | None = None      # story, bio, feed, dm, post, comment, search_organic, etc.

    # In-app browser
    is_in_app_browser: bool = False
    in_app_platform: str | None = None    # which app's webview

    # Device enrichment
    device_class: str = "unknown"         # mobile, desktop, tablet
    os_family: str = "unknown"
    os_version: str | None = None
    browser_family: str = "unknown"
    browser_version: str | None = None
    is_mobile: bool = False

    # Geo (from Accept-Language as fallback)
    language: str | None = None
    locale: str | None = None

    # Raw referer parsing
    referer_domain: str | None = None
    referer_path: str | None = None
    referer_full: str | None = None


# --- In-App Browser Detection ---
# These UA substrings identify specific platform webviews

IN_APP_PATTERNS = {
    "instagram":  [r"Instagram", r"FBAN/FBIOS.*Instagram"],
    "tiktok":     [r"BytedanceWebview", r"ByteLocale", r"musical_ly", r"TikTok"],
    "facebook":   [r"FBAN/", r"FBAV/", r"FB_IAB", r"\[FB"],
    "snapchat":   [r"Snapchat"],
    "twitter":    [r"Twitter", r"TwitterAndroid"],
    "linkedin":   [r"LinkedInApp"],
    "pinterest":  [r"Pinterest"],
    "reddit":     [r"Reddit/"],
    "telegram":   [r"TelegramBot", r"Telegram"],
    "whatsapp":   [r"WhatsApp"],
    "wechat":     [r"MicroMessenger"],
    "line":       [r"Line/"],
    "discord":    [r"Discord"],
    "threads":    [r"Barcelona"],  # Meta Threads uses codename Barcelona
    "youtube":    [r"com.google.android.youtube", r"YouTube"],
}


def _detect_in_app_browser(ua: str) -> tuple[bool, str | None]:
    """Check if the UA string indicates an in-app browser."""
    if not ua:
        return False, None

    for platform, patterns in IN_APP_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, ua, re.IGNORECASE):
                return True, platform

    return False, None


# --- Referer Domain Classification ---

DOMAIN_TO_PLATFORM = {
    # Social
    "instagram.com":    ("instagram", "social"),
    "l.instagram.com":  ("instagram", "social"),
    "www.instagram.com": ("instagram", "social"),
    "tiktok.com":       ("tiktok", "social"),
    "www.tiktok.com":   ("tiktok", "social"),
    "vm.tiktok.com":    ("tiktok", "social"),
    "twitter.com":      ("twitter", "social"),
    "x.com":            ("twitter", "social"),
    "t.co":             ("twitter", "social"),
    "facebook.com":     ("facebook", "social"),
    "www.facebook.com": ("facebook", "social"),
    "m.facebook.com":   ("facebook", "social"),
    "l.facebook.com":   ("facebook", "social"),
    "lm.facebook.com":  ("facebook", "social"),
    "fb.me":            ("facebook", "social"),
    "youtube.com":      ("youtube", "social"),
    "www.youtube.com":  ("youtube", "social"),
    "m.youtube.com":    ("youtube", "social"),
    "youtu.be":         ("youtube", "social"),
    "linkedin.com":     ("linkedin", "social"),
    "www.linkedin.com": ("linkedin", "social"),
    "lnkd.in":          ("linkedin", "social"),
    "pinterest.com":    ("pinterest", "social"),
    "www.pinterest.com": ("pinterest", "social"),
    "pin.it":           ("pinterest", "social"),
    "reddit.com":       ("reddit", "social"),
    "www.reddit.com":   ("reddit", "social"),
    "old.reddit.com":   ("reddit", "social"),
    "snapchat.com":     ("snapchat", "social"),
    "www.snapchat.com": ("snapchat", "social"),
    "threads.net":      ("threads", "social"),
    "www.threads.net":  ("threads", "social"),
    "tumblr.com":       ("tumblr", "social"),
    "www.tumblr.com":   ("tumblr", "social"),

    # Search
    "google.com":       ("google", "search"),
    "www.google.com":   ("google", "search"),
    "google.co.uk":     ("google", "search"),
    "google.ca":        ("google", "search"),
    "bing.com":         ("bing", "search"),
    "www.bing.com":     ("bing", "search"),
    "duckduckgo.com":   ("duckduckgo", "search"),
    "yahoo.com":        ("yahoo", "search"),
    "search.yahoo.com": ("yahoo", "search"),
    "baidu.com":        ("baidu", "search"),
    "www.baidu.com":    ("baidu", "search"),
    "yandex.com":       ("yandex", "search"),

    # Messaging
    "t.me":             ("telegram", "messaging"),
    "web.telegram.org": ("telegram", "messaging"),
    "wa.me":            ("whatsapp", "messaging"),
    "web.whatsapp.com": ("whatsapp", "messaging"),
    "discord.com":      ("discord", "messaging"),
    "discordapp.com":   ("discord", "messaging"),

    # Email
    "mail.google.com":  ("gmail", "email"),
    "outlook.live.com": ("outlook", "email"),
    "outlook.office.com": ("outlook", "email"),
    "mail.yahoo.com":   ("yahoo_mail", "email"),

    # Link shorteners (these indicate shared links)
    "bit.ly":           ("bitly", "referral"),
    "tinyurl.com":      ("tinyurl", "referral"),
    "linktr.ee":        ("linktree", "referral"),
    "beacons.ai":       ("beacons", "referral"),
    "stan.store":       ("stan_store", "referral"),
    "hoo.be":           ("hoobe", "referral"),
    "snipfeed.co":      ("snipfeed", "referral"),
    "campsite.bio":     ("campsite", "referral"),
    "tap.bio":          ("tapbio", "referral"),
}


def _classify_referer(referer: str | None) -> tuple[str, str, str | None, str | None, str | None]:
    """Classify referer into platform, medium, detail, domain, path."""
    if not referer:
        return "direct", "direct", None, None, None

    try:
        parsed = urlparse(referer)
        domain = parsed.netloc.lower().lstrip("www.")
        path = parsed.path
    except Exception:
        return "unknown", "referral", None, None, None

    # Check exact domain match first
    full_domain = parsed.netloc.lower()
    for check_domain in [full_domain, domain]:
        if check_domain in DOMAIN_TO_PLATFORM:
            platform, medium = DOMAIN_TO_PLATFORM[check_domain]
            detail = _extract_source_detail(platform, path)
            return platform, medium, detail, full_domain, path

    # Check if it's a subdomain of a known platform
    for known_domain, (platform, medium) in DOMAIN_TO_PLATFORM.items():
        if domain.endswith("." + known_domain) or domain == known_domain:
            detail = _extract_source_detail(platform, path)
            return platform, medium, detail, full_domain, path

    # Check for Google regional domains
    if re.match(r"google\.[a-z]{2,3}(\.[a-z]{2})?$", domain):
        return "google", "search", "search_organic", full_domain, path

    return "unknown", "referral", None, full_domain, path


def _extract_source_detail(platform: str, path: str) -> str | None:
    """Try to determine the specific placement (feed, story, bio, DM, etc.)."""
    if not path:
        return None

    path_lower = path.lower()

    if platform == "instagram":
        if "/stories/" in path_lower:
            return "story"
        elif "/p/" in path_lower:
            return "post"
        elif "/reel/" in path_lower:
            return "reel"
        elif "/direct/" in path_lower:
            return "dm"
        elif path_lower in ("/", ""):
            return "bio"
        return "feed"

    elif platform == "tiktok":
        if "/video/" in path_lower or "/@" in path_lower:
            return "video"
        return "feed"

    elif platform == "youtube":
        if "/watch" in path_lower:
            return "video"
        elif "/shorts/" in path_lower:
            return "short"
        elif "/channel/" in path_lower or "/@" in path_lower:
            return "channel"
        return "feed"

    elif platform == "twitter":
        if "/status/" in path_lower:
            return "tweet"
        elif "/messages" in path_lower:
            return "dm"
        return "feed"

    elif platform == "facebook":
        if "/messages" in path_lower or "/msg" in path_lower:
            return "dm"
        elif "/groups/" in path_lower:
            return "group"
        elif "/posts/" in path_lower:
            return "post"
        return "feed"

    elif platform in ("google", "bing", "duckduckgo", "yahoo"):
        return "search_organic"

    return None


def _parse_accept_language(header: str | None) -> tuple[str | None, str | None]:
    """Extract primary language and locale from Accept-Language header."""
    if not header:
        return None, None

    # e.g. "en-US,en;q=0.9,es;q=0.8" → language="en", locale="en-US"
    try:
        first = header.split(",")[0].strip().split(";")[0].strip()
        parts = first.split("-")
        language = parts[0].lower()
        locale = first if len(parts) > 1 else None
        return language, locale
    except Exception:
        return None, None


def _parse_device_from_ua(ua_string: str | None) -> dict:
    """Enhanced device parsing with version info."""
    if not ua_string:
        return {
            "device_class": "unknown",
            "os_family": "unknown",
            "os_version": None,
            "browser_family": "unknown",
            "browser_version": None,
            "is_mobile": False,
        }

    from user_agents import parse as parse_ua
    parsed = parse_ua(ua_string)

    if parsed.is_mobile:
        device = "mobile"
    elif parsed.is_tablet:
        device = "tablet"
    elif parsed.is_pc:
        device = "desktop"
    else:
        device = "other"

    return {
        "device_class": device,
        "os_family": parsed.os.family,
        "os_version": ".".join(str(v) for v in parsed.os.version if v is not None) or None,
        "browser_family": parsed.browser.family,
        "browser_version": ".".join(str(v) for v in parsed.browser.version if v is not None) or None,
        "is_mobile": parsed.is_mobile or parsed.is_tablet,
    }


# --- Main Entry Point ---

def analyze_click(
    user_agent: str | None,
    referer: str | None,
    accept_language: str | None,
    headers: dict | None = None,
) -> ClickIntelligence:
    """
    Analyze a click request and extract maximum intelligence.

    Priority for source detection:
      1. In-app browser UA (most reliable for social platforms)
      2. Referer header
      3. Falls back to "direct"
    """
    intel = ClickIntelligence()

    # --- 1. In-app browser detection (highest priority) ---
    is_in_app, in_app_platform = _detect_in_app_browser(user_agent)
    intel.is_in_app_browser = is_in_app
    intel.in_app_platform = in_app_platform

    # --- 2. Referer classification ---
    ref_platform, ref_medium, ref_detail, ref_domain, ref_path = _classify_referer(referer)
    intel.referer_domain = ref_domain
    intel.referer_path = ref_path
    intel.referer_full = referer

    # --- 3. Merge: in-app browser wins for platform, referer fills gaps ---
    if is_in_app and in_app_platform:
        intel.source_platform = in_app_platform
        intel.source_medium = "social"
        intel.source_detail = ref_detail or "in_app"
    else:
        intel.source_platform = ref_platform
        intel.source_medium = ref_medium
        intel.source_detail = ref_detail

    # --- 4. Device info ---
    device = _parse_device_from_ua(user_agent)
    intel.device_class = device["device_class"]
    intel.os_family = device["os_family"]
    intel.os_version = device["os_version"]
    intel.browser_family = device["browser_family"]
    intel.browser_version = device["browser_version"]
    intel.is_mobile = device["is_mobile"]

    # --- 5. Language/locale ---
    intel.language, intel.locale = _parse_accept_language(accept_language)

    return intel
