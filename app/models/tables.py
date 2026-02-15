"""
Database models — the "truth layer."

Design principles:
  - Events are append-only (no updates/deletes on event tables)
  - Links are mutable (can be paused, archived)
  - click_events stores both server + client telemetry
  - click_events_log is append-only firehose for debugging
"""

import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Entity tables
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    stripe_customer_id = Column(String(255), nullable=True)
    billing_policy = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    links = relationship("Link", back_populates="organization")


class Creator(Base):
    __tablename__ = "creators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    handle = Column(String(100), nullable=False, index=True)
    display_name = Column(String(255), nullable=True)
    platform = Column(String(50), nullable=True)
    platform_user_id = Column(String(255), nullable=True)
    profile_url = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    links = relationship("Link", back_populates="creator")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="active")
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Link(Base):
    __tablename__ = "links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("creators.id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)

    creator_handle = Column(String(100), nullable=False)
    campaign_slug = Column(String(100), nullable=False)
    asset_slug = Column(String(100), nullable=True)

    # Where the click goes — web
    destination_url = Column(Text, nullable=False)

    # Deep linking — app installs
    ios_deeplink = Column(Text, nullable=True)
    ios_fallback_url = Column(Text, nullable=True)
    android_deeplink = Column(Text, nullable=True)
    android_fallback_url = Column(Text, nullable=True)
    universal_link = Column(Text, nullable=True)

    # UTM / parameter injection overrides (JSONB)
    param_overrides = Column(JSONB, nullable=True)

    # Where the link was created: demo, member, api, enterprise
    source = Column(String(20), default="member", nullable=False, index=True)

    status = Column(String(20), default="active")
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="links")
    creator = relationship("Creator", back_populates="links")

    __table_args__ = (
        Index(
            "ix_links_route_lookup",
            "creator_handle", "campaign_slug", "asset_slug",
            unique=True,
        ),
    )


class ShopifyStore(Base):
    __tablename__ = "shopify_stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    shop_domain = Column(String(255), nullable=False, unique=True, index=True)
    access_token_encrypted = Column(Text, nullable=False)
    webhook_secret = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Event tables (append-only)
# ---------------------------------------------------------------------------

class ClickEvent(Base):
    """
    One row per click. Created server-side at /c/:slug.
    Updated with client telemetry from /collect/:clickId.
    """
    __tablename__ = "click_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, unique=True, index=True)
    session_id = Column(String(100), nullable=True)          # first-party cookie for repeat visit stitching
    link_id = Column(UUID(as_uuid=True), ForeignKey("links.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    creator_id = Column(UUID(as_uuid=True), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), nullable=False)

    # --- Destination URLs ---
    destination_url_raw = Column(Text, nullable=False)       # original link destination
    destination_url_final = Column(Text, nullable=False)     # after param injection

    # --- UTM + params ---
    utm = Column(JSONB, nullable=True)                       # final UTM set applied
    injected_params = Column(JSONB, nullable=True)           # all params WE authored
    platform_click_ids = Column(JSONB, nullable=True)        # fbclid, ttclid, etc. from platform
    query_params = Column(JSONB, nullable=True)              # all inbound query params

    # --- Source provenance (critical for "where they came from") ---
    referrer_header = Column(Text, nullable=True)            # server-side Referer header
    document_referrer = Column(Text, nullable=True)          # from client JS collector (more reliable)
    collector_page_url = Column(Text, nullable=True)         # window.location.href on collector hop (our URL with params)
    source_best = Column(Text, Computed(                     # auto-picks best available
        "COALESCE(document_referrer, referrer_header)"
    ))

    # --- Source intelligence (parsed from referrer + UA) ---
    source_platform = Column(String(50), nullable=True)
    source_medium = Column(String(50), nullable=True)
    source_detail = Column(String(50), nullable=True)
    is_in_app_browser = Column(Boolean, default=False)
    in_app_platform = Column(String(50), nullable=True)
    referer_domain = Column(String(255), nullable=True)

    # --- Networking ---
    ip_address = Column(String(45), nullable=True)

    # --- Sec-Fetch metadata headers (distinguish navigations vs fetches/bots) ---
    sec_fetch_site = Column(String(50), nullable=True)       # none, same-origin, same-site, cross-site
    sec_fetch_mode = Column(String(50), nullable=True)       # navigate, cors, no-cors, same-origin, websocket
    sec_fetch_dest = Column(String(50), nullable=True)       # document, iframe, image, script, etc.
    sec_fetch_user = Column(String(10), nullable=True)       # ?1 if user-initiated

    # --- User agent ---
    user_agent = Column(Text, nullable=True)
    ua_parsed = Column(JSONB, nullable=True)                 # os/browser/device parsed server-side
    is_webview_guess = Column(Boolean, default=False)

    # --- Device (parsed from UA) ---
    device_class = Column(String(20), nullable=True)
    os_family = Column(String(50), nullable=True)
    os_version = Column(String(20), nullable=True)
    browser_family = Column(String(50), nullable=True)
    browser_version = Column(String(20), nullable=True)
    is_mobile = Column(Boolean, default=False)

    # --- Geo (server-side IP lookup) ---
    country_code = Column(String(2), nullable=True)
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    asn = Column(Integer, nullable=True)                     # autonomous system number
    isp = Column(String(255), nullable=True)                 # ISP name

    # --- Language ---
    language = Column(String(10), nullable=True)             # from Accept-Language header
    locale = Column(String(10), nullable=True)

    # --- Client telemetry (from collector hop JS) ---
    client_meta = Column(JSONB, nullable=True)               # screen, tz, languages, connection, UA-CH, etc.

    # --- Screen & viewport (from client JS) ---
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)
    viewport_width = Column(Integer, nullable=True)
    viewport_height = Column(Integer, nullable=True)
    color_depth = Column(Integer, nullable=True)             # headless browsers often report 0 or 24

    # --- Client environment ---
    timezone = Column(String(100), nullable=True)            # e.g. "America/New_York" from Intl.DateTimeFormat
    connection_type = Column(String(20), nullable=True)      # wifi, cellular, ethernet, none (navigator.connection)
    touch_support = Column(Boolean, nullable=True)           # mobile UA with no touch = suspicious
    hardware_concurrency = Column(Integer, nullable=True)    # CPU cores — bots on VMs often report 1-2
    device_memory = Column(Float, nullable=True)             # GB — another VM/bot signal
    do_not_track = Column(Boolean, nullable=True)            # navigator.doNotTrack
    ad_blocker_detected = Column(Boolean, nullable=True)     # impacts attribution accuracy

    # --- Engagement signals ---
    is_repeat_visitor = Column(Boolean, default=False)       # based on session_id cookie
    click_number = Column(Integer, default=1)                # nth click in this session
    redirect_latency_ms = Column(Integer, nullable=True)     # server redirect → collector hop. Bots are instant

    # --- Bot / fraud ---
    risk_score = Column(Float, default=0.0)
    bot_blocked = Column(Boolean, default=False)
    is_suspected_bot = Column(Boolean, default=False)
    bot_reason = Column(Text, nullable=True)
    bot_signals = Column(JSONB, nullable=True)

    # --- Timing / latency ---
    server_received_at = Column(DateTime(timezone=True), server_default=func.now())
    server_responded_at = Column(DateTime(timezone=True), nullable=True)      # set just before redirect
    collector_received_at = Column(DateTime(timezone=True), nullable=True)    # when /collect fires
    # collector_hop_delta_ms computed at query time: collector_received_at - server_received_at
    # bots often don't execute JS so collector never fires — NULL = suspicious

    # --- Flags ---
    used_collector = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_click_events_org_created", "organization_id", "created_at"),
        Index("ix_click_events_creator_created", "creator_id", "created_at"),
        Index("ix_click_events_source", "organization_id", "source_platform", "source_medium"),
    )


class ClickEventLog(Base):
    """Append-only firehose — one row per event in the click lifecycle."""
    __tablename__ = "click_events_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    click_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)          # server_received, client_collected, redirected
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Downstream event tables (append-only)
# ---------------------------------------------------------------------------

class SessionEvent(Base):
    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(String(100), nullable=True)
    page_url = Column(Text, nullable=True)
    referrer = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PageViewEvent(Base):
    __tablename__ = "pageview_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    page_url = Column(Text, nullable=True)
    time_on_page_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConversionEvent(Base):
    __tablename__ = "conversion_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    order_id = Column(String(255), nullable=True)
    revenue_cents = Column(Integer, nullable=True)
    currency = Column(String(3), default="USD")
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_conversion_events_org_type", "organization_id", "event_type"),
    )


class RefundEvent(Base):
    __tablename__ = "refund_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    original_order_id = Column(String(255), nullable=True)
    refund_amount_cents = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
