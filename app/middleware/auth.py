import hashlib
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, select, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.models.database import get_db
from app.models.tables import Base

import structlog

logger = structlog.get_logger()


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(12), nullable=False)
    key_type = Column(String(20), nullable=False)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    rate_limit_per_minute = Column(Integer, default=120)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(key_type: str = "secret") -> tuple[str, str]:
    prefix = "sf_pub_" if key_type == "publishable" else "sf_sec_"
    token = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{token}"
    return raw_key, _hash_key(raw_key)


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class AuthContext:
    organization_id: UUID
    key_type: str
    key_id: UUID


async def _resolve_key(raw_key: str | None, db: AsyncSession) -> AuthContext:
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Include X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = _hash_key(raw_key)

    stmt = select(APIKey).where(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True,
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    api_key.last_used_at = func.now()
    await db.commit()

    return AuthContext(
        organization_id=api_key.organization_id,
        key_type=api_key.key_type,
        key_id=api_key.id,
    )


async def require_auth(
    request: Request,
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if not api_key:
        api_key = request.query_params.get("key")
    return await _resolve_key(api_key, db)


async def require_secret_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if not api_key:
        api_key = request.query_params.get("key")
    auth = await _resolve_key(api_key, db)
    if auth.key_type != "secret":
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires a secret key (sf_sec_...). Publishable keys cannot read data.",
        )
    return auth


def enforce_org_scope(auth: AuthContext, organization_id: UUID):
    if auth.organization_id != organization_id:
        raise HTTPException(
            status_code=403,
            detail="API key does not have access to this organization.",
        )