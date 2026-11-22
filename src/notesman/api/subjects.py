import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File as FormFile, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import can_manage, current_user, is_global_admin, managed_subject_ids, require_admin, require_manager
from notesman.api.schemas import FileOut, PaperMetaOut, SubjectIn, SubjectOut, SubjectPatch
from notesman.core.config import get_settings
from notesman.db.base import get_session
from notesman.db.models import Course, File, Job, Paper, Question, Subject, User, UserApiKey
from notesman.retrieval.qdrant import delete_points
from notesman.storage.r2 import R2Storage, get_storage, get_storage_optional

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["subjects"])

ALLOWED_EXT = {".pdf", ".epub", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"}
MAX_BYTES = 200 * 1024 * 1024


def is_admin(user: User | None) -> bool:
    """Global admin (every subject). Per-subject rights go through deps.can_manage."""
    return is_global_admin(user)


async def build_subject_outs(
    db: AsyncSession, subjects: list[Subject], user: User | None
) -> list[SubjectOut]:
    ids = [s.id for s in subjects]
    managed = set(ids) if is_admin(user) else await managed_subject_ids(db, user)
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
        select(Paper.id, Paper.subject_id, Paper.title, func.count(Question.id), locked, Paper.archived_at)
        .outerjoin(Question, Question.paper_id == Paper.id)
        .where(Paper.subject_id.in_(ids))
        .group_by(Paper.id)
        .order_by(Paper.created_at)
    )
    papers: dict[uuid.UUID, list[PaperMetaOut]] = {i: [] for i in ids}
    archived_papers: dict[uuid.UUID, list[PaperMetaOut]] = {i: [] for i in ids}
    for pid, sid, title, total, n_locked, archived_at in paper_rows:
        edit = sid in managed
        if not edit and (n_locked == 0 or archived_at):
            continue  # readers only see unarchived papers that have something finalised
        meta = PaperMetaOut(id=pid, title=title, locked=n_locked, total=total if edit else n_locked)
        (archived_papers if archived_at else papers)[sid].append(meta)
    course_names = {
        cid: name
        for cid, name in await db.execute(
            select(Course.id, Course.name).where(Course.id.in_({s.course_id for s in subjects}))
        )
    }
    return [
        SubjectOut(
            id=s.id,
            course_id=s.course_id,
            course_name=course_names[s.course_id],
            can_edit=s.id in managed,
            name=s.name,
            description=s.description,
            syllabus_files=file_counts.get((s.id, "syllabus"), 0),
            reference_files=file_counts.get((s.id, "reference"), 0),
            papers=papers[s.id],
            archived=s.archived_at is not None,
            archived_papers=archived_papers[s.id],
        )
        for s in subjects
    ]


@router.get("/subjects/{subject_id}", response_model=SubjectOut)
async def get_subject(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    subject = await db.get(Subject, subject_id)
    if subject is None or (subject.archived_at and not await can_manage(db, user, subject_id)):
        raise HTTPException(404, "Subject not found")
    return (await build_subject_outs(db, [subject], user))[0]


@router.post("/subjects/{subject_id}/archive", response_model=SubjectOut)
async def archive_subject(
    subject_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    return await _set_archived(db, user, subject_id, True)


@router.post("/subjects/{subject_id}/unarchive", response_model=SubjectOut)
async def unarchive_subject(
    subject_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    return await _set_archived(db, user, subject_id, False)


async def _set_archived(db: AsyncSession, user: User | None, subject_id: uuid.UUID, archived: bool) -> SubjectOut:
    await require_manager(db, user, subject_id)
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    subject.archived_at = datetime.now(UTC) if archived else None
    await db.commit()
    return (await build_subject_outs(db, [subject], user))[0]


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
async def patch_subject(
    subject_id: uuid.UUID,
    body: SubjectPatch,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    await require_manager(db, user, subject_id)
    subject = await db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    if body.name is not None:
        subject.name = body.name.strip()
    if "description" in body.model_fields_set:
        subject.description = (body.description or "").strip() or None
    await db.commit()
    return (await build_subject_outs(db, [subject], user))[0]


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
@router.get("/subjects/{subject_id}/files", response_model=list[FileOut])
async def list_files(
    subject_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    await require_manager(db, user, subject_id)
    rows = await db.execute(
        select(File).where(File.subject_id == subject_id).order_by(File.created_at)
    )
    return rows.scalars().all()


async def _need_own_gemini_key(db: AsyncSession, user: User) -> None:
    """Embedding is billed to whoever queues the file, so they must have their own Gemini key saved."""
    row = await db.get(UserApiKey, user.id)
    if row is None or not row.gemini_enc:
        raise HTTPException(400, "Add your own Gemini API key in Settings > API keys before uploading files.")


@router.post("/subjects/{subject_id}/files", response_model=FileOut, status_code=201)
async def upload_file(
    subject_id: uuid.UUID,
    kind: Literal["syllabus", "reference"] = Form(...),
    file: UploadFile = FormFile(...),
    db: AsyncSession = Depends(get_session),
    storage: R2Storage = Depends(get_storage),
    user: User | None = Depends(current_user),
):
    await require_manager(db, user, subject_id)
    if await db.get(Subject, subject_id) is None:
        raise HTTPException(404, "Subject not found")
    await _need_own_gemini_key(db, user)

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
    db.add(Job(file_id=file_id, stage="queued", user_id=user.id))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete_prefix(f"subjects/{subject_id}/{file_id}/")
        raise
    await db.refresh(row)
    return row


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
    storage: R2Storage | None = Depends(get_storage_optional),
    user: User | None = Depends(current_user),
):
    row = await db.get(File, file_id)
    if row is None:
        raise HTTPException(404, "File not found")
    await require_manager(db, user, row.subject_id)
    prefix = f"subjects/{row.subject_id}/{row.id}/"
    await db.delete(row)
    await db.commit()
    await _cleanup_external(request, storage, prefix, "file_id", str(file_id))


@router.post("/files/{file_id}/retry", response_model=FileOut)
async def retry_file(
    file_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    row = await db.get(File, file_id)
    if row is None:
        raise HTTPException(404, "File not found")
    await require_manager(db, user, row.subject_id)
    if row.status != "failed":
        raise HTTPException(409, "Only failed files can be retried")
    await _need_own_gemini_key(db, user)
    row.status, row.error = "queued", None
    db.add(Job(file_id=row.id, stage="queued", user_id=user.id))
    await db.commit()
    await db.refresh(row)
    return row
