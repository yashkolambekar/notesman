import asyncio

import httpx
import pytest

from notesman.core.config import Settings
from notesman.llm import gemini
from notesman.llm.gemini import EmbedError, GeminiEmbedder, format_text, retry_delay


def settings():
    return Settings(gemini_api_key="k", embed_dim=4, _env_file=None)


def ok(n):
    return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0, 0.0, 0.0, 9.9]} for _ in range(n)]})


def make(handler, patient):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiEmbedder(settings(), client=client, patient=patient)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(gemini.asyncio, "sleep", fake_sleep)
    return waits


def test_format_and_truncate():
    assert format_text("q", "query") == "task: search result | query: q"
    assert format_text("t", "document", "Unit 1") == "title: Unit 1 | text: t"
    [v] = asyncio.run(make(lambda r: ok(1), False).embed(["a"], "document"))
    assert v == [0.6, 0.8, 0.0, 0.0]  # truncated to dim=4 and L2-normalised


def test_patient_retries_rate_limit_many_times(no_sleep):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 12:  # far beyond the 5 attempts a non-patient client gets
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        return ok(2)

    out = asyncio.run(make(handler, True).embed(["a", "b"], "document"))
    assert len(out) == 2 and calls["n"] == 13
    assert all(w >= 7 for w in no_sleep)  # honoured Retry-After


def test_not_patient_gives_up(no_sleep):
    with pytest.raises(EmbedError, match="still failing"):
        asyncio.run(make(lambda r: httpx.Response(429), False).embed(["a"], "document"))


def test_real_errors_are_not_retried(no_sleep):
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(EmbedError, match="400"):
        asyncio.run(make(handler, True).embed(["a"], "document"))
    assert n["c"] == 1 and no_sleep == []


def test_retries_network_errors_and_5xx(no_sleep):
    seq = iter([httpx.ConnectError("boom"), httpx.Response(503), ok(1)])

    def handler(req):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return item

    assert len(asyncio.run(make(handler, True).embed(["a"], "document"))) == 1


def test_retry_delay_reads_google_body_and_caps():
    r = httpx.Response(429, text='{"details":[{"retryDelay":"34s"}]}')
    assert 34 <= retry_delay(r, 1) < 36
    assert retry_delay(httpx.Response(429), 50) <= gemini.MAX_WAIT + 2
