"""
Demo links — public-facing link wrapping for the marketing site.

Design:
  - No auth required (rate-limited by IP instead)
  - Auto-creates a creator="demo" + campaign="website-demo" under a 
    dedicated demo organization
  - Links funnel into the same /c/ redirect pipeline → same ClickEvent table
  - You (admin) can query all demo links + their analytics
  - Visitors only see the wrapped URL, never the dashboard
"""

import datetime
import secrets
import string
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.tables import Base


def _generate_slug(length: int = 7) -> str:
    """Generate a short random slug like 'a3xK9mz'."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class DemoLink(Base):
    """
    One row per demo-wrapped link from the marketing site.
    
    These map to real Link rows so the /c/ redirect pipeline works,
    but this table tracks the demo-specific metadata (who created it,
    from what IP, etc.) that normal links don't need.
    """
    __tablename__ = "demo_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # The short slug used in the wrapped URL: /c/demo/website-demo/{slug}
    slug = Column(String(20), nullable=False, unique=True, index=True)
    
    # What the visitor pasted
    original_url = Column(Text, nullable=False)
    
    # The full wrapped URL we returned
    wrapped_url = Column(Text, nullable=False)
    
    # FK to the real Link row (so /c/ redirect works)
    link_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # --- Who created it (anonymous, but we track for abuse) ---
    creator_ip = Column(String(45), nullable=True)
    creator_user_agent = Column(Text, nullable=True)
    creator_fingerprint = Column(String(64), nullable=True)  # hash of IP+UA for grouping
    
    # --- Metadata ---
    click_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    
    # Optional: if they gave an email for "send me analytics"
    creator_email = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)  # auto-expire demo links
    
    __table_args__ = (
        Index("ix_demo_links_ip_created", "creator_ip", "created_at"),
        Index("ix_demo_links_created", "created_at"),
    )
