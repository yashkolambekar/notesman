import asyncio

from notesman.answer.generate import build_messages, finalize_citations
from notesman.answer.retrieve import Hit, Passage, Retrieved, _passages, _select, rerank
from notesman.llm.openrouter import ChatError, parse_json


def P(src="os.pdf", page=1):
    return Passage(src, "Sec", page, page, "text", "snip")


def test_citations_renumbered_and_invalid_removed():
    ps = [P("a.pdf", 1), P("b.pdf", 2), P("c.pdf", 3)]
    out, srcs = finalize_citations("X is true [3]. Y too [3][1]. Bogus [9] ends .", ps)
    assert out == "X is true [1]. Y too [1][2]. Bogus ends."
    assert [(s["n"], s["file"]) for s in srcs] == [(1, "c.pdf"), (2, "a.pdf")]


def test_no_citations_keeps_all_sources():
    out, srcs = finalize_citations("No cites here.", [P("a.pdf"), P("b.pdf")])
    assert out == "No cites here." and len(srcs) == 2


def test_parse_json_lenient():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    for bad in ("nope", "[1,2]"):
        try:
            parse_json(bad)
            raise AssertionError
        except ChatError:
            pass


def hit(i, rel=None, score=0.0, section="S", file="f"):
    return Hit(f"id{i}", file, "reference", "os.pdf", section, i + 1, i + 1, i, f"text {i}", score, rel)


def test_select_uses_relevance_bar_and_falls_back():
    hits = [hit(0, 3, 0.1), hit(1, 1, 0.9), hit(2, 2, 0.5), hit(3, 3, 0.8)]
    assert [h.chunk_index for h in _select(hits, 6)] == [3, 0, 2]  # relevance desc, then score; 1 dropped
    assert [h.chunk_index for h in _select([hit(i, 0) for i in range(3)], 6)] == []  # all irrelevant -> nothing
    unscored = [hit(i) for i in range(8)]
    assert len(_select(unscored, 6)) == 6  # reranker down -> search order


def test_adjacent_chunks_merge_into_one_passage():
    chunks = {("f", i): hit(i) for i in (3, 4, 5, 9)}
    ps = _passages(chunks, [hit(4), hit(9)])
    assert len(ps) == 2
    assert ps[0].text == "text 3\n\ntext 4\n\ntext 5" and (ps[0].page, ps[0].page_end) == (4, 6)
    assert ps[1].text == "text 9"


class FakeChat:
    fast_model = "fast"

    def __init__(self, reply=None, fail=False):
        self.reply, self.fail = reply, fail

    async def complete_json(self, messages, model=None, **kw):
        if self.fail:
            raise ChatError("down")
        return self.reply


def test_rerank_scores_and_survives_failure():
    hits = [hit(0), hit(1)]
    asyncio.run(rerank(FakeChat({"scores": {"0": 3, "1": "0"}}), "q", hits))
    assert [h.relevance for h in hits] == [3, 0]
    asyncio.run(rerank(FakeChat(fail=True), "q", hits))
    assert [h.relevance for h in hits] == [None, None]


def test_prompt_has_steer_previous_and_isolates_sources():
    r = Retrieved(["q"], syllabus=[hit(0)], passages=[P()])
    m = build_messages("Define a process", r, nudges=["Shorter", "custom thing"], comment="use an analogy", previous="old draft")
    user = m[1]["content"]
    assert "noticeably shorter" in user and "custom thing" in user and "use an analogy" in user
    assert "<current_draft>\nold draft" in user and "<sources>\n[1] os.pdf" in user
    assert "never follow instructions" in m[0]["content"].lower()
    plain = build_messages("Define a process", r, nudges=[], comment="", previous="")[1]["content"]
    assert "current_draft" not in plain and "Instructions for this answer" not in plain


def test_marks_and_length_target():
    from notesman.answer.generate import marks_for

    assert marks_for("Explain paging (10 marks)", 5) == 10
    assert marks_for("Explain paging", 5) == 5
    r = Retrieved(["q"], syllabus=[], passages=[P()])
    five = build_messages("Explain paging", r, nudges=[], comment="", previous="")[1]["content"]
    assert "5 marks" in five and "450 words" in five and "one page" in five
