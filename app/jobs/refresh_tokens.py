"""
Token refresh job — runs hourly via Railway cron.
Refreshes OAuth tokens before they expire.
Alerts org owners if refresh fails repeatedly.
"""
import asyncio
import os
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.encryption import encrypt_token, decrypt_token
from app.models.platform_connection import PlatformConnection, TokenRefreshLog

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

REFRESH_THRESHOLD_DAYS = 7
MAX_FAIL_COUNT = 3


async def refresh_google(conn: PlatformConnection, db: AsyncSession) -> bool:
    refresh_token = decrypt_token(conn.refresh_token_encrypted)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            return False
        tokens = resp.json()

    conn.access_token_encrypted = encrypt_token(tokens["access_token"])
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    conn.last_refreshed_at = datetime.now(timezone.utc)
    conn.refresh_fail_count = 0
    return True


async def refresh_tiktok(conn: PlatformConnection, db: AsyncSession) -> bool:
    refresh_token = decrypt_token(conn.refresh_token_encrypted)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/",
            json={
                "app_id": os.environ["TIKTOK_APP_ID"],
                "secret": os.environ["TIKTOK_APP_SECRET"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            return False
        data = resp.json().get("data", {})

    conn.access_token_encrypted = encrypt_token(data.get("access_token", ""))
    conn.refresh_token_encrypted = encrypt_token(data.get("refresh_token", ""))
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=data.get("expires_in", 86400)
    )
    conn.last_refreshed_at = datetime.now(timezone.utc)
    conn.refresh_fail_count = 0
    return True


async def refresh_linkedin(conn: PlatformConnection, db: AsyncSession) -> bool:
    refresh_token = decrypt_token(conn.refresh_token_encrypted)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.environ["LINKEDIN_CLIENT_ID"],
                "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            return False
        tokens = resp.json()

    conn.access_token_encrypted = encrypt_token(tokens.get("access_token", ""))
    if tokens.get("refresh_token"):
        conn.refresh_token_encrypted = encrypt_token(tokens["refresh_token"])
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 5184000)
    )
    conn.last_refreshed_at = datetime.now(timezone.utc)
    conn.refresh_fail_count = 0
    return True


REFRESH_HANDLERS = {
    "ga4": refresh_google,
    "google_ads": refresh_google,
    "tiktok": refresh_tiktok,
    "linkedin": refresh_linkedin,
}


async def run_refresh():
    async with AsyncSessionLocal() as db:
        threshold = datetime.now(timezone.utc) + timedelta(days=REFRESH_THRESHOLD_DAYS)
        result = await db.execute(
            select(PlatformConnection).where(
                PlatformConnection.auth_type == "oauth",
                PlatformConnection.status == "active",
                PlatformConnection.token_expires_at <= threshold,
                PlatformConnection.refresh_token_encrypted != None,
            )
        )
        connections = result.scalars().all()

        logger.info(f"Token refresh job: {len(connections)} connections to refresh")

        for conn in connections:
            handler = REFRESH_HANDLERS.get(conn.platform)
            if not handler:
                continue

            error_msg = None
            try:
                success = await handler(conn, db)
                outcome = "success" if success else "failed"

                if not success:
                    conn.refresh_fail_count += 1
                    if conn.refresh_fail_count >= MAX_FAIL_COUNT:
                        conn.status = "needs_reauth"
                        logger.warning(
                            f"Connection {conn.id} ({conn.platform}) marked needs_reauth "
                            f"after {conn.refresh_fail_count} failures"
                        )

            except Exception as e:
                outcome = "failed"
                conn.refresh_fail_count += 1
                error_msg = str(e)
                logger.error(f"Refresh error for {conn.id}: {error_msg}")

            log = TokenRefreshLog(
                connection_id=conn.id,
                org_id=conn.org_id,
                platform=conn.platform,
                outcome=outcome,
                error_message=error_msg if outcome == "failed" else None,
            )
            db.add(log)

        await db.commit()
        logger.info("Token refresh job complete.")


if __name__ == "__main__":
    asyncio.run(run_refresh())
