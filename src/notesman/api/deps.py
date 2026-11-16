import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.db.base import get_session
from notesman.db.models import User


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
