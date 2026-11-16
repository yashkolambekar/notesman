from datetime import UTC, datetime
from urllib.parse import quote

from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user
from notesman.api.security import resolve_role, safe_return_path
from notesman.core.config import get_settings
from notesman.db.base import get_session
from notesman.db.models import User

router = APIRouter(prefix="/v1", tags=["auth"])

_oauth: OAuth | None = None


def google_client():
    global _oauth
    if _oauth is None:
        s = get_settings()
        if not (s.google_auth_client_id and s.google_auth_client_secret):
            raise HTTPException(503, "Google sign-in is not configured")
        _oauth = OAuth()
        _oauth.register(
            name="google",
            client_id=s.google_auth_client_id,
            client_secret=s.google_auth_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return _oauth.google


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    picture: str | None
    role: str


def user_out(u: User) -> UserOut:
    return UserOut(id=str(u.id), email=u.email, name=u.name, picture=u.picture, role=u.role)


def redirect_uri() -> str:
    # The web app proxies /api/* to this server, so Google sends the browser back via /api.
    return f"{get_settings().public_base_url.rstrip('/')}/api/v1/auth/google/callback"


def back_to(path: str, error: str | None = None) -> RedirectResponse:
    base = get_settings().public_base_url.rstrip("/")
    suffix = ""
    if error:
        suffix = ("&" if "?" in path else "?") + f"auth_error={quote(error)}"
    return RedirectResponse(f"{base}{path}{suffix}", status_code=302)


@router.get("/auth/google/login")
async def login(request: Request, return_to: str | None = None):
    client = google_client()
    request.session["return_to"] = safe_return_path(return_to)
    return await client.authorize_redirect(request, redirect_uri(), prompt="select_account")


@router.get("/auth/google/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_session)):
    client = google_client()
    path = safe_return_path(request.session.get("return_to"))
    try:
        token = await client.authorize_access_token(request)
    except OAuthError:
        return back_to(path, "sign_in_failed")

    info = token.get("userinfo") or {}
    email = info.get("email")
    if not email or info.get("email_verified") is not True:
        return back_to(path, "email_not_verified")

    s = get_settings()
    user = (await db.execute(select(User).where(User.google_sub == info["sub"]))).scalar_one_or_none()
    if user is None:
        user = User(google_sub=info["sub"], email=email)
        db.add(user)
    user.email = email
    user.name = info.get("name")
    user.picture = info.get("picture")
    user.role = resolve_role(user.role, email, s.superadmin_email)
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    request.session.clear()  # fresh session on login
    request.session["uid"] = str(user.id)
    return back_to(path)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


@router.get("/me")
async def me(user: User | None = Depends(current_user)):
    return {"user": user_out(user) if user else None}
