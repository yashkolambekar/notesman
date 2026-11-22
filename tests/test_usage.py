"""Spend tracking: provider cost parsing, recording (even on failure), and who may see what."""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api import papers
from notesman.api.deps import current_user, require_admin
from notesman.api.main import app
from notesman.core.config import Settings
from notesman.core.usage import Call, UsageCollector, estimate_tokens
from notesman.db.models import Course, UsageEvent, User
from notesman.llm.openrouter import ChatError, OpenRouterChat
from test_api_content import _db, admin_user  # noqa: F401  (fixture)


def _chat(usage):
    return OpenRouterChat(Settings(openrouter_api_key="k"), usage=usage)


def test_openrouter_reported_cost_is_used_and_marked_exact():
    u = UsageCollector()
    _chat(u)._record({"usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0123}}, "m", "answer")
    (c,) = u.calls
    assert (c.kind, c.purpose, c.input_tokens, c.output_tokens, c.cost_usd, c.estimated) == ("chat", "answer", 100, 50, 0.0123, False)


def test_missing_cost_falls_back_to_token_prices_and_is_estimated():
    u = UsageCollector()
    chat = OpenRouterChat(
        Settings(openrouter_api_key="k", chat_price_in_per_mtok_usd=2.0, chat_price_out_per_mtok_usd=10.0), usage=u
    )
    chat._record({"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}}, "m", "rerank")
    assert u.calls[0].cost_usd == pytest.approx(7.0) and u.calls[0].estimated
    u2 = UsageCollector()
    _chat(u2)._record({"choices": []}, "m", "answer")  # no usage block at all: nothing recorded, no crash
    assert u2.calls == []


def test_token_estimate():
    assert estimate_tokens(["a" * 400, "b" * 400]) == 200


@pytest.fixture
def cleanup_events(admin_user):  # noqa: F811
    yield
    async def go(engine):
        async with engine.begin() as c:
            await c.execute(delete(UsageEvent).where(UsageEvent.user_id == admin_user.id))
    _db(go)


def test_generate_records_spend_even_when_it_fails_and_costs_are_admin_only(admin_user, cleanup_events, monkeypatch):  # noqa: F811
    class FakeEmb:
        def __init__(self, s, api_key=None, usage=None):
            self.usage = usage

        async def aclose(self): ...

    class FakeChat(FakeEmb):
        model = "fake/model"

    async def failing_generation(*, emb, chat, **kw):
        chat.usage.add(Call("chat", "rewrite", "fake/model", 10, 5, 0.002))
        emb.usage.add(Call("embed", "embed_query", "emb", 8, 0, 0.0001, True))
        raise ChatError("boom")

    monkeypatch.setattr(papers, "GeminiEmbedder", FakeEmb)
    monkeypatch.setattr(papers, "OpenRouterChat", FakeChat)
    monkeypatch.setattr(papers, "run_generation", failing_generation)

    app.dependency_overrides[current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    cid = None
    try:
        with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
            app.state.qdrant_error = None
            c.put("/v1/me/api-keys", json={"gemini": "g-1234", "openrouter": "o-5678"})
            cid = c.post("/v1/courses", json={"name": "zz usage course"}).json()["id"]
            sid = c.post(f"/v1/courses/{cid}/subjects", json={"name": "S"}).json()["id"]
            pid = c.post(f"/v1/subjects/{sid}/papers", json={"title": "P"}).json()["id"]
            qid = c.post(f"/v1/papers/{pid}/questions", json={"prompt": "Q?"}).json()["id"]

            assert c.post(f"/v1/questions/{qid}/generate", json={}).status_code == 502

            async def rows(engine):
                async with AsyncSession(engine) as s:
                    return (await s.execute(select(UsageEvent).where(UsageEvent.user_id == admin_user.id))).scalars().all()

            ev = _db(rows)
            assert {e.purpose for e in ev} == {"rewrite", "embed_query"}
            assert all(str(e.question_id) == qid and str(e.subject_id) == sid for e in ev)
            assert sum(e.cost_usd for e in ev) == Decimal("0.002100")

            # admin sees cost on the question and paper; readers see none of it
            paper = c.get(f"/v1/papers/{pid}").json()
            assert paper["cost_usd"] == pytest.approx(0.0021)
            assert paper["questions"][0]["cost_usd"] == pytest.approx(0.0021) and paper["questions"][0]["cost_calls"] == 2
            usage = c.get("/v1/me/usage").json()
            assert usage["scope"] == "own" and usage["total_usd"] == pytest.approx(0.0021)
            assert usage["estimated_usd"] == pytest.approx(0.0001)
            assert {b["label"] for b in usage["by_purpose"]} == {"rewrite", "embed_query"}

            app.dependency_overrides[current_user] = lambda: None
            assert c.get("/v1/me/usage").status_code == 401
            # a reader can only see locked questions, so lock one as admin first
            app.dependency_overrides[current_user] = lambda: admin_user
            c.patch(f"/v1/questions/{qid}", json={"answer_md": "a"})
            c.post(f"/v1/questions/{qid}/lock")
            app.dependency_overrides[current_user] = lambda: None
            r = c.get(f"/v1/papers/{pid}").json()
            assert r["cost_usd"] is None and r["questions"][0]["cost_usd"] is None

            # plain user: no detail
            app.dependency_overrides[current_user] = lambda: User(id=uuid.uuid4(), role="user", email="u@e.com", google_sub="u")
            assert c.get("/v1/me/usage").status_code == 403

            # per-course spend is public: total plus display names, no emails
            app.dependency_overrides[current_user] = lambda: None
            r = c.get(f"/v1/courses/{cid}/spend")
            assert r.status_code == 200
            body = r.json()
            assert body["total_usd"] == pytest.approx(0.0021)
            assert len(body["by_admin"]) == 1 and "@" not in body["by_admin"][0]["name"]
            assert body["by_admin"][0]["cost_usd"] == pytest.approx(0.0021)
            assert (body["papers"], body["questions"]) == (1, 1)
            assert (body["embed_calls"], body["chat_calls"]) == (1, 1)
            assert (body["input_tokens"], body["output_tokens"]) == (18, 5)
            assert c.get(f"/v1/courses/{uuid.uuid4()}/spend").status_code == 404
    finally:
        app.dependency_overrides[current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
        if cid:
            with TestClient(app, headers={"origin": "http://localhost:3000"}) as c:
                c.delete(f"/v1/courses/{cid}")
        app.dependency_overrides.clear()
