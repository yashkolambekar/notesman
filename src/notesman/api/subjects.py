import hashlib
import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File as FormFile, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user, require_admin
from notesman.api.schemas import FileOut, PaperMetaOut, SubjectIn, SubjectOut, SubjectPatch
from notesman.core.config import get_settings
from notesman.db.base import get_session
from notesman.db.models import File, Job, Paper, Question, Subject, User
from notesman.retrieval.qdrant import delete_points
from notesman.storage.r2 import R2Storage, get_storage, get_storage_optional

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["subjects"])

ALLOWED_EXT = {".pdf", ".epub", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"}
MAX_BYTES = 200 * 1024 * 1024


def is_admin(user: User | None) -> bool:
    return user is not None and user.role in ("admin", "superadmin")


async def build_subject_outs(
    db: AsyncSession, subjects: list[Subject], admin: bool
) -> list[SubjectOut]:
    ids = [s.id for s in subjects]
    file_counts = {
        (sid, kind): n
        for sid, kind, n in await db.execute(
            select(File.subject_id, File.kind, func.count())
            .where(File.subject_id.in_(ids))
            .group_by(File.subject_id, File.kind)
        )
    }
    locked = func.count(Question.id).filter(Question.status == "locked")
    paper_rows = await db.execute(
        select(Paper.id, Paper.subject_id, Paper.title, func.count(Question.id), locked)
        .outerjoin(Question, Question.paper_id == Paper.id)
        .where(Paper.subject_id.in_(ids))
        .group_by(Paper.id)
        .order_by(Paper.created_at)
    )
    papers: dict[uuid.UUID, list[PaperMetaOut]] = {i: [] for i in ids}
    for pid, sid, title, total, n_locked in paper_rows:
        if not admin and n_locked == 0:
            continue  # readers only see papers that have something finalised
        papers[sid].append(
            PaperMetaOut(id=pid, title=title, locked=n_locked, total=total if admin else n_locked)
        )
    return [
        SubjectOut(
            id=s.id,
            name=s.name,
            description=s.description,
            syllabus_files=file_counts.get((s.id, "syllabus"), 0),
            reference_files=file_counts.get((s.id, "reference"), 0),
            papers=papers[s.id],
        )
        for s in subjects
    ]


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(
    db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    rows = (await db.execute(select(Subject).order_by(Subject.name))).scalars().all()
    return await build_subject_outs(db, list(rows), is_admin(user))


@router.get("/subjects/{subject_id}", response_model=SubjectOut)
async def get_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    return (await build_subject_outs(db, [subject], is_admin(user)))[0]


@router.post("/subjects", response_model=SubjectOut, status_code=201)
async def create_subject(
    body: SubjectIn, db: AsyncSession = Depends(get_session), user: User = Depends(require_admin)
):
    subject = Subject(name=body.name.strip(), description=(body.description or "").strip() or None, created_by=user.id)
    db.add(subject)
    await db.commit()
    return (await build_subject_outs(db, [subject], True))[0]


@router.patch("/subjects/{subject_id}", response_model=SubjectOut, dependencies=[Depends(require_admin)])
async def patch_subject(
    subject_id: uuid.UUID, body: SubjectPatch, db: AsyncSession = Depends(get_session)
):
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    if body.name is not None:
        subject.name = body.name.strip()
    if "description" in body.model_fields_set:
        subject.description = (body.description or "").strip() or None
    await db.commit()
    return (await build_subject_outs(db, [subject], True))[0]


@router.delete("/subjects/{subject_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_subject(
    subject_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
    storage: R2Storage | None = Depends(get_storage_optional),
):
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    await db.delete(subject)
    await db.commit()
    await _cleanup_external(request, storage, f"subjects/{subject_id}/", "subject_id", str(subject_id))


async def _cleanup_external(
    request: Request, storage: R2Storage | None, prefix: str, field: str, value: str
) -> None:
    """Best effort: the DB row is already gone, so leftovers are harmless orphans."""
    s = get_settings()
    try:
        await delete_points(request.app.state.qdrant, s, field, value)
    except Exception:
        log.exception("Qdrant cleanup failed for %s=%s", field, value)
    try:
        if storage is not None:
            await storage.delete_prefix(prefix)
    except Exception:
        log.exception("R2 cleanup failed for %s", prefix)


# ---- files ---------------------------------------------------------------------------
@router.get("/subjects/{subject_id}/files", response_model=list[FileOut], dependencies=[Depends(require_admin)])
async def list_files(subject_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    rows = await db.execute(
        select(File).where(File.subject_id == subject_id).order_by(File.created_at)
    )
    return rows.scalars().all()


@router.post("/subjects/{subject_id}/files", response_model=FileOut, status_code=201, dependencies=[Depends(require_admin)])
async def upload_file(
    subject_id: uuid.UUID,
    kind: Literal["syllabus", "reference"] = Form(...),
    file: UploadFile = FormFile(...),
    db: AsyncSession = Depends(get_session),
    storage: R2Storage = Depends(get_storage),
):
    if await db.get(Subject, subject_id) is None:
        raise HTTPException(404, "Subject not found")

    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type. Allowed: {' '.join(sorted(ALLOWED_EXT))}")

    digest, size = hashlib.sha256(), 0
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, "File is larger than 200 MB")
        digest.update(chunk)
    if size == 0:
        raise HTTPException(422, "File is empty")
    sha = digest.hexdigest()

    dup = (
        await db.execute(select(File.filename).where(File.subject_id == subject_id, File.sha256 == sha))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"Already uploaded as {dup}")

    file_id = uuid.uuid4()
    key = f"subjects/{subject_id}/{file_id}/original{ext}"
    await file.seek(0)
    await storage.put(key, file.file, file.content_type)

    row = File(
        id=file_id, subject_id=subject_id, kind=kind, filename=name, mime=file.content_type,
        size_bytes=size, sha256=sha, r2_key=key, status="queued",
    )
    db.add(row)
    db.add(Job(file_id=file_id, stage="queued"))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete_prefix(f"subjects/{subject_id}/{file_id}/")
        raise
    await db.refresh(row)
    return row


@router.delete("/files/{file_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
    storage: R2Storage | None = Depends(get_storage_optional),
):
    row = await db.get(File, file_id)
    if row is None:
        raise HTTPException(404, "File not found")
    prefix = f"subjects/{row.subject_id}/{row.id}/"
    await db.delete(row)
    await db.commit()
    await _cleanup_external(request, storage, prefix, "file_id", str(file_id))


@router.post("/files/{file_id}/retry", response_model=FileOut, dependencies=[Depends(require_admin)])
async def retry_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    row = await db.get(File, file_id)
    if row is None:
        raise HTTPException(404, "File not found")
    if row.status != "failed":
        raise HTTPException(409, "Only failed files can be retried")
    row.status, row.error = "queued", None
    db.add(Job(file_id=row.id, stage="queued"))
    await db.commit()
    await db.refresh(row)
    return row
