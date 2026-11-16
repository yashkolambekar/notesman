import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notesman.db.base import Base


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin', 'superadmin')", name="role"),
    )

    id: Mapped[uuid.UUID] = _id()
    google_sub: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    picture: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), server_default="user")
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    files: Mapped[list["File"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    papers: Mapped[list["Paper"]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("kind IN ('syllabus', 'reference')", name="kind"),
        CheckConstraint("status IN ('queued', 'processing', 'ready', 'failed')", name="status"),
        UniqueConstraint("subject_id", "sha256", name="subject_sha256"),
    )

    id: Mapped[uuid.UUID] = _id()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    r2_key: Mapped[str] = mapped_column(Text)
    text_r2_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()

    subject: Mapped[Subject] = relationship(back_populates="files")
    jobs: Mapped[list["Job"]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = _id()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    subject: Mapped[Subject] = relationship(back_populates="papers")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="Question.position"
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'locked')", name="status"),
        Index("ix_questions_paper_id_position", "paper_id", "position"),
    )

    id: Mapped[uuid.UUID] = _id()
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    # Fractional index: a string that sorts lexicographically, so a drag is a one-row write.
    position: Mapped[str] = mapped_column(String(64, collation="C"))
    prompt: Mapped[str] = mapped_column(Text)
    answer_md: Mapped[str] = mapped_column(Text, server_default="")
    previous_answer_md: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    # [{chunk_id, file_id, page, snippet}]
    sources: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    syllabus_match: Mapped[str | None] = mapped_column(Text)
    last_steer: Mapped[dict | None] = mapped_column(JSONB)  # {nudges: [...], comment: "..."}
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paper: Mapped[Paper] = relationship(back_populates="questions")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('queued', 'convert', 'chunk', 'embed', 'upsert', 'done', 'failed')",
            name="stage",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    file: Mapped[File] = relationship(back_populates="jobs")
