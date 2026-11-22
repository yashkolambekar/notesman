"""admins bring their own API keys (stored encrypted)

Revision ID: c3e5a8d17f40
Revises: b7d41e9c5a20
Create Date: 2026-11-22 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3e5a8d17f40"
down_revision: Union[str, Sequence[str], None] = "b7d41e9c5a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_api_keys",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("gemini_enc", sa.Text(), nullable=True),
        sa.Column("openrouter_enc", sa.Text(), nullable=True),
        sa.Column("gemini_hint", sa.String(length=8), nullable=True),
        sa.Column("openrouter_hint", sa.String(length=8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_api_keys_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_api_keys")),
    )
    op.add_column("jobs", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_jobs_user_id_users"), "jobs", "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_jobs_user_id_users"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "user_id")
    op.drop_table("user_api_keys")
