import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.db.base import get_session
from notesman.db.models import SubjectAdmin, User


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User | None:
    """The signed-in user, or None for visitors. Role is read from the DB on every
    request, so a demotion takes effect immediately."""
    raw = request.session.get("uid")
    if not raw:
        return None
    try:
        uid = uuid.UUID(raw)
    except ValueError:
        request.session.clear()
        return None
    user = await db.get(User, uid)
    if user is None:
        request.session.clear()
    return user


def require_role(*roles: str):
    async def dep(user: User | None = Depends(current_user)) -> User:
        if user is None:
            raise HTTPException(401, "Sign in required")
        if user.role not in roles:
            raise HTTPException(403, "Not allowed")
        return user

    return dep


require_admin = require_role("admin", "superadmin")
require_superadmin = require_role("superadmin")


def is_global_admin(user: User | None) -> bool:
    return user is not None and user.role in ("admin", "superadmin")


async def managed_subject_ids(db: AsyncSession, user: User | None) -> set[uuid.UUID]:
    """Subjects this user was granted by the superadmin (global admins manage all of them)."""
    if user is None:
        return set()
    rows = await db.execute(select(SubjectAdmin.subject_id).where(SubjectAdmin.user_id == user.id))
    return set(rows.scalars())


async def can_manage(db: AsyncSession, user: User | None, subject_id: uuid.UUID) -> bool:
    if user is None:
        return False
    if is_global_admin(user):
        return True
    return subject_id in await managed_subject_ids(db, user)


async def require_manager(db: AsyncSession, user: User | None, subject_id: uuid.UUID) -> User:
    """401 for visitors, 403 for anyone without admin rights on this subject."""
    if user is None:
        raise HTTPException(401, "Sign in required")
    if not await can_manage(db, user, subject_id):
        raise HTTPException(403, "Not allowed")
    return user
