import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.auth import UserOut, user_out
from notesman.api.deps import require_superadmin
from notesman.db.base import get_session
from notesman.db.models import User

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_superadmin)])


@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [user_out(u) for u in rows]


class RoleIn(BaseModel):
    role: Literal["user", "admin"]  # superadmin can never be assigned through the API


@router.put("/users/{user_id}/role", response_model=UserOut)
async def set_role(user_id: uuid.UUID, body: RoleIn, db: AsyncSession = Depends(get_session)):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.role == "superadmin":
        raise HTTPException(409, "The superadmin role cannot be changed here")
    target.role = body.role
    await db.commit()
    return user_out(target)
