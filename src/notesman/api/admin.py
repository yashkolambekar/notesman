import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.auth import UserOut, user_out
from notesman.api.deps import require_superadmin
from notesman.db.base import get_session
from notesman.db.models import Course, Subject, SubjectAdmin, User

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_superadmin)])


class AdminUserOut(UserOut):
    subject_ids: list[str]  # subjects this user was granted admin rights on


class SubjectChoice(BaseModel):
    id: str
    course_id: str
    name: str
    course_name: str


async def _grants(db: AsyncSession) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {}
    for uid, sid in await db.execute(select(SubjectAdmin.user_id, SubjectAdmin.subject_id)):
        out.setdefault(uid, []).append(str(sid))
    return out


def _admin_out(u: User, grants: dict[uuid.UUID, list[str]]) -> AdminUserOut:
    return AdminUserOut(**user_out(u).model_dump(), subject_ids=grants.get(u.id, []))


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    grants = await _grants(db)
    return [_admin_out(u, grants) for u in rows]


@router.get("/subjects", response_model=list[SubjectChoice])
async def list_subject_choices(db: AsyncSession = Depends(get_session)):
    rows = await db.execute(
        select(Subject.id, Subject.name, Course.name, Course.id).join(Course).order_by(Course.name, Subject.name)
    )
    return [SubjectChoice(id=str(i), name=n, course_name=c, course_id=str(ci)) for i, n, c, ci in rows]


class RoleIn(BaseModel):
    role: Literal["user", "admin"]  # superadmin can never be assigned through the API


@router.put("/users/{user_id}/role", response_model=AdminUserOut)
async def set_role(user_id: uuid.UUID, body: RoleIn, db: AsyncSession = Depends(get_session)):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.role == "superadmin":
        raise HTTPException(409, "The superadmin role cannot be changed here")
    target.role = body.role
    await db.commit()
    return _admin_out(target, await _grants(db))


class SubjectsIn(BaseModel):
    subject_ids: list[uuid.UUID]


@router.put("/users/{user_id}/subjects", response_model=AdminUserOut)
async def set_subjects(user_id: uuid.UUID, body: SubjectsIn, db: AsyncSession = Depends(get_session)):
    """Replace the set of subjects this user can administer."""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    wanted = set(body.subject_ids)
    if wanted:
        found = set((await db.execute(select(Subject.id).where(Subject.id.in_(wanted)))).scalars())
        if found != wanted:
            raise HTTPException(422, "Unknown subject")
    await db.execute(delete(SubjectAdmin).where(SubjectAdmin.user_id == user_id))
    db.add_all(SubjectAdmin(user_id=user_id, subject_id=sid) for sid in wanted)
    await db.commit()
    return _admin_out(target, await _grants(db))
