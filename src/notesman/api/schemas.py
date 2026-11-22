import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PaperMetaOut(BaseModel):
    id: uuid.UUID
    title: str
    locked: int
    total: int


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class CoursePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class CourseOut(BaseModel):
    id: uuid.UUID
    can_edit: bool = False  # the caller may rename it: a global admin, or admin of every subject in it
    name: str
    description: str | None
    subject_count: int


class SubjectOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    can_edit: bool  # the caller may administer this subject
    name: str
    description: str | None
    syllabus_files: int
    reference_files: int
    papers: list[PaperMetaOut]
    archived: bool = False
    archived_papers: list[PaperMetaOut] = []  # only sent to people who administer the subject


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class SubjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class FileOut(BaseModel):
    id: uuid.UUID
    kind: str
    filename: str
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionOut(BaseModel):
    id: uuid.UUID
    position: str
    prompt: str
    answer_md: str
    status: str
    syllabus_match: str | None
    sources: list
    # Admin-only fields (None for readers)
    previous_answer_md: str | None = None
    last_steer: dict | None = None
    cost_usd: float | None = None  # what generating this answer has cost so far
    cost_calls: int | None = None


class PaperOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    title: str
    questions: list[QuestionOut]
    cost_usd: float | None = None  # admins only


class PaperIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class QuestionIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


class QuestionPatch(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    answer_md: str | None = Field(default=None, max_length=50_000)


class MoveIn(BaseModel):
    before_id: uuid.UUID | None = None  # None = move to the end


class GenerateIn(BaseModel):
    nudges: list[str] = []
    comment: str = Field(default="", max_length=1000)
