"""No relevant material: refuse by default, or answer from general knowledge with a warning when allowed."""

import asyncio
import uuid

import pytest

from notesman.answer import generate as g
from notesman.answer.retrieve import Retrieved
from notesman.core.config import Settings


class FakeChat:
    model = "fake/model"

    def __init__(self):
        self.calls = []

    async def complete(self, messages, *a, **kw):
        self.calls.append((messages, kw))
        return "Test fitting catches misaligned parts early [1]. It saves rework."


def _run(allow, previous="", monkeypatch=None):
    async def empty(**kw):
        return Retrieved(queries=["q"])

    monkeypatch.setattr(g, "retrieve", empty)
    chat = FakeChat()
    coro = g.generate_answer(
        qd=None, s=Settings(), emb=None, chat=chat, subject_id=uuid.uuid4(), subject_name="Robotics",
        question="Why test-fit a robot?", nudges=[], comment="", previous=previous, allow_unsourced=allow,
    )
    return chat, coro


def test_refuses_by_default(monkeypatch):
    _, coro = _run(False, monkeypatch=monkeypatch)
    with pytest.raises(g.NoMaterial):
        asyncio.run(coro)


def test_allowed_answers_with_warning_and_no_sources(monkeypatch):
    chat, coro = _run(True, monkeypatch=monkeypatch)
    d = asyncio.run(coro)
    assert d.answer_md.startswith(g.UNSOURCED_WARNING)
    assert "[1]" not in d.answer_md and d.sources == [] and d.checked is False
    messages, kw = chat.calls[0]
    assert messages[0]["content"] == g.SYSTEM_UNSOURCED and "<sources>" not in messages[1]["content"]
    assert kw["purpose"] == "answer" and len(chat.calls) == 1  # no grounding check without sources


def test_warning_is_not_fed_back_as_previous_draft(monkeypatch):
    chat, coro = _run(True, previous=f"{g.UNSOURCED_WARNING}\n\nOld text", monkeypatch=monkeypatch)
    asyncio.run(coro)
    sent = chat.calls[0][0][1]["content"]
    assert "Old text" in sent and "No relevant material found" not in sent
