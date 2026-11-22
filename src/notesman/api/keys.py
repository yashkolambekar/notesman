"""An admin's own API keys. Stored encrypted, never returned, decrypted only to call the provider."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user, managed_subject_ids, is_global_admin
from notesman.core.crypto import KeyVaultError, decrypt_secret, encrypt_secret
from notesman.db.base import get_session
from notesman.db.models import User, UserApiKey

router = APIRouter(prefix="/v1/me", tags=["api-keys"])


class KeyStatus(BaseModel):
    gemini_set: bool
    gemini_hint: str | None
    openrouter_set: bool
    openrouter_hint: str | None


class KeysIn(BaseModel):
    # Omitted = keep, "" = remove, anything else = replace.
    gemini: str | None = Field(default=None, max_length=500)
    openrouter: str | None = Field(default=None, max_length=500)


class MissingKeys(Exception):
    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(f"Missing API key: {', '.join(names)}")


async def require_key_owner(db: AsyncSession, user: User | None) -> User:
    """Only admins (global, or granted on at least one subject) bring keys."""
    if user is None:
        raise HTTPException(401, "Sign in required")
    if not is_global_admin(user) and not await managed_subject_ids(db, user):
        raise HTTPException(403, "Not allowed")
    return user


def _status(row: UserApiKey | None) -> KeyStatus:
    return KeyStatus(
        gemini_set=bool(row and row.gemini_enc),
        gemini_hint=row.gemini_hint if row and row.gemini_enc else None,
        openrouter_set=bool(row and row.openrouter_enc),
        openrouter_hint=row.openrouter_hint if row and row.openrouter_enc else None,
    )


async def user_keys(db: AsyncSession, user_id: uuid.UUID | None, need: tuple[str, ...]) -> dict[str, str]:
    """Decrypt this user's keys. Raises MissingKeys if a needed one is not set. No fallback to anyone else's key."""
    row = await db.get(UserApiKey, user_id) if user_id else None
    out: dict[str, str] = {}
    missing: list[str] = []
    for name in need:
        enc = getattr(row, f"{name}_enc", None) if row else None
        if not enc:
            missing.append(name)
        else:
            out[name] = decrypt_secret(enc)
    if missing:
        raise MissingKeys(missing)
    return out


def missing_message(e: MissingKeys) -> str:
    label = {"gemini": "Gemini", "openrouter": "OpenRouter"}
    names = " and ".join(label[n] for n in e.names)
    return f"Add your own {names} API key in Settings > API keys first."


@router.get("/api-keys", response_model=KeyStatus)
async def get_keys(db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)):
    await require_key_owner(db, user)
    return _status(await db.get(UserApiKey, user.id))


@router.put("/api-keys", response_model=KeyStatus)
async def put_keys(
    body: KeysIn, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    await require_key_owner(db, user)
    row = await db.get(UserApiKey, user.id)
    if row is None:
        row = UserApiKey(user_id=user.id)
        db.add(row)
    try:
        for name in ("gemini", "openrouter"):
            value = getattr(body, name)
            if value is None:
                continue
            value = value.strip()
            if not value:
                setattr(row, f"{name}_enc", None)
                setattr(row, f"{name}_hint", None)
            else:
                setattr(row, f"{name}_enc", encrypt_secret(value))
                setattr(row, f"{name}_hint", value[-4:])
    except KeyVaultError as e:
        await db.rollback()
        raise HTTPException(503, str(e)) from e
    await db.commit()
    return _status(row)
