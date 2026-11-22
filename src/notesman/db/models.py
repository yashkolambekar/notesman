import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


class UserApiKey(Base):
    """An admin's own provider keys, stored encrypted (core/crypto.py). One row per user."""

    __tablename__ = "user_api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gemini_enc: Mapped[str | None] = mapped_column(Text)
    openrouter_enc: Mapped[str | None] = mapped_column(Text)
    gemini_hint: Mapped[str | None] = mapped_column(String(8))  # last 4 chars, for display only
    openrouter_hint: Mapped[str | None] = mapped_column(String(8))
    updated_at: Mapped[datetime] = _created()


class UsageEvent(Base):
    """One paid call to a provider (chat or embedding), kept to show what the service costs."""

    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint("kind IN ('chat', 'embed')", name="kind"),)

    id: Mapped[uuid.UUID] = _id()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(8))
    purpose: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    estimated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()

    subjects: Mapped[list["Subject"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = _id()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    # Archived = hidden from readers, still there for admins, who can restore it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    course: Mapped[Course] = relationship(back_populates="subjects")
    files: Mapped[list["File"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    papers: Mapped[list["Paper"]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class SubjectAdmin(Base):
    """Grants one user admin rights on one subject (files, papers, questions)."""

    __tablename__ = "subject_admins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    granted_at: Mapped[datetime] = _created()


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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    evaluation: Mapped[dict | None] = mapped_column(JSONB)  # cheap-model scores, see answer/evaluate.py
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
    # Whose API key pays for this job (the admin who uploaded or retried the file).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    file: Mapped[File] = relationship(back_populates="jobs")
