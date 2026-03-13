from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from uuid import uuid4
from app.models.tables import Base


class PlatformConnection(Base):
    __tablename__ = "platform_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True),
                    ForeignKey("organizations.id", ondelete="CASCADE"),
                    nullable=False)
    platform = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    auth_type = Column(String(10), nullable=False, default="token")

    # OAuth tokens (encrypted)
    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    oauth_scope = Column(Text, nullable=True)
    last_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    refresh_fail_count = Column(Integer, default=0)

    # Platform account identifiers
    platform_account_id = Column(String(255), nullable=True)
    platform_account_label = Column(String(255), nullable=True)
    secondary_id = Column(String(255), nullable=True)

    # Per-link override
    link_id = Column(UUID(as_uuid=True),
                     ForeignKey("links.id", ondelete="CASCADE"),
                     nullable=True)

    # Connection metadata
    connected_by = Column(UUID(as_uuid=True), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    last_event_status = Column(String(20), nullable=True)
    total_events_fired = Column(Integer, default=0)

    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_platform_connections_org_id", "org_id"),
        Index("ix_platform_connections_org_platform", "org_id", "platform"),
        UniqueConstraint("org_id", "platform", "link_id",
                         name="uq_platform_connection_org_platform_link"),
    )


class TokenRefreshLog(Base):
    __tablename__ = "token_refresh_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    org_id = Column(UUID(as_uuid=True), nullable=False)
    platform = Column(String(30), nullable=False)
    outcome = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
