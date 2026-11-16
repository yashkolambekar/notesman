"""One file, start to finish: R2 -> text -> chunks -> embeddings -> Qdrant.

Idempotent: point ids are deterministic and every point stores a hash of the exact text
that was embedded, so a re-run (after a crash, or a retry) only embeds what is missing.
That matters because every embedding call may be rate limited.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime

from qdrant_client import AsyncQdrantClient, models

from notesman.core.config import Settings
from notesman.db.base import SessionLocal
from notesman.db.models import File, Job
from notesman.ingest.chunker import Chunk, Page, chunk_pages
from notesman.ingest.convert import ConvertError, convert
from notesman.llm.gemini import EmbedError, GeminiEmbedder
from notesman.retrieval.qdrant import point_id
from notesman.retrieval.sparse import SPARSE_NAME, doc_vector
from notesman.storage.r2 import R2Storage

log = logging.getLogger(__name__)

# Syllabus: break at every heading so a chunk maps to one topic. References: break at
# chapter/section level and pack the rest up to ~600 tokens.
CHUNKING = {
    "syllabus": dict(max_chars=3200, overlap_chars=0, break_level=6),
    "reference": dict(max_chars=2400, overlap_chars=300, break_level=2),
}


async def _retry(fn, what: str, attempts: int = 5):
    """Retry infrastructure calls (R2, Qdrant) a few times before giving up."""
    for i in range(attempts):
        try:
            return await fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            wait = 2 ** (i + 1)
            log.warning("%s failed (%s), retrying in %ds", what, e, wait)
            await asyncio.sleep(wait)


async def _set_stage(job_id: uuid.UUID, stage: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if job:
            job.stage = stage
            await db.commit()


async def _fail(job_id: uuid.UUID, file_id: uuid.UUID, message: str) -> None:
    log.error("file %s failed: %s", file_id, message)
    async with SessionLocal() as db:
        job, file = await db.get(Job, job_id), await db.get(File, file_id)
        if job:
            job.stage, job.error, job.finished_at = "failed", message[:1000], datetime.now(UTC)
        if file:
            file.status, file.error = "failed", message[:1000]
        await db.commit()


def markdown_of(pages: list[Page]) -> str:
    return "\n\n".join(
        (f"<!-- page {p.number} -->\n\n" if p.number else "") + p.text.strip() for p in pages
    )


def embed_input(chunk: Chunk, filename: str) -> tuple[str, str]:
    """(title, text) as sent to the embedder: the heading path travels with the chunk."""
    return chunk.section or filename, chunk.text


def text_hash(title: str, text: str, model: str, dim: int) -> str:
    return hashlib.sha256(f"{model}|{dim}|{title}|{text}".encode()).hexdigest()


async def process_job(
    job_id: uuid.UUID,
    s: Settings,
    storage: R2Storage,
    qd: AsyncQdrantClient,
    emb: GeminiEmbedder,
) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        file = await db.get(File, job.file_id) if job else None
        if job is None or file is None:
            return
        fid, sid = file.id, file.subject_id
        filename, kind, key = file.filename, file.kind, file.r2_key
    log.info("ingesting %s (%s, %s)", filename, kind, fid)

    try:
        # 1. convert
        await _set_stage(job_id, "convert")
        data = await _retry(lambda: storage.get(key), "R2 download")
        pages = await asyncio.to_thread(convert, filename, data)
        text_key = f"subjects/{sid}/{fid}/text.md"
        md = markdown_of(pages).encode()
        await _retry(lambda: storage.put_bytes(text_key, md, "text/markdown"), "R2 upload")

        # 2. chunk
        await _set_stage(job_id, "chunk")
        chunks = chunk_pages(pages, **CHUNKING[kind])
        if not chunks:
            raise ConvertError("No usable text after cleaning the file")
        log.info("%s: %d pages, %d chunks", filename, len(pages), len(chunks))

        # 3. embed + upsert, skipping chunks that are already stored and unchanged
        await _set_stage(job_id, "embed")
        items = []
        for c in chunks:
            title, text = embed_input(c, filename)
            items.append((c, title, text, text_hash(title, text, s.embed_model, s.embed_dim)))

        ids = [point_id(str(fid), c.index) for c, *_ in items]
        have: dict[str, str | None] = {}
        for i in range(0, len(ids), 200):
            recs = await _retry(
                lambda i=i: qd.retrieve(s.qdrant_collection, ids=ids[i : i + 200], with_payload=["text_sha"], with_vectors=False),
                "Qdrant lookup",
            )
            have.update({str(r.id): (r.payload or {}).get("text_sha") for r in recs})
        todo = [it for it, pid in zip(items, ids, strict=True) if have.get(pid) != it[3]]
        log.info("%s: %d of %d chunks need embedding", filename, len(todo), len(items))

        done = 0
        for i in range(0, len(todo), s.embed_batch_size):
            batch = todo[i : i + s.embed_batch_size]
            vecs = await emb.embed([t for _, _, t, _ in batch], "document", [ti for _, ti, _, _ in batch])
            points = [
                models.PointStruct(
                    id=point_id(str(fid), c.index),
                    vector={"": v, SPARSE_NAME: doc_vector(f"{ti} {t}")},
                    payload={
                        "subject_id": str(sid),
                        "file_id": str(fid),
                        "kind": kind,
                        "source_name": filename,
                        "section": c.section,
                        "page": c.page_start,
                        "page_end": c.page_end,
                        "chunk_index": c.index,
                        "text": c.text,
                        "text_sha": sha,
                        "embed_model": s.embed_model,
                    },
                )
                for (c, ti, t, sha), v in zip(batch, vecs, strict=True)
            ]
            await _set_stage(job_id, "upsert")
            await _retry(lambda p=points: qd.upsert(s.qdrant_collection, points=p, wait=True), "Qdrant upsert")
            await _set_stage(job_id, "embed")
            done += len(batch)
            log.info("%s: embedded %d/%d", filename, done, len(todo))

        # drop leftovers if the file now has fewer chunks than a previous run
        await _retry(
            lambda: qd.delete(
                s.qdrant_collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(key="file_id", match=models.MatchValue(value=str(fid))),
                            models.FieldCondition(key="chunk_index", range=models.Range(gte=len(chunks))),
                        ]
                    )
                ),
            ),
            "Qdrant cleanup",
        )

        # 4. done (unless the file was deleted while we worked)
        async with SessionLocal() as db:
            job, file = await db.get(Job, job_id), await db.get(File, fid)
            if file is None:
                log.info("%s was deleted during ingestion, removing its points", filename)
                await qd.delete(
                    s.qdrant_collection,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[models.FieldCondition(key="file_id", match=models.MatchValue(value=str(fid)))]
                        )
                    ),
                )
                return
            file.status, file.error = "ready", None
            file.pages = len([p for p in pages if p.number])
            file.chunk_count = len(chunks)
            file.text_r2_key = text_key
            if job:
                job.stage, job.error, job.finished_at = "done", None, datetime.now(UTC)
            await db.commit()
        log.info("done: %s (%d chunks)", filename, len(chunks))

    except (ConvertError, EmbedError) as e:
        await _fail(job_id, fid, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("unexpected error while ingesting %s", filename)
        await _fail(job_id, fid, f"Unexpected error: {type(e).__name__}: {e}")
