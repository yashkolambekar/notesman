"""Uploaded file -> Markdown pages. Blocking: call it from a thread."""

import io
from pathlib import Path

from notesman.ingest.chunker import Page


class ConvertError(RuntimeError):
    """The file cannot be turned into text (the message is shown to the admin)."""


def convert(filename: str, data: bytes) -> list[Page]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        pages = _pdf(data)
    elif ext in (".txt", ".md"):
        pages = [Page(None, data.decode("utf-8", errors="replace"))]
    elif ext in (".docx", ".pptx", ".epub"):
        pages = [Page(None, _markitdown(data, ext))]
    elif ext in (".png", ".jpg", ".jpeg"):
        raise ConvertError("Image files are not supported yet. Upload a PDF instead.")
    else:
        raise ConvertError(f"Unsupported file type {ext!r}")

    if sum(len(p.text.strip()) for p in pages) < 40:
        raise ConvertError("No readable text found in this file")
    return pages


def _pdf(data: bytes) -> list[Page]:
    import pymupdf
    import pymupdf4llm

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise ConvertError(f"Could not open the PDF: {e}") from e
    if doc.needs_pass:
        raise ConvertError("The PDF is password protected")
    # pymupdf4llm runs Tesseract OCR itself on pages that have no text layer.
    chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)
    return [Page(c["metadata"]["page_number"], c["text"]) for c in chunks]


def _markitdown(data: bytes, ext: str) -> str:
    from markitdown import MarkItDown

    try:
        return MarkItDown().convert_stream(io.BytesIO(data), file_extension=ext).text_content
    except Exception as e:  # noqa: BLE001
        raise ConvertError(f"Could not read the {ext} file: {e}") from e
