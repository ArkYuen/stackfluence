"""platform_connections — enterprise OAuth + token management

Revision ID: platform_connections_009
Revises: pixel_configs_006
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect

revision = 'platform_connections_009'
down_revision = 'pixel_configs_006'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'platform_connections' not in existing_tables:
        op.create_table(
            'platform_connections',
            sa.Column('id', UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('org_id', UUID(as_uuid=True),
                      sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('platform', sa.String(30), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='active'),
            sa.Column('auth_type', sa.String(10), nullable=False, server_default='token'),
            sa.Column('access_token_encrypted', sa.Text, nullable=True),
            sa.Column('refresh_token_encrypted', sa.Text, nullable=True),
            sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('oauth_scope', sa.Text, nullable=True),
            sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('refresh_fail_count', sa.Integer, server_default='0'),
            sa.Column('platform_account_id', sa.String(255), nullable=True),
            sa.Column('platform_account_label', sa.String(255), nullable=True),
            sa.Column('secondary_id', sa.String(255), nullable=True),
            sa.Column('link_id', UUID(as_uuid=True),
                      sa.ForeignKey('links.id', ondelete='CASCADE'), nullable=True),
            sa.Column('connected_by', UUID(as_uuid=True), nullable=True),
            sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_event_status', sa.String(20), nullable=True),
            sa.Column('total_events_fired', sa.Integer, server_default='0'),
            sa.Column('enabled', sa.Boolean, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        )
        op.create_index('ix_platform_connections_org_id', 'platform_connections', ['org_id'])
        op.create_index('ix_platform_connections_org_platform', 'platform_connections', ['org_id', 'platform'])
        op.create_unique_constraint(
            'uq_platform_connection_org_platform_link',
            'platform_connections',
            ['org_id', 'platform', 'link_id'],
        )

    if 'token_refresh_log' not in existing_tables:
        op.create_table(
            'token_refresh_log',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('connection_id', UUID(as_uuid=True), nullable=False, index=True),
            sa.Column('org_id', UUID(as_uuid=True), nullable=False),
            sa.Column('platform', sa.String(30), nullable=False),
            sa.Column('outcome', sa.String(20), nullable=False),
            sa.Column('error_message', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        )


def downgrade():
    op.drop_table('token_refresh_log')
    op.drop_table('platform_connections')
