"""questions.evaluation: on-demand answer scores

Revision ID: f1c4d7a98b35
Revises: e5b8c1d27a96
Create Date: 2026-11-22 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f1c4d7a98b35"
down_revision: Union[str, Sequence[str], None] = "e5b8c1d27a96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "evaluation")
