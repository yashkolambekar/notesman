"""Markdown -> chunks. Heading-aware, with a size cap and a little overlap.

Pure functions, no I/O. A chunk never crosses a section boundary (a heading at or above
`break_level`), tables and fenced code blocks stay whole where they fit, and every chunk
remembers its heading path and the page range it came from.
"""

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Page:
    number: int | None
    text: str


@dataclass
class Chunk:
    index: int
    text: str
    section: str
    page_start: int | None
    page_end: int | None


@dataclass
class _Block:
    text: str
    page: int | None
    kind: str  # "text" | "code" | "table"


def _blocks(page: Page) -> list[tuple[str, _Block | tuple[int, str]]]:
    """Split one page into paragraphs, tables, code blocks and headings, in order."""
    out: list[tuple[str, _Block | tuple[int, str]]] = []
    buf: list[str] = []
    in_code = False

    def flush():
        nonlocal buf
        text = "\n".join(buf).strip()
        buf = []
        if not text:
            return
        kind = "table" if all(l.lstrip().startswith("|") for l in text.splitlines()) else "text"
        out.append(("block", _Block(text, page.number, kind)))

    for line in page.text.splitlines():
        if line.lstrip().startswith("```"):
            if not in_code:
                flush()
                in_code = True
                buf = [line]
            else:
                buf.append(line)
                text = "\n".join(buf)
                buf, in_code = [], False
                out.append(("block", _Block(text, page.number, "code")))
            continue
        if in_code:
            buf.append(line)
            continue
        m = HEADING.match(line)
        if m:
            flush()
            out.append(("heading", (len(m.group(1)), m.group(2))))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    if in_code and buf:  # unterminated fence: keep what we have
        out.append(("block", _Block("\n".join(buf), page.number, "code")))
    else:
        flush()
    return out


def _split_oversized(b: _Block, max_chars: int) -> list[_Block]:
    if len(b.text) <= max_chars:
        return [b]
    if b.kind in ("code", "table"):
        lines, parts, cur = b.text.splitlines(), [], ""
        for line in lines:
            if cur and len(cur) + len(line) + 1 > max_chars:
                parts.append(cur)
                cur = ""
            cur += ("\n" if cur else "") + line
        if cur:
            parts.append(cur)
        pieces = parts
    else:
        pieces, cur = [], ""
        for sent in SENTENCE.split(b.text):
            while len(sent) > max_chars:  # a "sentence" with no boundary: hard split
                if cur:
                    pieces.append(cur)
                    cur = ""
                pieces.append(sent[:max_chars])
                sent = sent[max_chars:]
            if cur and len(cur) + len(sent) + 1 > max_chars:
                pieces.append(cur)
                cur = ""
            cur += (" " if cur else "") + sent
        if cur:
            pieces.append(cur)
    return [_Block(p, b.page, b.kind) for p in pieces if p.strip()]


def chunk_pages(
    pages: list[Page],
    *,
    max_chars: int = 2400,
    overlap_chars: int = 300,
    break_level: int = 2,
) -> list[Chunk]:
    """~600 tokens per chunk at the default size (about 4 characters per token)."""
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    cur: list[_Block] = []
    cur_section = ""

    def path() -> str:
        return " > ".join(t for _, t in stack)

    def size(blocks: list[_Block]) -> int:
        return sum(len(b.text) for b in blocks) + 2 * max(len(blocks) - 1, 0)

    def emit(blocks: list[_Block], section: str):
        text = "\n\n".join(b.text for b in blocks).strip()
        if sum(c.isalnum() for c in text) < 20:
            return
        pgs = [b.page for b in blocks if b.page is not None]
        chunks.append(
            Chunk(len(chunks), text, section, min(pgs) if pgs else None, max(pgs) if pgs else None)
        )

    def flush(keep_overlap: bool):
        nonlocal cur
        if not cur:
            return
        emit(cur, cur_section)
        tail: list[_Block] = []
        if keep_overlap:
            for b in reversed(cur):
                if size(tail) + len(b.text) > overlap_chars:
                    break
                tail.insert(0, b)
        cur = tail

    for page in pages:
        for kind, item in _blocks(page):
            if kind == "heading":
                level, title = item  # type: ignore[misc]
                stack[:] = [(l, t) for l, t in stack if l < level] + [(level, title)]
                if level <= break_level:
                    flush(keep_overlap=False)
                    cur = []
                    cur_section = path()
                else:
                    blk = _Block(f"{'#' * level} {title}", page.number, "text")
                    if cur and size(cur) + len(blk.text) > max_chars:
                        flush(keep_overlap=True)
                    if not cur:
                        cur_section = path()
                    cur.append(blk)
                continue

            for blk in _split_oversized(item, max_chars):  # type: ignore[arg-type]
                if cur and size(cur) + 2 + len(blk.text) > max_chars:
                    flush(keep_overlap=True)
                    # the overlap tail must not push the new block over the cap
                    while cur and size(cur) + 2 + len(blk.text) > max_chars:
                        cur.pop(0)
                if not cur:
                    cur_section = path()
                cur.append(blk)
    flush(keep_overlap=False)
    return chunks
