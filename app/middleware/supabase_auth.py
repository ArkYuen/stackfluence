"""
Supabase authentication middleware for FastAPI.
Validates JWTs server-side by calling Supabase /auth/v1/user.
Auto-creates Organization + User on first login.
"""

import datetime
from dataclasses import dataclass
from uuid import uuid4

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import Column, DateTime, ForeignKey, String, Boolean, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Base, Organization


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    supabase_id = Column(String(255), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


@dataclass
class SupabaseAuthContext:
    organization_id: str
    user_id: str
    supabase_id: str
    email: str


async def _validate_supabase_token(token: str) -> dict:
    """Call Supabase /auth/v1/user to validate the Bearer token server-side."""
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return resp.json()


async def _get_or_create_user(
    supabase_user: dict, db: AsyncSession
) -> User:
    """Find user by supabase_id or auto-create a new Organization + User."""
    supabase_id = supabase_user["id"]
    email = supabase_user.get("email", "")
    full_name = supabase_user.get("user_metadata", {}).get("full_name", "")
    avatar_url = supabase_user.get("user_metadata", {}).get("avatar_url", "")

    result = await db.execute(select(User).where(User.supabase_id == supabase_id))
    user = result.scalar_one_or_none()

    if user:
        user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()
        return user

    # First login — create org + user
    org = Organization(
        id=uuid4(),
        name=f"{email}'s Organization",
        slug=f"org-{uuid4().hex[:12]}",
    )
    db.add(org)
    await db.flush()

    user = User(
        id=uuid4(),
        supabase_id=supabase_id,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        organization_id=org.id,
        last_login_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(user)
    await db.commit()
    return user


async def require_supabase_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> SupabaseAuthContext:
    """FastAPI dependency — extracts Bearer token, validates, returns auth context."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth_header[7:]
    supabase_user = await _validate_supabase_token(token)
    user = await _get_or_create_user(supabase_user, db)

    return SupabaseAuthContext(
        organization_id=str(user.organization_id),
        user_id=str(user.id),
        supabase_id=user.supabase_id,
        email=user.email,
    )
