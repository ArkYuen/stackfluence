"""initial schema v2

Revision ID: cbedd969b620
Revises:
Create Date: 2026-02-10 01:20:53.677939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cbedd969b620'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Organizations ---
    op.create_table('organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('billing_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)

    # --- Creators ---
    op.create_table('creators',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('handle', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('platform', sa.String(length=50), nullable=True),
        sa.Column('platform_user_id', sa.String(length=255), nullable=True),
        sa.Column('profile_url', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_creators_handle'), 'creators', ['handle'], unique=False)

    # --- Campaigns ---
    op.create_table('campaigns',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_campaigns_slug'), 'campaigns', ['slug'], unique=False)

    # --- Links ---
    op.create_table('links',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_handle', sa.String(length=100), nullable=False),
        sa.Column('campaign_slug', sa.String(length=100), nullable=False),
        sa.Column('asset_slug', sa.String(length=100), nullable=True),
        sa.Column('destination_url', sa.Text(), nullable=False),
        sa.Column('ios_deeplink', sa.Text(), nullable=True),
        sa.Column('ios_fallback_url', sa.Text(), nullable=True),
        sa.Column('android_deeplink', sa.Text(), nullable=True),
        sa.Column('android_fallback_url', sa.Text(), nullable=True),
        sa.Column('universal_link', sa.Text(), nullable=True),
        sa.Column('param_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['creator_id'], ['creators.id']),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_links_route_lookup', 'links', ['creator_handle', 'campaign_slug', 'asset_slug'], unique=True)

    # --- API Keys ---
    op.create_table('api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('key_prefix', sa.String(length=12), nullable=False),
        sa.Column('key_type', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('rate_limit_per_minute', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)
    op.create_index(op.f('ix_api_keys_key_prefix'), 'api_keys', ['key_prefix'], unique=False)

    # --- Click Events ---
    op.create_table('click_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('session_id', sa.String(length=100), nullable=True),
        sa.Column('link_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=False),
        # Destinations
        sa.Column('destination_url_raw', sa.Text(), nullable=False),
        sa.Column('destination_url_final', sa.Text(), nullable=False),
        # Params
        sa.Column('utm', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('injected_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('platform_click_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('query_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Source provenance
        sa.Column('referrer_header', sa.Text(), nullable=True),
        sa.Column('document_referrer', sa.Text(), nullable=True),
        sa.Column('collector_page_url', sa.Text(), nullable=True),
        # source_best added via raw SQL below (computed column)
        # Source intelligence
        sa.Column('source_platform', sa.String(length=50), nullable=True),
        sa.Column('source_medium', sa.String(length=50), nullable=True),
        sa.Column('source_detail', sa.String(length=50), nullable=True),
        sa.Column('is_in_app_browser', sa.Boolean(), nullable=True),
        sa.Column('in_app_platform', sa.String(length=50), nullable=True),
        sa.Column('referer_domain', sa.String(length=255), nullable=True),
        # Network
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        # Sec-Fetch headers
        sa.Column('sec_fetch_site', sa.String(length=50), nullable=True),
        sa.Column('sec_fetch_mode', sa.String(length=50), nullable=True),
        sa.Column('sec_fetch_dest', sa.String(length=50), nullable=True),
        sa.Column('sec_fetch_user', sa.String(length=10), nullable=True),
        # User agent
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('ua_parsed', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_webview_guess', sa.Boolean(), nullable=True),
        # Device
        sa.Column('device_class', sa.String(length=20), nullable=True),
        sa.Column('os_family', sa.String(length=50), nullable=True),
        sa.Column('os_version', sa.String(length=20), nullable=True),
        sa.Column('browser_family', sa.String(length=50), nullable=True),
        sa.Column('browser_version', sa.String(length=20), nullable=True),
        sa.Column('is_mobile', sa.Boolean(), nullable=True),
        # Geo
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('region', sa.String(length=100), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('asn', sa.Integer(), nullable=True),
        sa.Column('isp', sa.String(length=255), nullable=True),
        # Language
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('locale', sa.String(length=10), nullable=True),
        # Client telemetry
        sa.Column('client_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Bot / fraud
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('bot_blocked', sa.Boolean(), nullable=True),
        sa.Column('is_suspected_bot', sa.Boolean(), nullable=True),
        sa.Column('bot_reason', sa.Text(), nullable=True),
        sa.Column('bot_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Timing
        sa.Column('server_received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('server_responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('collector_received_at', sa.DateTime(timezone=True), nullable=True),
        # Flags
        sa.Column('used_collector', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(['link_id'], ['links.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_click_events_click_id'), 'click_events', ['click_id'], unique=True)
    op.create_index(op.f('ix_click_events_organization_id'), 'click_events', ['organization_id'], unique=False)
    op.create_index('ix_click_events_org_created', 'click_events', ['organization_id', 'created_at'], unique=False)
    op.create_index('ix_click_events_creator_created', 'click_events', ['creator_id', 'created_at'], unique=False)
    op.create_index('ix_click_events_source', 'click_events', ['organization_id', 'source_platform', 'source_medium'], unique=False)

    # Computed column — Alembic can't do this natively
    op.execute("""
        ALTER TABLE click_events
        ADD COLUMN source_best TEXT GENERATED ALWAYS AS (COALESCE(document_referrer, referrer_header)) STORED
    """)

    # --- Click Events Log (firehose) ---
    op.create_table('click_events_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_click_events_log_click_id'), 'click_events_log', ['click_id'], unique=False)

    # --- Session Events ---
    op.create_table('session_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(length=100), nullable=True),
        sa.Column('page_url', sa.Text(), nullable=True),
        sa.Column('referrer', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_session_events_click_id'), 'session_events', ['click_id'], unique=False)
    op.create_index(op.f('ix_session_events_organization_id'), 'session_events', ['organization_id'], unique=False)

    # --- Page View Events ---
    op.create_table('pageview_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('page_url', sa.Text(), nullable=True),
        sa.Column('time_on_page_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pageview_events_click_id'), 'pageview_events', ['click_id'], unique=False)
    op.create_index(op.f('ix_pageview_events_organization_id'), 'pageview_events', ['organization_id'], unique=False)

    # --- Conversion Events ---
    op.create_table('conversion_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('order_id', sa.String(length=255), nullable=True),
        sa.Column('revenue_cents', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conversion_events_click_id'), 'conversion_events', ['click_id'], unique=False)
    op.create_index(op.f('ix_conversion_events_organization_id'), 'conversion_events', ['organization_id'], unique=False)
    op.create_index('ix_conversion_events_org_type', 'conversion_events', ['organization_id', 'event_type'], unique=False)

    # --- Refund Events ---
    op.create_table('refund_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('click_id', sa.String(length=100), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('original_order_id', sa.String(length=255), nullable=True),
        sa.Column('refund_amount_cents', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_refund_events_click_id'), 'refund_events', ['click_id'], unique=False)
    op.create_index(op.f('ix_refund_events_organization_id'), 'refund_events', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_table('refund_events')
    op.drop_table('conversion_events')
    op.drop_table('pageview_events')
    op.drop_table('session_events')
    op.drop_table('click_events_log')
    op.drop_table('click_events')
    op.drop_table('api_keys')
    op.drop_table('links')
    op.drop_table('campaigns')
    op.drop_table('creators')
    op.drop_table('organizations')
