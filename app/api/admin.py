"""
One-time admin bootstrap endpoint.
Handles retries gracefully — won't fail if org already exists.
"""

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Organization
from app.middleware.auth import APIKey, generate_api_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


class BootstrapRequest(BaseModel):
    org_name: str
    setup_key: str


@router.post("/bootstrap")
async def bootstrap(
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()

    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")

    if body.setup_key != settings.click_id_secret:
        raise HTTPException(status_code=403, detail="Invalid setup key")

    # Fix column size if needed (safe to run multiple times)
    try:
        await db.execute(text("ALTER TABLE api_keys ALTER COLUMN key_type TYPE varchar(20)"))
        await db.commit()
    except Exception:
        await db.rollback()

    # Find or create org
    org_slug = body.org_name.lower().replace(" ", "-").replace("_", "-")
    stmt = select(Organization).where(Organization.slug == org_slug)
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()

    if not org:
        org = Organization(name=body.org_name, slug=org_slug)
        db.add(org)
        await db.flush()

    # Check if keys already exist for this org
    stmt = select(APIKey).where(APIKey.organization_id == org.id)
    result = await db.execute(stmt)
    existing_keys = result.scalars().all()

    if existing_keys:
        return {
            "message": "Organization already has API keys. Create a new org name to get new keys.",
            "organization": {"id": str(org.id), "name": body.org_name, "slug": org_slug},
        }

    # Generate keys
    raw_secret, secret_hash = generate_api_key("secret")
    db.add(APIKey(
        organization_id=org.id,
        key_hash=secret_hash,
        key_prefix=raw_secret[:12],
        key_type="secret",
        name="Default Secret Key",
    ))

    raw_pub, pub_hash = generate_api_key("publishable")
    db.add(APIKey(
        organization_id=org.id,
        key_hash=pub_hash,
        key_prefix=raw_pub[:12],
        key_type="publishable",
        name="Default Publishable Key",
    ))

    await db.commit()

    return {
        "message": "SAVE THESE KEYS — they won't be shown again.",
        "organization": {"id": str(org.id), "name": body.org_name, "slug": org_slug},
        "secret_key": raw_secret,
        "publishable_key": raw_pub,
    }
