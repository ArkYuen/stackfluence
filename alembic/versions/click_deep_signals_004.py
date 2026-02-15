"""add fingerprinting, performance, and IP enrichment columns to click_events

Revision ID: click_deep_signals_004
Revises: click_enrichment_003
Create Date: 2026-02-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'click_deep_signals_004'
down_revision = 'click_enrichment_003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Device fingerprinting
    op.add_column('click_events', sa.Column('webgl_renderer', sa.String(255), nullable=True))
    op.add_column('click_events', sa.Column('canvas_fingerprint', sa.String(64), nullable=True))
    op.add_column('click_events', sa.Column('audio_fingerprint', sa.String(64), nullable=True))
    op.add_column('click_events', sa.Column('installed_fonts_hash', sa.String(64), nullable=True))
    op.add_column('click_events', sa.Column('pdf_viewer_enabled', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('battery_charging', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('battery_level', sa.Float(), nullable=True))

    # Page load performance
    op.add_column('click_events', sa.Column('perf_dns_ms', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('perf_tcp_ms', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('perf_tls_ms', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('perf_ttfb_ms', sa.Integer(), nullable=True))
    op.add_column('click_events', sa.Column('perf_load_ms', sa.Integer(), nullable=True))

    # Server-side headers
    op.add_column('click_events', sa.Column('accept_language_full', sa.Text(), nullable=True))
    op.add_column('click_events', sa.Column('header_order', sa.Text(), nullable=True))

    # IP enrichment
    op.add_column('click_events', sa.Column('is_vpn', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('is_tor', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('is_residential', sa.Boolean(), nullable=True))
    op.add_column('click_events', sa.Column('ip_reputation_score', sa.Float(), nullable=True))
    op.add_column('click_events', sa.Column('ip_company_name', sa.String(255), nullable=True))

    # Indexes for fingerprint-based queries
    op.create_index('ix_click_events_canvas_fp', 'click_events', ['canvas_fingerprint'])
    op.create_index('ix_click_events_webgl', 'click_events', ['webgl_renderer'])
    op.create_index('ix_click_events_vpn', 'click_events', ['is_vpn'])


def downgrade() -> None:
    op.drop_index('ix_click_events_vpn')
    op.drop_index('ix_click_events_webgl')
    op.drop_index('ix_click_events_canvas_fp')

    op.drop_column('click_events', 'ip_company_name')
    op.drop_column('click_events', 'ip_reputation_score')
    op.drop_column('click_events', 'is_residential')
    op.drop_column('click_events', 'is_tor')
    op.drop_column('click_events', 'is_vpn')
    op.drop_column('click_events', 'header_order')
    op.drop_column('click_events', 'accept_language_full')
    op.drop_column('click_events', 'perf_load_ms')
    op.drop_column('click_events', 'perf_ttfb_ms')
    op.drop_column('click_events', 'perf_tls_ms')
    op.drop_column('click_events', 'perf_tcp_ms')
    op.drop_column('click_events', 'perf_dns_ms')
    op.drop_column('click_events', 'battery_level')
    op.drop_column('click_events', 'battery_charging')
    op.drop_column('click_events', 'pdf_viewer_enabled')
    op.drop_column('click_events', 'installed_fonts_hash')
    op.drop_column('click_events', 'audio_fingerprint')
    op.drop_column('click_events', 'canvas_fingerprint')
    op.drop_column('click_events', 'webgl_renderer')
