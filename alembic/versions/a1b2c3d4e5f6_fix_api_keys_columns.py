"""fix api_keys columns

Revision ID: a1b2c3d4e5f6
Revises: cbedd969b620
Create Date: 2026-02-10 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'cbedd969b620'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename label -> name
    op.alter_column('api_keys', 'label', new_column_name='name')
    # Widen key_prefix from 10 -> 12
    op.alter_column('api_keys', 'key_prefix',
                     existing_type=sa.String(length=10),
                     type_=sa.String(length=12))
    # Add missing columns
    op.add_column('api_keys', sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('api_keys', sa.Column('rate_limit_per_minute', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('api_keys', 'rate_limit_per_minute')
    op.drop_column('api_keys', 'last_used_at')
    op.alter_column('api_keys', 'key_prefix',
                     existing_type=sa.String(length=12),
                     type_=sa.String(length=10))
    op.alter_column('api_keys', 'name', new_column_name='label')
