"""Add pixel_configs table for server-side CAPI integration

Revision ID: pixel_configs_006
Revises: universal_events_005
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision = "pixel_configs_006"
down_revision = "universal_events_005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'pixel_configs' not in existing_tables:
        op.create_table(
            'pixel_configs',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False),
            sa.Column('link_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('links.id'), nullable=True),
            sa.Column('platform', sa.String(50), nullable=False),
            sa.Column('pixel_id', sa.String(255), nullable=False),
            sa.Column('access_token', sa.Text, nullable=True),
            sa.Column('test_event_code', sa.String(100), nullable=True),
            sa.Column('enabled', sa.Boolean, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        existing_indexes = [i['name'] for i in inspector.get_indexes('pixel_configs')] if 'pixel_configs' in existing_tables else []
        if 'ix_pixel_configs_org' not in existing_indexes:
            op.create_index('ix_pixel_configs_org', 'pixel_configs', ['organization_id'])
        if 'ix_pixel_configs_link' not in existing_indexes:
            op.create_index('ix_pixel_configs_link', 'pixel_configs', ['link_id'])


def downgrade():
    op.drop_index('ix_pixel_configs_link')
    op.drop_index('ix_pixel_configs_org')
    op.drop_table('pixel_configs')
