"""Real run: ingest a syllabus and a reference, then answer questions with the real models.
Needs GEMINI_API_KEY and OPENROUTER_API_KEY; creates and removes its own subject."""

import asyncio
import uuid

import pymupdf
import pytest

from notesman.answer.generate import NoMaterial, generate_answer
from notesman.core.config import get_settings
from notesman.db.base import SessionLocal, engine
from notesman.db.models import Course, File, Job, Subject
from notesman.ingest.pipeline import process_job
from notesman.llm.gemini import GeminiEmbedder
from notesman.llm.openrouter import OpenRouterChat
from notesman.retrieval.qdrant import delete_points, ensure_collection, make_client

s0 = get_settings()
pytestmark = pytest.mark.skipif(not (s0.gemini_api_key and s0.openrouter_api_key), reason="no API keys")


class FakeStorage:
    def __init__(self):
        self.blobs = {}

    async def get(self, key):
        return self.blobs[key]

    async def put_bytes(self, key, data, content_type=None):
        self.blobs[key] = data


def pdf(pages):
    d = pymupdf.open()
    for t in pages:
        d.new_page().insert_textbox(pymupdf.Rect(60, 60, 540, 780), t, fontsize=11)
    return d.tobytes()


SYLLABUS = ["Unit 2: CPU Scheduling\n\nScheduling criteria. FCFS, SJF and Round Robin algorithms. Time quantum. Gantt charts."]
REFERENCE = [
    "CPU Scheduling\n\nRound Robin (RR) scheduling is designed for time-sharing systems. Each process gets a small unit of CPU time called a time quantum, usually 10 to 100 milliseconds. After the quantum expires the process is preempted and moved to the tail of the ready queue.",
    "Round Robin performance\n\nIf the time quantum is very large, Round Robin degenerates into FCFS. If the quantum is very small, context switch overhead dominates. A good rule is that 80 percent of CPU bursts should be shorter than the quantum.",
    "Memory\n\nPaging divides physical memory into fixed-size frames and logical memory into pages of the same size.",
]


def test_answer_end_to_end():
    async def run():
        s = get_settings()
        qd, emb, chat = make_client(s), GeminiEmbedder(s, patient=True), OpenRouterChat(s)
        await ensure_collection(qd, s)
        sid, st = uuid.uuid4(), FakeStorage()
        try:
            async with SessionLocal() as db:
                cid = uuid.uuid4()
                db.add(Course(id=cid, name="zz test course"))
                await db.flush()
                db.add(Subject(id=sid, course_id=cid, name="Operating Systems"))
                await db.flush()
                jobs = []
                for kind, name, pages in [("syllabus", "syllabus.pdf", SYLLABUS), ("reference", "galvin.pdf", REFERENCE)]:
                    fid = uuid.uuid4()
                    key = f"subjects/{sid}/{fid}/original.pdf"
                    st.blobs[key] = pdf(pages)
                    db.add(File(id=fid, subject_id=sid, kind=kind, filename=name, size_bytes=1,
                                sha256=uuid.uuid4().hex, r2_key=key, status="processing"))
                    await db.flush()
                    j = Job(file_id=fid, stage="convert", attempts=1)
                    db.add(j)
                    await db.flush()
                    jobs.append(j.id)
                await db.commit()
            for j in jobs:
                await process_job(j, s, st, qd, emb)

            d = await generate_answer(qd=qd, s=s, emb=emb, chat=chat, subject_id=sid, subject_name="Operating Systems",
                                      question="Explain Round Robin scheduling and the effect of the time quantum.",
                                      nudges=[], comment="", previous="")
            print("\n--- ANSWER ---\n", d.answer_md, "\n--- SOURCES ---\n", d.sources, "\n--- MATCH ---\n", d.syllabus_match)
            assert "quantum" in d.answer_md.lower() and "[1]" in d.answer_md
            assert d.sources and d.sources[0]["file"] == "galvin.pdf"
            assert d.syllabus_match and "Scheduling" in d.syllabus_match
            assert "frame" not in d.answer_md.lower()  # unrelated paging chunk not used

            d2 = await generate_answer(qd=qd, s=s, emb=emb, chat=chat, subject_id=sid, subject_name="Operating Systems",
                                       question="Explain Round Robin scheduling and the effect of the time quantum.",
                                       nudges=["Shorter"], comment="Use a one-line analogy at the end.", previous=d.answer_md)
            print("\n--- REVISED ---\n", d2.answer_md)
            assert len(d2.answer_md) < len(d.answer_md) * 1.3

            with pytest.raises(NoMaterial):
                await generate_answer(qd=qd, s=s, emb=emb, chat=chat, subject_id=sid, subject_name="Operating Systems",
                                      question="Who won the 1998 football world cup?", nudges=[], comment="", previous="")
        finally:
            await delete_points(qd, s, "subject_id", str(sid))
            async with SessionLocal() as db:
                subj = await db.get(Subject, sid)
                if subj:
                    await db.delete(await db.get(Course, subj.course_id))
                    await db.commit()
            await emb.aclose(); await chat.aclose(); await qd.close(); await engine.dispose()

    asyncio.run(run())
