"""usage_events: what each paid call cost

Revision ID: e5b8c1d27a96
Revises: d9a2f6b3c814
Create Date: 2026-11-22 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5b8c1d27a96"
down_revision: Union[str, Sequence[str], None] = "d9a2f6b3c814"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=True),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("file_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("kind IN ('chat', 'embed')", name=op.f("ck_usage_events_kind")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_usage_events_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], name=op.f("fk_usage_events_question_id_questions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name=op.f("fk_usage_events_subject_id_subjects"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], name=op.f("fk_usage_events_file_id_files"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_created_at"), "usage_events", ["created_at"])
    op.create_index(op.f("ix_usage_events_question_id"), "usage_events", ["question_id"])
    op.create_index(op.f("ix_usage_events_subject_id"), "usage_events", ["subject_id"])


def downgrade() -> None:
    op.drop_table("usage_events")
