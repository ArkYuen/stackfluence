"""
Platform connection management.
Handles both paste-token and OAuth connection types.
"""
import os
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_token, decrypt_token
from app.models.database import get_db
from app.models.platform_connection import PlatformConnection
from app.middleware.supabase_auth import require_org_member, require_org_role

router = APIRouter(tags=["connections"])

# ── Constants ──────────────────────────────────────────────────────────────

PASTE_TOKEN_PLATFORMS = {"meta", "snapchat", "reddit", "pinterest"}
OAUTH_PLATFORMS = {"google", "tiktok", "linkedin"}

# GA4 and Google Ads share one Google OAuth connection
GOOGLE_SCOPE = (
    "https://www.googleapis.com/auth/analytics.readonly "
    "https://www.googleapis.com/auth/adwords"
)
TIKTOK_SCOPE = "user.info.basic,business.get"
LINKEDIN_SCOPE = "r_ads_reporting,rw_conversions,r_organization_social"

# ── Schemas ────────────────────────────────────────────────────────────────

class PasteTokenRequest(BaseModel):
    platform: str
    platform_account_id: str
    platform_account_label: Optional[str] = None
    secondary_id: Optional[str] = None
    link_id: Optional[UUID] = None

class ConnectionOut(BaseModel):
    id: UUID
    platform: str
    status: str
    auth_type: str
    platform_account_id: Optional[str]
    platform_account_label: Optional[str]
    secondary_id: Optional[str]
    link_id: Optional[UUID]
    connected_by: Optional[UUID]
    connected_at: Optional[datetime]
    last_event_at: Optional[datetime]
    last_event_status: Optional[str]
    total_events_fired: int
    enabled: bool
    token_expires_at: Optional[datetime]
    refresh_fail_count: int
    created_at: datetime

    model_config = {"from_attributes": True}

# ── List connections ───────────────────────────────────────────────────────

@router.get("/v1/orgs/{org_id}/connections", response_model=list[ConnectionOut])
async def list_connections(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    caller=Depends(require_org_member),
):
    result = await db.execute(
        select(PlatformConnection)
        .where(PlatformConnection.org_id == org_id)
        .order_by(PlatformConnection.platform)
    )
    return result.scalars().all()

# ── Paste-token connect (Meta, Snap, Reddit, Pinterest) ───────────────────

@router.post("/v1/orgs/{org_id}/connections/token",
             status_code=status.HTTP_201_CREATED,
             response_model=ConnectionOut)
async def connect_paste_token(
    org_id: UUID,
    body: PasteTokenRequest,
    db: AsyncSession = Depends(get_db),
    caller=Depends(require_org_role(["owner", "admin"])),
):
    if body.platform not in PASTE_TOKEN_PLATFORMS:
        raise HTTPException(status_code=400,
            detail=f"{body.platform} requires OAuth. Use /v1/oauth/{body.platform}/connect instead.")

    # Upsert — if connection exists for this org+platform+link, update it
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.org_id == org_id,
            PlatformConnection.platform == body.platform,
            PlatformConnection.link_id == body.link_id,
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.platform_account_id = body.platform_account_id
        conn.platform_account_label = body.platform_account_label
        conn.secondary_id = body.secondary_id
        conn.status = "active"
        conn.connected_by = caller.user_id
        conn.connected_at = datetime.now(timezone.utc)
    else:
        conn = PlatformConnection(
            org_id=org_id,
            platform=body.platform,
            auth_type="token",
            status="active",
            platform_account_id=body.platform_account_id,
            platform_account_label=body.platform_account_label,
            secondary_id=body.secondary_id,
            link_id=body.link_id,
            connected_by=caller.user_id,
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)

    await db.commit()
    await db.refresh(conn)
    return conn

# ── Toggle enable/disable ──────────────────────────────────────────────────

@router.patch("/v1/orgs/{org_id}/connections/{connection_id}/toggle")
async def toggle_connection(
    org_id: UUID,
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    caller=Depends(require_org_role(["owner", "admin"])),
):
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.id == connection_id,
            PlatformConnection.org_id == org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    conn.enabled = not conn.enabled
    await db.commit()
    return {"enabled": conn.enabled}

# ── Disconnect ─────────────────────────────────────────────────────────────

@router.delete("/v1/orgs/{org_id}/connections/{connection_id}")
async def disconnect_platform(
    org_id: UUID,
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    caller=Depends(require_org_role(["owner", "admin"])),
):
    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.id == connection_id,
            PlatformConnection.org_id == org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")
    conn.status = "disconnected"
    conn.access_token_encrypted = None
    conn.refresh_token_encrypted = None
    await db.commit()
    return {"message": "Platform disconnected."}

# ── OAuth: Google ──────────────────────────────────────────────────────────

@router.get("/v1/oauth/google/connect")
async def google_oauth_connect(org_id: UUID, request: Request):
    """Initiate Google OAuth flow."""
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": f"{state}:{org_id}",
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    response = RedirectResponse(url)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True, secure=True)
    return response


@router.get("/v1/oauth/google/callback")
async def google_oauth_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback. Exchange code for tokens."""
    state_parts = state.split(":")
    if len(state_parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    state_token, org_id = state_parts[0], state_parts[1]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"],
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Google token exchange failed.")
        tokens = resp.json()

    import datetime as dt
    expires_at = datetime.now(timezone.utc) + dt.timedelta(seconds=tokens.get("expires_in", 3600))

    for platform in ["ga4", "google_ads"]:
        result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.org_id == org_id,
                PlatformConnection.platform == platform,
                PlatformConnection.link_id == None,
            )
        )
        conn = result.scalar_one_or_none()
        if conn:
            conn.access_token_encrypted = encrypt_token(tokens["access_token"])
            conn.refresh_token_encrypted = encrypt_token(tokens.get("refresh_token", ""))
            conn.token_expires_at = expires_at
            conn.oauth_scope = tokens.get("scope")
            conn.status = "active"
            conn.auth_type = "oauth"
            conn.connected_at = datetime.now(timezone.utc)
            conn.refresh_fail_count = 0
        else:
            conn = PlatformConnection(
                org_id=org_id,
                platform=platform,
                auth_type="oauth",
                status="active",
                access_token_encrypted=encrypt_token(tokens["access_token"]),
                refresh_token_encrypted=encrypt_token(tokens.get("refresh_token", "")),
                token_expires_at=expires_at,
                oauth_scope=tokens.get("scope"),
                connected_at=datetime.now(timezone.utc),
            )
            db.add(conn)

    await db.commit()
    return RedirectResponse(
        f"{os.environ.get('FRONTEND_URL', 'https://app.stackfluence.com')}"
        f"/settings/connections?connected=google"
    )

# ── OAuth: TikTok ──────────────────────────────────────────────────────────

@router.get("/v1/oauth/tiktok/connect")
async def tiktok_oauth_connect(org_id: UUID, request: Request):
    state = secrets.token_urlsafe(32)
    params = {
        "client_key": os.environ["TIKTOK_APP_ID"],
        "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
        "response_type": "code",
        "scope": TIKTOK_SCOPE,
        "state": f"{state}:{org_id}",
    }
    from urllib.parse import urlencode
    url = "https://business-api.tiktok.com/portal/auth?" + urlencode(params)
    response = RedirectResponse(url)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True, secure=True)
    return response


@router.get("/v1/oauth/tiktok/callback")
async def tiktok_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    state_parts = state.split(":")
    org_id = state_parts[1] if len(state_parts) == 2 else None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
            json={
                "app_id": os.environ["TIKTOK_APP_ID"],
                "secret": os.environ["TIKTOK_APP_SECRET"],
                "auth_code": code,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="TikTok token exchange failed.")
        data = resp.json().get("data", {})

    import datetime as dt
    expires_at = datetime.now(timezone.utc) + dt.timedelta(
        seconds=data.get("expires_in", 86400)
    )

    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.org_id == org_id,
            PlatformConnection.platform == "tiktok",
            PlatformConnection.link_id == None,
        )
    )
    conn = result.scalar_one_or_none()

    token_data = {
        "access_token_encrypted": encrypt_token(data.get("access_token", "")),
        "refresh_token_encrypted": encrypt_token(data.get("refresh_token", "")),
        "token_expires_at": expires_at,
        "status": "active",
        "auth_type": "oauth",
        "connected_at": datetime.now(timezone.utc),
        "refresh_fail_count": 0,
    }

    if conn:
        for k, v in token_data.items():
            setattr(conn, k, v)
    else:
        conn = PlatformConnection(
            org_id=org_id,
            platform="tiktok",
            **token_data,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(
        f"{os.environ.get('FRONTEND_URL', 'https://app.stackfluence.com')}"
        f"/settings/connections?connected=tiktok"
    )

# ── OAuth: LinkedIn ────────────────────────────────────────────────────────

@router.get("/v1/oauth/linkedin/connect")
async def linkedin_oauth_connect(org_id: UUID, request: Request):
    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
        "scope": LINKEDIN_SCOPE,
        "state": f"{state}:{org_id}",
    }
    from urllib.parse import urlencode
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params)
    response = RedirectResponse(url)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True, secure=True)
    return response


@router.get("/v1/oauth/linkedin/callback")
async def linkedin_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    state_parts = state.split(":")
    org_id = state_parts[1] if len(state_parts) == 2 else None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
                "client_id": os.environ["LINKEDIN_CLIENT_ID"],
                "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="LinkedIn token exchange failed.")
        tokens = resp.json()

    import datetime as dt
    expires_at = datetime.now(timezone.utc) + dt.timedelta(
        seconds=tokens.get("expires_in", 5184000)
    )

    result = await db.execute(
        select(PlatformConnection).where(
            PlatformConnection.org_id == org_id,
            PlatformConnection.platform == "linkedin",
            PlatformConnection.link_id == None,
        )
    )
    conn = result.scalar_one_or_none()

    token_data = {
        "access_token_encrypted": encrypt_token(tokens.get("access_token", "")),
        "refresh_token_encrypted": encrypt_token(tokens.get("refresh_token", "")),
        "token_expires_at": expires_at,
        "oauth_scope": LINKEDIN_SCOPE,
        "status": "active",
        "auth_type": "oauth",
        "connected_at": datetime.now(timezone.utc),
        "refresh_fail_count": 0,
    }

    if conn:
        for k, v in token_data.items():
            setattr(conn, k, v)
    else:
        conn = PlatformConnection(
            org_id=org_id,
            platform="linkedin",
            **token_data,
        )
        db.add(conn)

    await db.commit()
    return RedirectResponse(
        f"{os.environ.get('FRONTEND_URL', 'https://app.stackfluence.com')}"
        f"/settings/connections?connected=linkedin"
    )
