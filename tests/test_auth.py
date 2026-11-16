import os

os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:3000")

import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from notesman.api.deps import current_user, require_admin, require_superadmin
from notesman.api.origin import OriginCheck
from notesman.api.security import resolve_role, safe_return_path
from notesman.db.models import User


# ---- pure helpers ----------------------------------------------------------------
@pytest.mark.parametrize(
    "existing,email,env,expected",
    [
        (None, "a@x.com", "", "user"),
        ("user", "a@x.com", "boss@x.com", "user"),
        ("admin", "a@x.com", "boss@x.com", "admin"),
        (None, "Boss@X.com", "boss@x.com", "superadmin"),
        ("user", "boss@x.com", "boss@x.com", "superadmin"),
        ("superadmin", "other@x.com", "boss@x.com", "admin"),  # env changed: lose superadmin
        ("superadmin", "other@x.com", "", "admin"),
    ],
)
def test_resolve_role(existing, email, env, expected):
    assert resolve_role(existing, email, env) == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/subjects/os", "/subjects/os"),
        ("/a?b=1", "/a?b=1"),
        (None, "/"),
        ("", "/"),
        ("https://evil.com", "/"),
        ("//evil.com", "/"),
        ("/\\evil.com", "/"),
        ("/ok\r\nSet-Cookie: x=1", "/"),
        ("evil.com", "/"),
    ],
)
def test_safe_return_path(path, expected):
    assert safe_return_path(path) == expected


# ---- guards ------------------------------------------------------------------------
def make_app(user: User | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginCheck, allowed_origin="http://localhost:3000", cookie_name="notesman_session")
    app.add_middleware(SessionMiddleware, secret_key="t", session_cookie="notesman_session")
    app.dependency_overrides[current_user] = lambda: user

    @app.get("/admin-only", dependencies=[Depends(require_admin)])
    def a():
        return "ok"

    @app.get("/super-only", dependencies=[Depends(require_superadmin)])
    def b():
        return "ok"

    @app.post("/write")
    def w():
        return "ok"

    return app


def u(role):
    return User(id=uuid.uuid4(), google_sub="s", email="e@x.com", role=role)


@pytest.mark.parametrize(
    "role,admin_status,super_status",
    [
        (None, 401, 401),
        ("user", 403, 403),
        ("admin", 200, 403),
        ("superadmin", 200, 200),
    ],
)
def test_role_guards(role, admin_status, super_status):
    c = TestClient(make_app(u(role) if role else None))
    assert c.get("/admin-only").status_code == admin_status
    assert c.get("/super-only").status_code == super_status


def test_origin_check():
    c = TestClient(make_app(None))
    assert c.post("/write").status_code == 200  # no cookie, no origin: curl-style
    assert c.post("/write", headers={"origin": "http://localhost:3000"}).status_code == 200
    assert c.post("/write", headers={"origin": "https://evil.com"}).status_code == 403
    c.cookies.set("notesman_session", "x")
    assert c.post("/write").status_code == 403  # cookie but no origin
    assert c.get("/admin-only").status_code == 401  # GETs are never blocked by origin
