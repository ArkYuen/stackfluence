"""add source column to links table

Revision ID: links_source_002
Revises: demo_links_001
Create Date: 2026-02-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'links_source_002'
down_revision = 'demo_links_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'links',
        sa.Column('source', sa.String(20), nullable=False, server_default='member')
    )
    op.create_index('ix_links_source', 'links', ['source'])

    # Backfill existing demo links
    op.execute("""
        UPDATE links SET source = 'demo'
        WHERE creator_handle = 'demo' AND campaign_slug = 'website-demo'
    """)


def downgrade() -> None:
    op.drop_index('ix_links_source', 'links')
    op.drop_column('links', 'source')
