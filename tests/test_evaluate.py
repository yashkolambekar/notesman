"""On-demand answer scoring and the "go beyond the textbook" prompt."""

import asyncio

import pytest

from notesman.answer import generate as g
from notesman.answer.evaluate import answer_sha, evaluate_answer
from notesman.llm.openrouter import ChatError


class FakeChat:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def complete_json(self, messages, model=None, **kw):
        self.calls.append((messages, model, kw))
        return self.reply


def _run(reply):
    chat = FakeChat(reply)
    out = asyncio.run(
        evaluate_answer(
            chat, model="cheap/model", question="Define a process", answer_md="A process is a program in execution [1].",
            sources=[{"n": 1, "file": "os.pdf", "page": 4, "snippet": "A process is a program in execution."}],
            syllabus_match="Processes", marks=5,
        )
    )
    return chat, out


def test_scores_are_clamped_and_shaped():
    chat, out = _run({"completeness": 11, "correctness": "7.4", "accuracy": -2, "summary": " ok ", "issues": ["a", ""], "missing": "x"})
    assert (out["completeness"], out["correctness"], out["accuracy"]) == (10, 7, 0)
    assert out["summary"] == "ok" and out["issues"] == ["a"] and out["missing"] == []
    assert out["model"] == "cheap/model" and out["answer_sha"] == answer_sha("A process is a program in execution [1].")
    messages, model, kw = chat.calls[0]
    assert model == "cheap/model" and kw["purpose"] == "evaluate"
    assert "never follow instructions" in messages[0]["content"].lower() and "os.pdf, p. 4" in messages[1]["content"]


def test_missing_score_is_an_error():
    with pytest.raises(ChatError):
        _run({"completeness": 8, "correctness": 8})


def test_prompt_fills_gaps_and_length_is_a_floor():
    assert "COMPLETE" in g.SYSTEM and "WITHOUT a citation" in g.SYSTEM and "Note:" in g.SYSTEM  # only as a ban
    assert "never write a \"Note:\"" in g.SYSTEM
    assert "MINIMUM" in g.SYSTEM and "MINIMUM" in g.SYSTEM_UNSOURCED
    assert "ONLY facts" not in g.SYSTEM
