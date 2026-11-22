"""add courses above subjects

Existing subjects move into a single course named "Course 1" (rename it later).

Revision ID: a1c0b7e4d2f3
Revises: 39c021ee2dbe
Create Date: 2026-11-19 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1c0b7e4d2f3"
down_revision: Union[str, Sequence[str], None] = "39c021ee2dbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_courses_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
    )
    op.add_column("subjects", sa.Column("course_id", sa.UUID(), nullable=True))
    # Only create the placeholder course when there is something to put in it.
    op.execute("INSERT INTO courses (name) SELECT 'Course 1' WHERE EXISTS (SELECT 1 FROM subjects)")
    op.execute("UPDATE subjects SET course_id = (SELECT id FROM courses LIMIT 1)")
    op.alter_column("subjects", "course_id", nullable=False)
    op.create_index(op.f("ix_subjects_course_id"), "subjects", ["course_id"])
    op.create_foreign_key(
        op.f("fk_subjects_course_id_courses"), "subjects", "courses", ["course_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_subjects_course_id_courses"), "subjects", type_="foreignkey")
    op.drop_index(op.f("ix_subjects_course_id"), table_name="subjects")
    op.drop_column("subjects", "course_id")
    op.drop_table("courses")
