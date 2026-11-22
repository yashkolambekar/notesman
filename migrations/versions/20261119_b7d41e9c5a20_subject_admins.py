"""per-subject admin grants

Revision ID: b7d41e9c5a20
Revises: a1c0b7e4d2f3
Create Date: 2026-11-19 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d41e9c5a20"
down_revision: Union[str, Sequence[str], None] = "a1c0b7e4d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subject_admins",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_subject_admins_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name=op.f("fk_subject_admins_subject_id_subjects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "subject_id", name=op.f("pk_subject_admins")),
    )
    op.create_index(op.f("ix_subject_admins_subject_id"), "subject_admins", ["subject_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_subject_admins_subject_id"), table_name="subject_admins")
    op.drop_table("subject_admins")
