"""Add pixel_configs table for server-side CAPI integration

Revision ID: pixel_configs_006
Revises: universal_events_005
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "pixel_configs_006"
down_revision = "universal_events_005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pixel_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('link_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('links.id'), nullable=True),  # null = org-level
        sa.Column('platform', sa.String(50), nullable=False),  # meta, tiktok, ga4, google_ads, snapchat
        sa.Column('pixel_id', sa.String(255), nullable=False),
        sa.Column('access_token', sa.Text, nullable=True),  # for server-side CAPI
        sa.Column('test_event_code', sa.String(100), nullable=True),  # Meta test events
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_pixel_configs_org', 'pixel_configs', ['organization_id'])
    op.create_index('ix_pixel_configs_link', 'pixel_configs', ['link_id'])


def downgrade():
    op.drop_index('ix_pixel_configs_link')
    op.drop_index('ix_pixel_configs_org')
    op.drop_table('pixel_configs')
