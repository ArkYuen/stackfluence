"""Add universal_events table for v5 pixel

Revision ID: universal_events_005
Revises: click_deep_signals_004
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "universal_events_005"
down_revision = "click_deep_signals_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "universal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("click_id", sa.String(100), nullable=True, index=True),
        sa.Column("organization_id", sa.String(100), nullable=False, index=True),
        sa.Column("session_id", sa.String(100), nullable=True, index=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("event_source", sa.String(50), nullable=False),
        sa.Column("event_data", postgresql.JSONB, nullable=True),
        sa.Column("page_url", sa.Text, nullable=True),
        sa.Column("page_path", sa.String(500), nullable=True),
        sa.Column("page_title", sa.String(500), nullable=True),
        sa.Column("page_type", sa.String(50), nullable=True),
        sa.Column("visit_number", sa.Integer, nullable=True),
        sa.Column("pages_this_session", sa.Integer, nullable=True),
        sa.Column("days_since_first_visit", sa.Integer, nullable=True),
        sa.Column("detected_vertical", sa.String(50), nullable=True),
        sa.Column("detected_tools", postgresql.JSONB, nullable=True),
        sa.Column("conversion_score", sa.Float, nullable=True),
        sa.Column("conversion_type", sa.String(50), nullable=True),
        sa.Column("attribution_confidence", sa.String(20), nullable=True),
        sa.Column("agent_processed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("agent_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_universal_events_org_type", "universal_events", ["organization_id", "event_type"])
    op.create_index("ix_universal_events_org_created", "universal_events", ["organization_id", "created_at"])
    op.create_index("ix_universal_events_session", "universal_events", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("universal_events")
