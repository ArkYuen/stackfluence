"""
One-time admin bootstrap endpoint.

GET /admin/bootstrap?org_name=MyBrand

Creates an organization and generates API keys.
Protected by a setup secret to prevent unauthorized use.
Delete this file after you've bootstrapped your first org.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.tables import Base, Organization
from app.middleware.auth import APIKey, generate_api_key

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/bootstrap")
async def bootstrap(
    org_name: str = Query(..., description="Your organization name"),
    setup_key: str = Query(..., description="Must match SF_CLICK_ID_SECRET"),
    db: AsyncSession = Depends(get_db),
):
    """One-time setup: create org + API keys.

    Protected by requiring your SF_CLICK_ID_SECRET as the setup_key parameter.
    """
    settings = get_settings()

    # Protect with the secret
    if setup_key != settings.click_id_secret:
        raise HTTPException(status_code=403, detail="Invalid setup key")

    # Create org
    org_slug = org_name.lower().replace(" ", "-").replace("_", "-")
    org = Organization(name=org_name, slug=org_slug)
    db.add(org)
    await db.flush()

    # Generate secret key
    raw_secret, secret_hash = generate_api_key("secret")
    secret_key_record = APIKey(
        organization_id=org.id,
        key_hash=secret_hash,
        key_prefix=raw_secret[:12],
        key_type="secret",
        name="Default Secret Key",
    )
    db.add(secret_key_record)

    # Generate publishable key
    raw_pub, pub_hash = generate_api_key("publishable")
    pub_key_record = APIKey(
        organization_id=org.id,
        key_hash=pub_hash,
        key_prefix=raw_pub[:12],
        key_type="publishable",
        name="Default Publishable Key",
    )
    db.add(pub_key_record)

    await db.commit()

    logger.info("bootstrap_complete", org=org_name, org_id=str(org.id))

    return {
        "message": "Organization and API keys created. SAVE THESE KEYS — they won't be shown again.",
        "organization": {
            "id": str(org.id),
            "name": org_name,
            "slug": org_slug,
        },
        "secret_key": raw_secret,
        "publishable_key": raw_pub,
        "next_steps": {
            "create_link": f"curl -X POST {settings.base_url}/v1/links/quick -H 'Content-Type: application/json' -H 'X-API-Key: {raw_secret}' -d '{{\"destination_url\": \"https://yourbrand.com\", \"creator\": \"emma\", \"campaign\": \"test\"}}'",
            "js_snippet": f'<script src="https://cdn.stackfluence.com/sf.js" data-key="{raw_pub}" data-org="{org.id}"></script>',
        },
    }
