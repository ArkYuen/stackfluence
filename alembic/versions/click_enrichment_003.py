"""add enriched click tracking columns to click_events

Revision ID: click_enrichment_003
Revises: links_source_002
Create Date: 2026-02-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'click_enrichment_003'
down_revision = 'links_source_002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Screen & viewport
    op.add_column('click_events', sa.Column('screen_width', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('screen_height', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('viewport_width', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('viewport_height', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('color_depth', sa.Integer(), nullable=True))

    # Client environment
    op.add_column('click_events', sa.Column('timezone', sa.String(100), nullable=True))
    op.add_column('click_events', sa.Column('connection_type', sa.String(20), nullable=True))
    op.add_column('click_events', sa.Column('touch_support', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('hardware_concurrency', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('device_memory', sa.Float(), nullable=True))
    op.add_column('click_events', sa.Column('do_not_track', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('ad_blocker_detected', sa.Boolean(), nullable=True))

    # Engagement signals
    op.add_column('click_events', sa.Column('is_repeat_visitor', sa.Boolean(), server_default='false'))
    op.add_column('click_events', sa.Column('click_number', sa.Integer(), server_default='1'))
    op.add_column('click_events', sa.Column('redirect_latency_ms', sa.Integer(), nullable=True))

    # Indexes for common queries
    op.create_index('ix_click_events_timezone', 'click_events', ['timezone'])
    op.create_index('ix_click_events_connection', 'click_events', ['connection_type'])
    op.create_index('ix_click_events_repeat', 'click_events', ['is_repeat_visitor'])


def downgrade() -> None:
    op.drop_index('ix_click_events_repeat')
    op.drop_index('ix_click_events_connection')
    op.drop_index('ix_click_events_timezone')

    op.drop_column('click_events', 'redirect_latency_ms')
    op.drop_column('click_events', 'click_number')
    op.drop_column('click_events', 'is_repeat_visitor')
    op.drop_column('click_events', 'ad_blocker_detected')
    op.drop_column('click_events', 'do_not_track')
    op.drop_column('click_events', 'device_memory')
    op.drop_column('click_events', 'hardware_concurrency')
    op.drop_column('click_events', 'touch_support')
    op.drop_column('click_events', 'connection_type')
    op.drop_column('click_events', 'timezone')
    op.drop_column('click_events', 'color_depth')
    op.drop_column('click_events', 'viewport_height')
    op.drop_column('click_events', 'viewport_width')
    op.drop_column('click_events', 'screen_height')
    op.drop_column('click_events', 'screen_width')
