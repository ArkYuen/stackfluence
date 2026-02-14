"""add demo_links table

Revision ID: demo_links_001
Revises: 
Create Date: 2026-02-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'demo_links_001'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'demo_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('slug', sa.String(20), nullable=False, unique=True),
        sa.Column('original_url', sa.Text(), nullable=False),
        sa.Column('wrapped_url', sa.Text(), nullable=False),
        sa.Column('link_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_ip', sa.String(45), nullable=True),
        sa.Column('creator_user_agent', sa.Text(), nullable=True),
        sa.Column('creator_fingerprint', sa.String(64), nullable=True),
        sa.Column('click_count', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('creator_email', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    op.create_index('ix_demo_links_slug', 'demo_links', ['slug'], unique=True)
    op.create_index('ix_demo_links_link_id', 'demo_links', ['link_id'])
    op.create_index('ix_demo_links_ip_created', 'demo_links', ['creator_ip', 'created_at'])
    op.create_index('ix_demo_links_created', 'demo_links', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_demo_links_created')
    op.drop_index('ix_demo_links_ip_created')
    op.drop_index('ix_demo_links_link_id')
    op.drop_index('ix_demo_links_slug')
    op.drop_table('demo_links')
