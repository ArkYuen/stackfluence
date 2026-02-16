"""
Referrer Intelligence — extract maximum context from every click.

Priority chain (direct is LAST RESORT):
  1. In-app browser UA detection (Instagram, TikTok, FB, etc.)
  2. Referrer header domain classification
  3. Platform click IDs in URL params (fbclid, gclid, ttclid, etc.)
  4. UTM params already on the URL (utm_source, utm_medium)
  5. sec-fetch-site header (cross-site vs none vs same-origin)
  6. Accept-Language complexity (simple = bot, complex = real user)
  7. Only THEN fall back to "direct"

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
    "threads":    [r"Barcelona"],
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


# --- Platform Click ID Detection ---

CLICK_ID_TO_PLATFORM = {
    "fbclid":       ("facebook", "social"),
    "gclid":        ("google", "paid"),
    "gbraid":       ("google", "paid"),
    "wbraid":       ("google", "paid"),
    "ttclid":       ("tiktok", "social"),
    "twclid":       ("twitter", "social"),
    "li_fat_id":    ("linkedin", "social"),
    "sclid":        ("snapchat", "social"),
    "msclkid":      ("bing", "paid"),
    "mc_eid":       ("mailchimp", "email"),
    "igshid":       ("instagram", "social"),
    "pin_click_id": ("pinterest", "social"),
    "rdt_cid":      ("reddit", "social"),
    "yclid":        ("yandex", "paid"),
    "dclid":        ("google", "paid"),       # Google Display
    "_branch_match_id": ("branch", "referral"),
}


def _detect_platform_click_ids(query_params: dict) -> tuple[str | None, str | None, str | None]:
    """Check URL query params for platform-injected click IDs."""
    if not query_params:
        return None, None, None

    for param_name, (platform, medium) in CLICK_ID_TO_PLATFORM.items():
        if param_name in query_params and query_params[param_name]:
            detail = "paid" if medium == "paid" else "click_id"
            return platform, medium, detail

    return None, None, None


# --- UTM Param Detection ---

def _detect_utm_source(query_params: dict) -> tuple[str | None, str | None, str | None]:
    """Check for utm_source and utm_medium in query params."""
    if not query_params:
        return None, None, None

    utm_source = query_params.get("utm_source", "").strip().lower()
    utm_medium = query_params.get("utm_medium", "").strip().lower()
    utm_campaign = query_params.get("utm_campaign", "").strip().lower()

    if not utm_source:
        return None, None, None

    # Map common utm_source values to platforms
    UTM_SOURCE_MAP = {
        "instagram": ("instagram", "social"),
        "ig": ("instagram", "social"),
        "tiktok": ("tiktok", "social"),
        "tt": ("tiktok", "social"),
        "facebook": ("facebook", "social"),
        "fb": ("facebook", "social"),
        "twitter": ("twitter", "social"),
        "x": ("twitter", "social"),
        "youtube": ("youtube", "social"),
        "yt": ("youtube", "social"),
        "linkedin": ("linkedin", "social"),
        "li": ("linkedin", "social"),
        "pinterest": ("pinterest", "social"),
        "reddit": ("reddit", "social"),
        "snapchat": ("snapchat", "social"),
        "threads": ("threads", "social"),
        "telegram": ("telegram", "messaging"),
        "whatsapp": ("whatsapp", "messaging"),
        "discord": ("discord", "messaging"),
        "google": ("google", "search"),
        "bing": ("bing", "search"),
        "gmail": ("gmail", "email"),
        "email": ("email", "email"),
        "newsletter": ("newsletter", "email"),
        "mailchimp": ("mailchimp", "email"),
        "sendgrid": ("sendgrid", "email"),
        "klaviyo": ("klaviyo", "email"),
        "sms": ("sms", "messaging"),
        "text": ("sms", "messaging"),
    }

    if utm_source in UTM_SOURCE_MAP:
        platform, medium = UTM_SOURCE_MAP[utm_source]
        # utm_medium overrides if present
        if utm_medium:
            medium = utm_medium
        return platform, medium, utm_campaign or None

    # Unknown utm_source but it exists — still better than "direct"
    medium = utm_medium if utm_medium else "referral"
    return utm_source, medium, utm_campaign or None


# --- sec-fetch-site Classification ---

def _classify_sec_fetch(headers: dict | None) -> tuple[str | None, str | None]:
    """
    Use sec-fetch-site to determine if click was external.
    Returns (platform_hint, medium_hint) or (None, None).
    """
    if not headers:
        return None, None

    sec_fetch_site = (headers.get("sec-fetch-site") or "").lower()
    sec_fetch_dest = (headers.get("sec-fetch-dest") or "").lower()

    if sec_fetch_site == "cross-site":
        # Definitely came from somewhere external — not direct
        return "unknown_external", "referral"
    elif sec_fetch_site == "same-site":
        return "same_site", "internal"
    elif sec_fetch_site == "same-origin":
        return "same_origin", "internal"
    # "none" means direct navigation, typed URL, or bookmark
    # We don't return anything here — let it fall through

    return None, None


# --- Email Client UA Detection ---

EMAIL_CLIENT_PATTERNS = {
    "gmail":     [r"Googlebot", r"Google-Safety"],
    "outlook":   [r"Microsoft Office", r"Outlook", r"ms-office"],
    "yahoo":     [r"Yahoo! Slurp", r"YahooMailProxy"],
    "apple_mail": [r"AppleMail"],
    "thunderbird": [r"Thunderbird"],
}


def _detect_email_client(ua: str | None) -> tuple[bool, str | None]:
    """Check if UA indicates an email client or email link scanner."""
    if not ua:
        return False, None

    for client, patterns in EMAIL_CLIENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, ua, re.IGNORECASE):
                return True, client

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
    "outlook.office365.com": ("outlook", "email"),
    "mail.yahoo.com":   ("yahoo_mail", "email"),
    "mail.aol.com":     ("aol_mail", "email"),
    "mail.protonmail.com": ("protonmail", "email"),
    "app.mailspring.com": ("mailspring", "email"),

    # Link shorteners
    "bit.ly":           ("bitly", "referral"),
    "tinyurl.com":      ("tinyurl", "referral"),
    "linktr.ee":        ("linktree", "referral"),
    "beacons.ai":       ("beacons", "referral"),
    "stan.store":       ("stan_store", "referral"),
    "hoo.be":           ("hoobe", "referral"),
    "snipfeed.co":      ("snipfeed", "referral"),
    "campsite.bio":     ("campsite", "referral"),
    "tap.bio":          ("tapbio", "referral"),

    # News / content
    "news.ycombinator.com": ("hackernews", "referral"),
    "producthunt.com":  ("producthunt", "referral"),
    "www.producthunt.com": ("producthunt", "referral"),
    "medium.com":       ("medium", "referral"),
    "substack.com":     ("substack", "referral"),
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
    query_params: dict | None = None,
) -> ClickIntelligence:
    """
    Analyze a click request and extract maximum intelligence.

    Priority chain — "direct" is ABSOLUTE LAST RESORT:
      1. In-app browser UA (most reliable for social platforms)
      2. Referrer header domain
      3. Platform click IDs (fbclid, gclid, ttclid, etc.)
      4. UTM params (utm_source, utm_medium)
      5. Email client UA detection
      6. sec-fetch-site header (cross-site = external, not direct)
      7. Only then: "direct"
    """
    intel = ClickIntelligence()

    # --- 1. In-app browser detection (highest priority) ---
    is_in_app, in_app_platform = _detect_in_app_browser(user_agent)
    intel.is_in_app_browser = is_in_app
    intel.in_app_platform = in_app_platform

    # --- 2. Referrer classification ---
    ref_platform, ref_medium, ref_detail, ref_domain, ref_path = _classify_referer(referer)
    intel.referer_domain = ref_domain
    intel.referer_path = ref_path
    intel.referer_full = referer

    # --- 3. Platform click IDs ---
    clickid_platform, clickid_medium, clickid_detail = _detect_platform_click_ids(query_params)

    # --- 4. UTM params ---
    utm_platform, utm_medium, utm_detail = _detect_utm_source(query_params)

    # --- 5. Email client detection ---
    is_email_client, email_client_name = _detect_email_client(user_agent)

    # --- 6. sec-fetch-site ---
    sec_platform, sec_medium = _classify_sec_fetch(headers)

    # =====================================================================
    #  MERGE — cascade through signals, "direct" only if ALL are empty
    # =====================================================================

    resolved = False

    # Priority 1: In-app browser (strongest signal)
    if is_in_app and in_app_platform:
        intel.source_platform = in_app_platform
        intel.source_medium = "social"
        intel.source_detail = ref_detail or "in_app"
        resolved = True

    # Priority 2: Referrer header (if not "direct")
    if not resolved and ref_platform != "direct":
        intel.source_platform = ref_platform
        intel.source_medium = ref_medium
        intel.source_detail = ref_detail
        resolved = True

    # Priority 3: Platform click IDs (fbclid, gclid, etc.)
    if not resolved and clickid_platform:
        intel.source_platform = clickid_platform
        intel.source_medium = clickid_medium
        intel.source_detail = clickid_detail
        resolved = True

    # Priority 4: UTM params
    if not resolved and utm_platform:
        intel.source_platform = utm_platform
        intel.source_medium = utm_medium
        intel.source_detail = utm_detail
        resolved = True

    # Priority 5: Email client UA
    if not resolved and is_email_client:
        intel.source_platform = email_client_name
        intel.source_medium = "email"
        intel.source_detail = "link_scanner"
        resolved = True

    # Priority 6: sec-fetch-site (we know it's external, just don't know from where)
    if not resolved and sec_platform and sec_platform != "same_origin" and sec_platform != "same_site":
        intel.source_platform = sec_platform  # "unknown_external"
        intel.source_medium = sec_medium      # "referral"
        intel.source_detail = "no_referrer"
        resolved = True

    # Priority 7 (LAST RESORT): direct
    if not resolved:
        intel.source_platform = "direct"
        intel.source_medium = "direct"
        intel.source_detail = None

    # --- ENRICHMENT: Even if resolved, overlay additional context ---

    # If we got platform from click ID or UTM but also have in-app info, add it
    if not is_in_app and in_app_platform is None:
        # Not in-app, but check if resolved platform suggests it should be mobile social
        pass

    # If we resolved from sec-fetch but have click IDs, upgrade the detail
    if intel.source_platform == "unknown_external" and clickid_platform:
        intel.source_platform = clickid_platform
        intel.source_medium = clickid_medium

    # --- Device info ---
    device = _parse_device_from_ua(user_agent)
    intel.device_class = device["device_class"]
    intel.os_family = device["os_family"]
    intel.os_version = device["os_version"]
    intel.browser_family = device["browser_family"]
    intel.browser_version = device["browser_version"]
    intel.is_mobile = device["is_mobile"]

    # --- Language/locale ---
    intel.language, intel.locale = _parse_accept_language(accept_language)

    return intel
