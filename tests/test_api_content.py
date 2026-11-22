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
from notesman.db.models import Course, User
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
            await c.execute(delete(Course).where(Course.created_by == uid))
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
        # uploads are embedded with the uploader's own Gemini key, so it must be saved first
        r = c.put("/v1/me/api-keys", json={"gemini": "gem-test-key-1234"})
        assert r.status_code == 200 and r.json()["gemini_set"] and not r.json()["openrouter_set"]
        # subject + files
        r = c.post("/v1/courses", json={"name": "zz test course"})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert c.post(f"/v1/courses/{uuid.uuid4()}/subjects", json={"name": "x"}).status_code == 404
        r = c.post(f"/v1/courses/{cid}/subjects", json={"name": "zz test subject", "description": "d"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert r.json()["course_id"] == cid and r.json()["course_name"] == "zz test course"
        assert [x["id"] for x in c.get(f"/v1/courses/{cid}/subjects").json()] == [sid]
        assert c.get(f"/v1/courses/{cid}").json()["subject_count"] == 1

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
        # generating needs the admin's own OpenRouter key too (only Gemini is saved): refused, no fallback
        r = c.post(f"/v1/questions/{q[2]}/generate", json={})
        assert r.status_code == 400 and "OpenRouter" in r.json()["detail"], r.text

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
        assert c.delete(f"/v1/courses/{cid}").status_code == 204  # cascades to subject, files, papers
        assert c.get(f"/v1/courses/{cid}").status_code == 404
        assert c.get(f"/v1/subjects/{sid}").status_code == 404
        assert storage.objects == {}


def test_subject_grants(admin_user):
    """A plain user can administer exactly the subjects granted to them, and nothing else."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from notesman.db.models import SubjectAdmin

    scoped = User(id=uuid.uuid4(), google_sub=f"test-{uuid.uuid4()}", email=f"s-{uuid.uuid4()}@example.com", role="user")

    async def make_user(engine):
        async with AsyncSession(engine, expire_on_commit=False) as s:
            s.add(scoped)
            await s.commit()

    async def grant(engine, sid):
        async with AsyncSession(engine) as s:
            s.add(SubjectAdmin(user_id=scoped.id, subject_id=sid))
            await s.commit()

    async def drop_user(engine):
        async with engine.begin() as c:
            await c.execute(delete(User).where(User.id == scoped.id))

    _db(make_user)
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_storage_optional] = lambda: storage
    try:
        with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
            app.dependency_overrides[require_admin] = lambda: admin_user
            app.dependency_overrides[current_user] = lambda: admin_user
            cid = c.post("/v1/courses", json={"name": "zz grants course"}).json()["id"]
            mine = c.post(f"/v1/courses/{cid}/subjects", json={"name": "mine"}).json()["id"]
            other = c.post(f"/v1/courses/{cid}/subjects", json={"name": "other"}).json()["id"]
            paper_other = c.post(f"/v1/subjects/{other}/papers", json={"title": "P"}).json()["id"]
            q_other = c.post(f"/v1/papers/{paper_other}/questions", json={"prompt": "Q?"}).json()["id"]
            app.dependency_overrides.pop(require_admin)

            app.dependency_overrides[current_user] = lambda: scoped
            # no grant yet: read-only everywhere
            assert c.post(f"/v1/subjects/{mine}/papers", json={"title": "x"}).status_code == 403
            assert all(not s["can_edit"] for s in c.get(f"/v1/courses/{cid}/subjects").json())

            _db(lambda e: grant(e, uuid.UUID(mine)))
            subs = {s["id"]: s for s in c.get(f"/v1/courses/{cid}/subjects").json()}
            assert subs[mine]["can_edit"] and not subs[other]["can_edit"]

            pid = c.post(f"/v1/subjects/{mine}/papers", json={"title": "Mine"}).json()["id"]
            qid = c.post(f"/v1/papers/{pid}/questions", json={"prompt": "Q?"}).json()["id"]
            assert c.patch(f"/v1/questions/{qid}", json={"answer_md": "a"}).status_code == 200
            assert c.post(f"/v1/questions/{qid}/lock").status_code == 200
            assert c.get(f"/v1/subjects/{mine}/files").status_code == 200

            # other subject, and global-only actions, stay closed
            assert c.post(f"/v1/subjects/{other}/papers", json={"title": "x"}).status_code == 403
            assert c.get(f"/v1/subjects/{other}/files").status_code == 403
            assert c.patch(f"/v1/questions/{q_other}", json={"answer_md": "x"}).status_code == 403
            assert c.post(f"/v1/questions/{q_other}/generate", json={}).status_code == 403
            assert c.get(f"/v1/papers/{paper_other}/export?include_drafts=true").status_code == 403
            assert c.get(f"/v1/papers/{paper_other}").json()["questions"] == []  # drafts hidden
            assert c.post(f"/v1/courses/{cid}/subjects", json={"name": "n"}).status_code in (401, 403)
            assert c.delete(f"/v1/subjects/{mine}").status_code in (401, 403)
            assert c.delete(f"/v1/courses/{cid}").status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
        _db(drop_user)


def test_api_keys_are_encrypted_and_private(admin_user):
    from sqlalchemy import select

    from notesman.core.crypto import decrypt_secret
    from notesman.db.models import UserApiKey

    app.dependency_overrides[current_user] = lambda: admin_user
    secret = "sk-or-very-secret-5678"
    with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
        assert c.get("/v1/me/api-keys").json() == {
            "gemini_set": False, "gemini_hint": None, "openrouter_set": False, "openrouter_hint": None,
        }
        r = c.put("/v1/me/api-keys", json={"openrouter": secret})
        assert r.status_code == 200, r.text
        assert r.json()["openrouter_hint"] == "5678"
        assert secret not in r.text and secret not in c.get("/v1/me/api-keys").text

        async def stored(engine):
            from sqlalchemy.ext.asyncio import AsyncSession

            async with AsyncSession(engine) as s:
                return (await s.execute(select(UserApiKey).where(UserApiKey.user_id == admin_user.id))).scalar_one()

        row = _db(stored)
        assert secret not in (row.openrouter_enc or "")
        assert decrypt_secret(row.openrouter_enc) == secret

        # omitted field keeps the other key; empty string removes
        assert c.put("/v1/me/api-keys", json={"gemini": "g-1111"}).json()["openrouter_set"] is True
        r = c.put("/v1/me/api-keys", json={"openrouter": ""})
        assert r.json()["openrouter_set"] is False and r.json()["gemini_set"] is True

        # a plain user cannot bring keys
        app.dependency_overrides[current_user] = lambda: User(id=uuid.uuid4(), role="user", email="u@example.com", google_sub="x")
        assert c.put("/v1/me/api-keys", json={"gemini": "x"}).status_code == 403
        app.dependency_overrides[current_user] = lambda: None
        assert c.get("/v1/me/api-keys").status_code == 401
    app.dependency_overrides.clear()


def test_rename_permissions(admin_user):
    """Global admin renames anything. A subject admin renames their subject and its papers, and the
    course only when they administer every subject in it."""
    from notesman.db.models import Subject, SubjectAdmin

    helper = User(id=uuid.uuid4(), google_sub=f"t-{uuid.uuid4()}", email=f"h-{uuid.uuid4()}@example.com", role="user")
    ids: dict = {}

    async def setup(engine):
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine, expire_on_commit=False) as s:
            s.add(helper)
            c = Course(name="zz rename course", created_by=admin_user.id)
            s.add(c)
            await s.flush()
            a, b = Subject(course_id=c.id, name="A"), Subject(course_id=c.id, name="B")
            s.add_all([a, b])
            await s.flush()
            ids.update(course=c.id, a=a.id, b=b.id)
            s.add(SubjectAdmin(user_id=helper.id, subject_id=a.id))
            await s.commit()

    async def grant_b(engine):
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as s:
            s.add(SubjectAdmin(user_id=helper.id, subject_id=ids["b"]))
            await s.commit()

    async def cleanup(engine):
        async with engine.begin() as c:
            await c.execute(delete(Course).where(Course.id == ids["course"]))
            await c.execute(delete(User).where(User.id == helper.id))

    _db(setup)
    try:
        with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
            app.dependency_overrides[current_user] = lambda: helper
            cid = str(ids["course"])
            assert c.get(f"/v1/courses/{cid}").json()["can_edit"] is False
            assert c.patch(f"/v1/subjects/{ids['a']}", json={"name": "A2"}).json()["name"] == "A2"
            assert c.patch(f"/v1/subjects/{ids['b']}", json={"name": "x"}).status_code == 403
            assert c.patch(f"/v1/courses/{cid}", json={"name": "x"}).status_code == 403
            pid = None
            app.dependency_overrides[current_user] = lambda: admin_user
            pid = c.post(f"/v1/subjects/{ids['a']}/papers", json={"title": "P"}).json()["id"]
            app.dependency_overrides[current_user] = lambda: helper
            assert c.patch(f"/v1/papers/{pid}", json={"title": "P2"}).json()["title"] == "P2"

            _db(grant_b)  # now admin of the whole course
            assert c.get(f"/v1/courses/{cid}").json()["can_edit"] is True
            assert c.patch(f"/v1/courses/{cid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
            app.dependency_overrides[current_user] = lambda: None
            assert c.patch(f"/v1/courses/{cid}", json={"name": "x"}).status_code == 401
    finally:
        app.dependency_overrides.clear()
        _db(cleanup)


def test_archive(admin_user):
    """Archived subjects and papers vanish for readers and stay visible (and restorable) for admins."""
    with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
        app.dependency_overrides[current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
        try:
            cid = c.post("/v1/courses", json={"name": "zz archive course"}).json()["id"]
            sid = c.post(f"/v1/courses/{cid}/subjects", json={"name": "S"}).json()["id"]
            pid = c.post(f"/v1/subjects/{sid}/papers", json={"title": "P"}).json()["id"]
            qid = c.post(f"/v1/papers/{pid}/questions", json={"prompt": "Q?"}).json()["id"]
            c.patch(f"/v1/questions/{qid}", json={"answer_md": "a"})
            assert c.post(f"/v1/questions/{qid}/lock").status_code == 200

            def as_reader():
                app.dependency_overrides[current_user] = lambda: None

            def as_admin():
                app.dependency_overrides[current_user] = lambda: admin_user

            # paper archive
            assert c.post(f"/v1/papers/{pid}/archive").status_code == 200
            s = c.get(f"/v1/subjects/{sid}").json()
            assert s["papers"] == [] and [p["id"] for p in s["archived_papers"]] == [pid]
            as_reader()
            s = c.get(f"/v1/subjects/{sid}").json()
            assert s["papers"] == [] and s["archived_papers"] == []
            assert c.get(f"/v1/papers/{pid}").status_code == 404
            assert c.get(f"/v1/papers/{pid}/export").status_code == 404
            assert c.post(f"/v1/papers/{pid}/archive").status_code == 401
            as_admin()
            assert c.post(f"/v1/papers/{pid}/unarchive").status_code == 200
            as_reader()
            assert [p["id"] for p in c.get(f"/v1/subjects/{sid}").json()["papers"]] == [pid]
            assert c.get(f"/v1/papers/{pid}").status_code == 200

            # subject archive
            as_admin()
            r = c.post(f"/v1/subjects/{sid}/archive")
            assert r.status_code == 200 and r.json()["archived"] is True
            assert c.get(f"/v1/courses/{cid}").json()["subject_count"] == 0
            assert [x["id"] for x in c.get(f"/v1/courses/{cid}/subjects").json()] == [sid]  # admin still lists it
            as_reader()
            assert c.get(f"/v1/courses/{cid}/subjects").json() == []
            assert c.get(f"/v1/subjects/{sid}").status_code == 404
            assert c.get(f"/v1/papers/{pid}").status_code == 404
            as_admin()
            assert c.post(f"/v1/subjects/{sid}/unarchive").json()["archived"] is False
            as_reader()
            assert c.get(f"/v1/subjects/{sid}").status_code == 200
        finally:
            as_admin()
            c.delete(f"/v1/courses/{cid}")
            app.dependency_overrides.clear()
