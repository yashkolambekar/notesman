from notesman.ingest.chunker import Page, chunk_pages

DOC = """# Unit 1: Processes

## Process concept

A process is a program in execution. It has a program counter, registers and a stack.

## Process states

| State | Meaning |
| --- | --- |
| New | Being created |
| Ready | Waiting for CPU |

```c
wait(S) { while (S <= 0); S--; }
```

# Unit 2: Scheduling

Scheduling decides which ready process runs next on the CPU.
"""


def test_sections_page_and_tables():
    chunks = chunk_pages([Page(3, DOC)], break_level=2)
    sections = [c.section for c in chunks]
    assert sections == [
        "Unit 1: Processes > Process concept",
        "Unit 1: Processes > Process states",
        "Unit 2: Scheduling",
    ]
    assert all(c.page_start == 3 == c.page_end for c in chunks)
    states = chunks[1].text
    assert "| New | Being created |" in states and "wait(S)" in states  # table and code kept whole
    assert [c.index for c in chunks] == [0, 1, 2]


def test_never_crosses_a_section_and_respects_size():
    para = "Sentence number one is here. " * 40
    text = "# A\n\n" + para + "\n\n# B\n\n" + para
    chunks = chunk_pages([Page(None, text)], max_chars=500, overlap_chars=100, break_level=1)
    assert all(len(c.text) <= 500 for c in chunks)
    assert {c.section for c in chunks} == {"A", "B"}
    assert [c.section for c in chunks] == sorted(c.section for c in chunks)  # A's before B's


def test_page_range_and_overlap():
    p1 = Page(1, "# T\n\n" + "Alpha alpha alpha alpha. " * 30)
    p2 = Page(2, "Beta beta beta beta. " * 30)
    chunks = chunk_pages([p1, p2], max_chars=600, overlap_chars=200, break_level=1)
    assert chunks[0].page_start == 1
    assert any(c.page_start == 1 and c.page_end == 2 for c in chunks) or chunks[-1].page_end == 2
    assert len(chunks) >= 2
    assert all(len(c.text) <= 600 for c in chunks)


def test_deterministic_and_drops_junk():
    pages = [Page(1, DOC), Page(2, "# x\n\n.\n\n--")]
    assert [c.text for c in chunk_pages(pages)] == [c.text for c in chunk_pages(pages)]
    assert not any(len(c.text) < 20 for c in chunk_pages(pages))


def test_syllabus_breaks_at_every_heading():
    chunks = chunk_pages([Page(1, DOC)], max_chars=3200, overlap_chars=0, break_level=6)
    assert len(chunks) == 3
