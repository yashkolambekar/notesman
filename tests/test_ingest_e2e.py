"""Real ingestion: PDF -> chunks -> Gemini embeddings -> Qdrant -> search.

Uses the real database, Qdrant and Gemini key from .env, but a fake file store (R2 is not
touched). Creates its own subject and removes it afterwards. Skipped without a Gemini key.
"""

import asyncio
import uuid

import pymupdf
import pytest
from sqlalchemy import select

from notesman.core.config import get_settings
from notesman.db.base import SessionLocal, engine
from notesman.db.models import File, Job, Subject
from notesman.ingest.pipeline import process_job
from notesman.llm.gemini import GeminiEmbedder
from notesman.retrieval.qdrant import delete_points, ensure_collection, make_client, subject_filter

pytestmark = pytest.mark.skipif(not get_settings().gemini_api_key, reason="no GEMINI_API_KEY")


class FakeStorage:
    def __init__(self, blobs):
        self.blobs = blobs

    async def get(self, key):
        return self.blobs[key]

    async def put_bytes(self, key, data, content_type=None):
        self.blobs[key] = data


def make_pdf() -> bytes:
    doc = pymupdf.open()
    for text in [
        "Process Management\n\nA process is a program in execution.\nIt has a stack, registers and a program counter.",
        "CPU Scheduling\n\nRound Robin gives every process a fixed time quantum.\nShortest job first minimises average waiting time.",
    ]:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 700), text, fontsize=12)
    return doc.tobytes()


def test_ingest_pdf():
    async def run():
        s = get_settings()
        qd, emb = make_client(s), GeminiEmbedder(s, patient=True)
        await ensure_collection(qd, s)
        sid, fid = uuid.uuid4(), uuid.uuid4()
        key = f"subjects/{sid}/{fid}/original.pdf"
        storage = FakeStorage({key: make_pdf()})
        try:
            async with SessionLocal() as db:
                db.add(Subject(id=sid, name="zz ingest test"))
                await db.flush()
                db.add(File(id=fid, subject_id=sid, kind="reference", filename="os.pdf", size_bytes=1,
                            sha256=uuid.uuid4().hex, r2_key=key, status="processing"))
                job = Job(file_id=fid, stage="convert", attempts=1)
                db.add(job)
                await db.commit()
                job_id = job.id

            await process_job(job_id, s, storage, qd, emb)

            async with SessionLocal() as db:
                f = await db.get(File, fid)
                assert f.status == "ready", f.error
                assert f.chunk_count >= 1 and f.pages == 2
                assert (await db.get(Job, job_id)).stage == "done"
            assert f"subjects/{sid}/{fid}/text.md" in storage.blobs

            # searchable, with metadata, scoped to the subject
            [q] = await emb.embed(["What is round robin scheduling?"], "query")
            hits = (await qd.query_points(s.qdrant_collection, query=q, limit=3,
                                          query_filter=subject_filter(str(sid), "reference"), with_payload=True)).points
            assert hits and "Round Robin" in hits[0].payload["text"]
            p = hits[0].payload
            assert p["file_id"] == str(fid) and p["subject_id"] == str(sid) and p["page"] == 2
            assert p["source_name"] == "os.pdf" and p["embed_model"] == s.embed_model

            # re-running embeds nothing new (resume / idempotent)
            calls = {"n": 0}
            real = emb.embed

            async def counting(*a, **k):
                calls["n"] += 1
                return await real(*a, **k)

            emb.embed = counting
            await process_job(job_id, s, storage, qd, emb)
            assert calls["n"] == 0
            n = (await qd.count(s.qdrant_collection, count_filter=subject_filter(str(sid)), exact=True)).count
            assert n == f.chunk_count
        finally:
            await delete_points(qd, s, "subject_id", str(sid))
            async with SessionLocal() as db:
                subj = await db.get(Subject, sid)
                if subj:
                    await db.delete(subj)
                    await db.commit()
            await emb.aclose()
            await qd.close()
            await engine.dispose()

    asyncio.run(run())
