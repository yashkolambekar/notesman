import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user, is_global_admin, managed_subject_ids, require_admin
from notesman.api.schemas import CourseIn, CourseOut, CoursePatch, SubjectIn, SubjectOut
from notesman.api.subjects import _cleanup_external, build_subject_outs
from notesman.db.base import get_session
from notesman.db.models import Course, Subject, User
from notesman.storage.r2 import R2Storage, get_storage_optional

router = APIRouter(prefix="/v1", tags=["courses"])


async def _course(db: AsyncSession, course_id: uuid.UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Course not found")
    return course


async def _out(db: AsyncSession, courses: list[Course], user: User | None = None) -> list[CourseOut]:
    counts = dict(
        (await db.execute(
            select(Subject.course_id, func.count())
            .where(Subject.course_id.in_([c.id for c in courses]), Subject.archived_at.is_(None))
            .group_by(Subject.course_id)
        )).all()
    )
    managed = await managed_subject_ids(db, user)
    in_course: dict[uuid.UUID, set[uuid.UUID]] = {}
    if managed and not is_global_admin(user):
        for cid, sid in await db.execute(select(Subject.course_id, Subject.id).where(Subject.course_id.in_([c.id for c in courses]))):
            in_course.setdefault(cid, set()).add(sid)

    def can_edit(c: Course) -> bool:
        if is_global_admin(user):
            return True
        subs = in_course.get(c.id)
        return bool(subs) and subs <= managed  # admin of the whole course

    return [
        CourseOut(
            id=c.id, name=c.name, description=c.description,
            subject_count=counts.get(c.id, 0), can_edit=can_edit(c),
        )
        for c in courses
    ]


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)):
    rows = (await db.execute(select(Course).order_by(Course.name))).scalars().all()
    return await _out(db, list(rows), user)


@router.get("/courses/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    return (await _out(db, [await _course(db, course_id)], user))[0]


@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(
    body: CourseIn, db: AsyncSession = Depends(get_session), user: User = Depends(require_admin)
):
    course = Course(name=body.name.strip(), description=(body.description or "").strip() or None, created_by=user.id)
    db.add(course)
    await db.commit()
    return (await _out(db, [course], user))[0]


@router.patch("/courses/{course_id}", response_model=CourseOut)
async def patch_course(
    course_id: uuid.UUID,
    body: CoursePatch,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    if user is None:
        raise HTTPException(401, "Sign in required")
    course = await _course(db, course_id)
    if not (await _out(db, [course], user))[0].can_edit:
        raise HTTPException(403, "Not allowed")
    if body.name is not None:
        course.name = body.name.strip()
    if "description" in body.model_fields_set:
        course.description = (body.description or "").strip() or None
    await db.commit()
    return (await _out(db, [course], user))[0]


@router.delete("/courses/{course_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_course(
    course_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
    storage: R2Storage | None = Depends(get_storage_optional),
):
    course = await _course(db, course_id)
    subject_ids = list((await db.execute(select(Subject.id).where(Subject.course_id == course_id))).scalars())
    await db.delete(course)  # cascades to subjects, files, papers, questions
    await db.commit()
    for sid in subject_ids:
        await _cleanup_external(request, storage, f"subjects/{sid}/", "subject_id", str(sid))


# ---- subjects inside a course -------------------------------------------------------
@router.get("/courses/{course_id}/subjects", response_model=list[SubjectOut])
async def list_subjects(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    await _course(db, course_id)
    rows = (
        await db.execute(select(Subject).where(Subject.course_id == course_id).order_by(Subject.name))
    ).scalars().all()
    if not rows:
        return []
    outs = await build_subject_outs(db, list(rows), user)
    return [o for o in outs if o.can_edit or not o.archived]  # readers never see archived subjects


@router.post("/courses/{course_id}/subjects", response_model=SubjectOut, status_code=201)
async def create_subject(
    course_id: uuid.UUID,
    body: SubjectIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    await _course(db, course_id)
    subject = Subject(
        course_id=course_id,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        created_by=user.id,
    )
    db.add(subject)
    await db.commit()
    return (await build_subject_outs(db, [subject], user))[0]
