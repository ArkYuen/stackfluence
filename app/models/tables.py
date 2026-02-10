"""
Database models — the "truth layer."

Design principles:
  - Events are append-only (no updates/deletes on event tables)
  - Links are mutable (can be paused, archived)
  - Derivations (qualified_session, attributed_conversion) are computed views/tables built later
"""

import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
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
    """Advertiser / brand account."""
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    stripe_customer_id = Column(String(255), nullable=True)
    billing_policy = Column(JSONB, nullable=True)  # per-client policy overrides
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    links = relationship("Link", back_populates="organization")


class Creator(Base):
    """Influencer / creator identity."""
    __tablename__ = "creators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    handle = Column(String(100), nullable=False, index=True)
    display_name = Column(String(255), nullable=True)
    platform = Column(String(50), nullable=True)  # tiktok, instagram, youtube, etc.
    platform_user_id = Column(String(255), nullable=True)
    profile_url = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)  # enrichment data
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    links = relationship("Link", back_populates="creator")


class Campaign(Base):
    """Groups links under a campaign for an org."""
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="active")  # active, paused, archived
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Link(Base):
    """A tracked wrapper link: /c/{creator_handle}/{campaign_slug}/{asset?}"""
    __tablename__ = "links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("creators.id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)

    # The short path components
    creator_handle = Column(String(100), nullable=False)
    campaign_slug = Column(String(100), nullable=False)
    asset_slug = Column(String(100), nullable=True)  # optional sub-asset

    # Where the click actually goes
    destination_url = Column(Text, nullable=False)

    status = Column(String(20), default="active")  # active, paused, expired
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


# ---------------------------------------------------------------------------
# Event tables (append-only)
# ---------------------------------------------------------------------------

class ClickEvent(Base):
    """Immutable click event — logged server-side on every wrapper hit."""
    __tablename__ = "click_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, unique=True, index=True)
    link_id = Column(UUID(as_uuid=True), ForeignKey("links.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    creator_id = Column(UUID(as_uuid=True), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), nullable=False)

    # Request metadata
    ip_address = Column(String(45), nullable=True)  # v4 or v6
    user_agent = Column(Text, nullable=True)
    referer = Column(Text, nullable=True)
    country_code = Column(String(2), nullable=True)
    region = Column(String(100), nullable=True)
    device_class = Column(String(20), nullable=True)  # mobile, desktop, tablet
    os_family = Column(String(50), nullable=True)
    browser_family = Column(String(50), nullable=True)

    # Bot detection
    risk_score = Column(Float, default=0.0)
    bot_blocked = Column(Boolean, default=False)
    bot_signals = Column(JSONB, nullable=True)

    # Destination
    destination_url = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_click_events_org_created", "organization_id", "created_at"),
        Index("ix_click_events_creator_created", "creator_id", "created_at"),
    )


class SessionEvent(Base):
    """Fired by advertiser-side connector when user lands on site."""
    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(String(100), nullable=True)  # advertiser's session ID if available

    page_url = Column(Text, nullable=True)
    referrer = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PageViewEvent(Base):
    """Individual page view within a session."""
    __tablename__ = "pageview_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    page_url = Column(Text, nullable=True)
    time_on_page_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConversionEvent(Base):
    """Advertiser-reported conversion (add_to_cart, signup, purchase, etc.)."""
    __tablename__ = "conversion_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    event_type = Column(String(50), nullable=False)  # add_to_cart, signup, purchase
    order_id = Column(String(255), nullable=True)
    revenue_cents = Column(Integer, nullable=True)
    currency = Column(String(3), default="USD")
    metadata_ = Column("metadata", JSONB, nullable=True)  # line items, etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_conversion_events_org_type", "organization_id", "event_type"),
    )


class RefundEvent(Base):
    """Refund/chargeback tied to a prior conversion."""
    __tablename__ = "refund_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    click_id = Column(String(100), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    original_order_id = Column(String(255), nullable=True)
    refund_amount_cents = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
