"""Integration test for subjects, files, papers and questions.

Talks to the real database from DATABASE_URL (creates and removes its own rows) and fakes
auth and R2, so it needs no Google login and no bucket. Skipped if the DB is unreachable.
"""

import asyncio
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from notesman.api.deps import current_user, require_admin
from notesman.api.main import app
from notesman.core.config import get_settings
from notesman.db.models import Subject, User
from notesman.storage.r2 import get_storage, get_storage_optional


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, fileobj, content_type):
        self.objects[key] = fileobj.read()

    async def delete_prefix(self, prefix):
        self.objects = {k: v for k, v in self.objects.items() if not k.startswith(prefix)}


def _db(fn):
    async def run():
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            return await fn(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def admin_user():
    uid = uuid.uuid4()
    user = User(id=uid, google_sub=f"test-{uid}", email=f"test-{uid}@example.com", role="admin")

    async def create(engine):
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine, expire_on_commit=False) as s:
            s.add(user)
            await s.commit()

    try:
        _db(create)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database unreachable: {e}")
    yield user

    async def cleanup(engine):
        async with engine.begin() as c:
            await c.execute(delete(Subject).where(Subject.created_by == uid))
            await c.execute(delete(User).where(User.id == uid))

    _db(cleanup)
    app.dependency_overrides.clear()


def test_content_flow(admin_user):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_storage_optional] = lambda: storage
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[current_user] = lambda: admin_user

    with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
        # subject + files
        r = c.post("/v1/subjects", json={"name": "zz test subject", "description": "d"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]

        def upload(name, data, kind="syllabus"):
            return c.post(
                f"/v1/subjects/{sid}/files",
                data={"kind": kind},
                files={"file": (name, io.BytesIO(data), "text/plain")},
            )

        assert upload("syllabus.txt", b"unit 1").status_code == 201
        assert upload("again.txt", b"unit 1").status_code == 409  # same content
        assert upload("x.exe", b"nope").status_code == 415
        assert upload("empty.txt", b"").status_code == 422
        assert len(storage.objects) == 1
        assert c.get(f"/v1/subjects/{sid}").json()["syllabus_files"] == 1

        # paper + questions
        pid = c.post(f"/v1/subjects/{sid}/papers", json={"title": "Midterm"}).json()["id"]
        q = [c.post(f"/v1/papers/{pid}/questions", json={"prompt": f"Q{i}?"}).json()["id"] for i in range(3)]
        for qid in q[:2]:
            assert c.patch(f"/v1/questions/{qid}", json={"answer_md": f"answer {qid}"}).status_code == 200

        assert c.post(f"/v1/questions/{q[2]}/lock").status_code == 409  # no answer yet
        assert c.post(f"/v1/questions/{q[0]}/lock").status_code == 200
        assert c.patch(f"/v1/questions/{q[0]}", json={"answer_md": "x"}).status_code == 409
        assert c.delete(f"/v1/questions/{q[0]}").status_code == 409
        assert c.post(f"/v1/questions/{q[2]}/generate", json={}).status_code == 501

        # reorder: move Q2 before Q0
        assert c.post(f"/v1/questions/{q[2]}/move", json={"before_id": q[0]}).status_code == 200
        order = [x["id"] for x in c.get(f"/v1/papers/{pid}").json()["questions"]]
        assert order == [q[2], q[0], q[1]]
        assert c.post(f"/v1/questions/{q[2]}/move", json={}).status_code == 200  # to the end
        order = [x["id"] for x in c.get(f"/v1/papers/{pid}").json()["questions"]]
        assert order == [q[0], q[1], q[2]]

        # reader view: only locked, no admin-only fields, no writes
        app.dependency_overrides.pop(require_admin)
        app.dependency_overrides[current_user] = lambda: None
        paper = c.get(f"/v1/papers/{pid}").json()
        assert [x["id"] for x in paper["questions"]] == [q[0]]
        assert paper["questions"][0]["previous_answer_md"] is None
        subj = c.get(f"/v1/subjects/{sid}").json()
        assert subj["papers"][0]["total"] == 1 and subj["papers"][0]["locked"] == 1
        assert c.post(f"/v1/papers/{pid}/questions", json={"prompt": "x"}).status_code == 401
        assert c.get(f"/v1/papers/{pid}/export?include_drafts=true").status_code == 403
        md = c.get(f"/v1/papers/{pid}/export").text
        assert "Q0?" in md and "Q1?" not in md

        # back to admin: unlock keeps the old text; then clean up through the API
        app.dependency_overrides[require_admin] = lambda: admin_user
        app.dependency_overrides[current_user] = lambda: admin_user
        un = c.post(f"/v1/questions/{q[0]}/unlock").json()
        assert un["status"] == "draft" and un["previous_answer_md"] == f"answer {q[0]}"
        assert c.delete(f"/v1/subjects/{sid}").status_code == 204
        assert c.get(f"/v1/subjects/{sid}").status_code == 404
        assert storage.objects == {}
