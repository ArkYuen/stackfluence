"""
Parameter Injection Engine — rules-based.

UTM spec:
  utm_source   = platform bucket (instagram, tiktok, reddit, direct, ...)
  utm_medium   = "creator" (constant)
  utm_campaign = full referrer URL (or Sec-Fetch-Site bucket, or omitted)
  utm_content  = destination URL path+query, sanitized for dashboards
  inf_click_id = always present

What WE author:
  1. UTM params → ALWAYS.
  2. Stackfluence click ID (inf_click_id) → ALWAYS.
  3. Mobile attribution params → ONLY when the link has app destinations.
  4. Per-link param_overrides → ALWAYS applied last (brand wins).

What the PLATFORMS author (we just passthrough):
  - fbclid, ttclid, ScCid, gclid, wbraid, gbraid, msclkid, epik, li_fat_id, twclid, rdt_cid
"""

from urllib.parse import urlencode, urlparse, parse_qs, urlunparse


# Maps source_platform → utm_source value
PLATFORM_SOURCE = {
    "instagram":  "instagram",
    "tiktok":     "tiktok",
    "youtube":    "youtube",
    "twitter":    "x",
    "facebook":   "facebook",
    "linkedin":   "linkedin",
    "pinterest":  "pinterest",
    "snapchat":   "snapchat",
    "reddit":     "reddit",
    "threads":    "threads",
    "telegram":   "telegram",
    "whatsapp":   "whatsapp",
    "discord":    "discord",
    "google":     "google",
    "bing":       "bing",
    "duckduckgo": "duckduckgo",
    "gmail":      "gmail",
    "outlook":    "outlook",
    "yahoo_mail": "yahoo_mail",
    "linktree":   "linktree",
    "direct":     "direct",
}

# Platform-injected params we passthrough (not strip, not generate)
PLATFORM_PASSTHROUGH_PARAMS = {
    "fbclid",       # Meta / Facebook / Instagram
    "ttclid",       # TikTok
    "ScCid",        # Snapchat
    "gclid",        # Google Ads
    "wbraid",       # Google Ads (web-to-app)
    "gbraid",       # Google Ads (app-to-app)
    "epik",         # Pinterest
    "li_fat_id",    # LinkedIn
    "msclkid",      # Microsoft Ads
    "twclid",       # Twitter/X Ads
    "rdt_cid",      # Reddit Ads
}


def extract_platform_params(query_params: dict) -> dict:
    """Extract platform-injected params from the incoming request."""
    captured = {}
    for key in PLATFORM_PASSTHROUGH_PARAMS:
        if key in query_params:
            captured[key] = query_params[key]
    return captured


def _sanitize_campaign(dest_url: str) -> str:
    """
    Build utm_campaign from destination URL "after host".
    path + query, sanitized for dashboards.

    Transform:
      / → _
      ? → ~
      & → __
      = → -
    Then collapse repeated underscores and trim to 180 chars.
    """
    parsed = urlparse(dest_url)

    # Build raw campaign: path + query
    campaign_raw = parsed.path or ""
    if parsed.query:
        campaign_raw += "?" + parsed.query

    # Remove leading slash
    campaign_raw = campaign_raw.lstrip("/")

    if not campaign_raw:
        return "home"

    # Sanitize for dashboards (human-readable approach)
    sanitized = campaign_raw
    sanitized = sanitized.replace("/", "_")
    sanitized = sanitized.replace("?", "~")
    sanitized = sanitized.replace("&", "__")
    sanitized = sanitized.replace("=", "-")

    # Collapse repeated underscores
    while "__" in sanitized:
        old = sanitized
        sanitized = sanitized.replace("___", "__")
        if sanitized == old:
            break

    # Trim to 180 chars
    if len(sanitized) > 180:
        sanitized = sanitized[:180]

    return sanitized


def _encode_referrer(referrer: str | None) -> str:
    """Return the raw referrer string for utm_content (encoding handled by urlencode later)."""
    if not referrer:
        return ""
    # Cap at 500 chars to avoid URL length issues
    return referrer[:500]


def build_tracking_params(
    click_id: str,
    source_platform: str,
    dest_url: str,
    referrer: str | None = None,
    creator_handle: str = "",
    campaign_slug: str = "",
    asset_slug: str | None = None,
    param_overrides: dict | None = None,
    has_app_destination: bool = False,
    platform_params: dict | None = None,
    request_headers: dict | None = None,
) -> dict:
    params = {}

    # ═══════════════════════════════════════════════════════════
    # RULE 1: UTM params — ALWAYS (we author these)
    # ═══════════════════════════════════════════════════════════

    # utm_source = platform bucket
    utm_source = PLATFORM_SOURCE.get(
        source_platform,
        source_platform or "unknown"
    )
    params["utm_source"] = utm_source

    # utm_medium = "creator" (constant)
    params["utm_medium"] = "creator"

    # content = sanitized destination path (+query)
    params["utm_content"] = _sanitize_campaign(dest_url)

    # campaign = full referrer URL if present; else Sec-Fetch-Site bucket; else omit
    if referrer:
        params["utm_campaign"] = _encode_referrer(referrer)
    else:
        sec_fetch_site = (request_headers or {}).get("sec-fetch-site") or (request_headers or {}).get("Sec-Fetch-Site")
        if sec_fetch_site:
            params["utm_campaign"] = sec_fetch_site.lower()  # "cross-site" / "same-site" / "same-origin" / "none"
        # else: do not set utm_campaign

    # ═══════════════════════════════════════════════════════════
    # RULE 2: Stackfluence click ID — ALWAYS
    # ═══════════════════════════════════════════════════════════
    params["inf_click_id"] = click_id

    # ═══════════════════════════════════════════════════════════
    # RULE 3: Platform passthrough — forward what they gave us
    # ═══════════════════════════════════════════════════════════
    if platform_params:
        params.update(platform_params)

    # ═══════════════════════════════════════════════════════════
    # RULE 4: Mobile attribution — ONLY when link goes to an app
    # ═══════════════════════════════════════════════════════════
    if has_app_destination:
        # AppsFlyer
        params["pid"] = f"stackfluence_{source_platform}"
        params["c"] = campaign_slug
        params["af_sub1"] = creator_handle
        params["af_sub2"] = click_id
        params["af_sub3"] = ""

        # Branch.io
        params["~channel"] = source_platform
        params["~campaign"] = campaign_slug
        params["~feature"] = "influencer"
        params["~tags"] = creator_handle

        # Adjust
        params["adj_tracker"] = click_id
        params["adj_campaign"] = campaign_slug
        params["adj_creative"] = creator_handle

        # Kochava
        params["ko_click_id"] = click_id

        # Singular
        params["singular_click_id"] = click_id

    # ═══════════════════════════════════════════════════════════
    # RULE 5: Per-link overrides — ALWAYS applied last
    # ═══════════════════════════════════════════════════════════
    if param_overrides:
        params.update(param_overrides)

    return params


def inject_params_to_url(url: str, params: dict, policy: str = "only_if_missing") -> str:
    """
    Append tracking parameters to a URL.

    policy:
      "only_if_missing" — don't overwrite existing UTMs (recommended)
      "always_override" — our params win
    """
    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)

    for key, value in params.items():
        if policy == "only_if_missing" and key in existing:
            continue
        existing[key] = [str(value)]

    new_query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def resolve_destination(
    link,
    click_id: str,
    source_platform: str,
    source_medium: str,
    source_detail: str | None,
    is_mobile: bool,
    os_family: str | None,
    platform_params: dict | None = None,
    referrer: str | None = None,
    request_headers: dict | None = None,
) -> tuple[str, dict]:
    """Determine final destination URL. Returns (final_url, injected_params)."""
    has_app_destination = bool(
        link.ios_deeplink or link.ios_fallback_url or
        link.android_deeplink or link.android_fallback_url or
        link.universal_link
    )

    params = build_tracking_params(
        click_id=click_id,
        source_platform=source_platform,
        dest_url=link.destination_url,
        referrer=referrer,
        creator_handle=link.creator_handle,
        campaign_slug=link.campaign_slug,
        asset_slug=link.asset_slug,
        param_overrides=link.param_overrides,
        has_app_destination=has_app_destination,
        platform_params=platform_params,
        request_headers=request_headers,
    )

    base_url = link.destination_url

    if is_mobile and os_family:
        os_lower = os_family.lower() if os_family else ""

        if "ios" in os_lower or "iphone" in os_lower or "ipad" in os_lower:
            if link.universal_link:
                base_url = link.universal_link
            elif link.ios_fallback_url:
                base_url = link.ios_fallback_url

        elif "android" in os_lower:
            if link.universal_link:
                base_url = link.universal_link
            elif link.android_fallback_url:
                base_url = link.android_fallback_url

    # --- Build the final URL ---
    # ONLY inject inf_click_id into the destination URL.
    # UTM params, platform params, and everything else stay in the DB only.
    # The advertiser's URL stays clean — no leaked tracking params.
    url_params = {"inf_click_id": click_id}

    # Platform passthrough params (fbclid, gclid, etc.) — these are expected by
    # advertisers' analytics tools, so we DO forward them.
    if platform_params:
        url_params.update(platform_params)

    # Per-link overrides — the brand explicitly wants these on the URL
    if link.param_overrides:
        url_params.update(link.param_overrides)

    # Mobile deep link params if applicable
    if is_mobile and os_family:
        os_lower = os_family.lower() if os_family else ""
        if ("ios" in os_lower or "iphone" in os_lower or "ipad" in os_lower):
            if link.ios_deeplink and link.ios_fallback_url:
                url_params["ios_deeplink"] = link.ios_deeplink + \
                    ("&" if "?" in link.ios_deeplink else "?") + f"inf_click_id={click_id}"
        elif "android" in os_lower:
            if link.android_deeplink and link.android_fallback_url:
                url_params["android_deeplink"] = link.android_deeplink + \
                    ("&" if "?" in link.android_deeplink else "?") + f"inf_click_id={click_id}"

    final_url = inject_params_to_url(base_url, url_params, policy="only_if_missing")
    return final_url, params
