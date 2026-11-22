"""archive subjects and papers

Revision ID: d9a2f6b3c814
Revises: c3e5a8d17f40
Create Date: 2026-11-22 13:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9a2f6b3c814"
down_revision: Union[str, Sequence[str], None] = "c3e5a8d17f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("papers", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "archived_at")
    op.drop_column("subjects", "archived_at")
