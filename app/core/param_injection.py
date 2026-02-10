"""
Parameter Injection Engine — rules-based.

What WE author:
  1. UTM params → ALWAYS. We control these.
  2. Stackfluence click ID (inf_click_id) → ALWAYS.
  3. Mobile attribution params → ONLY when the link has app destinations.
  4. Per-link param_overrides → ALWAYS applied last (brand wins).

What the PLATFORMS author (we just passthrough):
  - fbclid, ttclid, ScCid, gclid, wbraid, gbraid, msclkid, epik, li_fat_id, twclid, rdt_cid
  We capture these and pass them through. We NEVER generate them.
"""

from urllib.parse import urlencode, urlparse, parse_qs, urlunparse


PLATFORM_UTM = {
    "instagram":  ("instagram", "social"),
    "tiktok":     ("tiktok", "social"),
    "youtube":    ("youtube", "social"),
    "twitter":    ("twitter", "social"),
    "facebook":   ("facebook", "social"),
    "linkedin":   ("linkedin", "social"),
    "pinterest":  ("pinterest", "social"),
    "snapchat":   ("snapchat", "social"),
    "reddit":     ("reddit", "social"),
    "threads":    ("threads", "social"),
    "telegram":   ("telegram", "messaging"),
    "whatsapp":   ("whatsapp", "messaging"),
    "discord":    ("discord", "messaging"),
    "google":     ("google", "organic"),
    "bing":       ("bing", "organic"),
    "duckduckgo": ("duckduckgo", "organic"),
    "gmail":      ("gmail", "email"),
    "outlook":    ("outlook", "email"),
    "yahoo_mail": ("yahoo_mail", "email"),
    "linktree":   ("linktree", "referral"),
    "direct":     ("direct", "none"),
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


def build_tracking_params(
    click_id: str,
    source_platform: str,
    source_medium: str,
    source_detail: str | None,
    creator_handle: str,
    campaign_slug: str,
    asset_slug: str | None = None,
    param_overrides: dict | None = None,
    has_app_destination: bool = False,
    platform_params: dict | None = None,
) -> dict:
    params = {}

    # ═══════════════════════════════════════════════════════════
    # RULE 1: UTM params — ALWAYS (we author these)
    # ═══════════════════════════════════════════════════════════
    utm_source, utm_medium = PLATFORM_UTM.get(
        source_platform,
        (source_platform or "unknown", source_medium or "referral")
    )
    params["utm_source"] = utm_source
    params["utm_medium"] = utm_medium
    params["utm_campaign"] = campaign_slug
    params["utm_content"] = creator_handle
    if source_detail:
        params["utm_term"] = source_detail
    if asset_slug:
        params["utm_content"] = f"{creator_handle}_{asset_slug}"

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
        params["af_sub3"] = source_detail or ""

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


def inject_params_to_url(url: str, params: dict) -> str:
    """Append tracking parameters to a URL. New params override existing."""
    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
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
        source_medium=source_medium,
        source_detail=source_detail,
        creator_handle=link.creator_handle,
        campaign_slug=link.campaign_slug,
        asset_slug=link.asset_slug,
        param_overrides=link.param_overrides,
        has_app_destination=has_app_destination,
        platform_params=platform_params,
    )

    base_url = link.destination_url

    if is_mobile and os_family:
        os_lower = os_family.lower() if os_family else ""

        if "ios" in os_lower or "iphone" in os_lower or "ipad" in os_lower:
            if link.universal_link:
                base_url = link.universal_link
            elif link.ios_deeplink:
                deep_url = link.ios_deeplink
                if "?" in deep_url:
                    deep_url += f"&inf_click_id={click_id}"
                else:
                    deep_url += f"?inf_click_id={click_id}"
                if link.ios_fallback_url:
                    base_url = link.ios_fallback_url
                    params["ios_deeplink"] = deep_url

        elif "android" in os_lower:
            if link.universal_link:
                base_url = link.universal_link
            elif link.android_deeplink:
                deep_url = link.android_deeplink
                if "?" in deep_url:
                    deep_url += f"&inf_click_id={click_id}"
                else:
                    deep_url += f"?inf_click_id={click_id}"
                if link.android_fallback_url:
                    base_url = link.android_fallback_url
                    params["android_deeplink"] = deep_url

    final_url = inject_params_to_url(base_url, params)
    return final_url, params
