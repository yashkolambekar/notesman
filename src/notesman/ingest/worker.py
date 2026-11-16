"""Ingestion worker. Run it as its own process:

    uv run python -m notesman.ingest.worker

Polls the jobs table, one file at a time. Safe to stop and restart at any time: unfinished
jobs go back to the queue and already-embedded chunks are not embedded again.
"""

import asyncio
import logging
import signal
from datetime import UTC, datetime

from sqlalchemy import select, update

from notesman.core.config import get_settings
from notesman.db.base import SessionLocal, engine
from notesman.db.models import File, Job
from notesman.ingest.pipeline import process_job
from notesman.llm.gemini import GeminiEmbedder
from notesman.retrieval.qdrant import ensure_collection, make_client
from notesman.storage.r2 import get_storage

log = logging.getLogger("notesman.worker")
POLL_SECONDS = 3
IN_PROGRESS = ("convert", "chunk", "embed", "upsert")


async def requeue_stuck() -> None:
    """A job left mid-way by a previous run (this worker is the only one) goes back to the queue."""
    async with SessionLocal() as db:
        stuck = (await db.execute(select(Job).where(Job.stage.in_(IN_PROGRESS)))).scalars().all()
        for job in stuck:
            job.stage = "queued"
            await db.execute(update(File).where(File.id == job.file_id).values(status="queued"))
        await db.commit()
    if stuck:
        log.info("requeued %d unfinished job(s)", len(stuck))


async def claim():
    async with SessionLocal() as db:
        job = (
            await db.execute(
                select(Job).where(Job.stage == "queued").order_by(Job.created_at).limit(1).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        job.stage, job.attempts, job.started_at, job.error = "convert", job.attempts + 1, datetime.now(UTC), None
        await db.execute(update(File).where(File.id == job.file_id).values(status="processing", error=None))
        await db.commit()
        return job.id


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    if not s.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set")
    storage = get_storage()  # raises a clear error if R2 is not configured

    qd = make_client(s)
    await ensure_collection(qd, s)
    emb = GeminiEmbedder(s, patient=True)  # rate limits are retried forever
    await requeue_stuck()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker ready, waiting for files (Ctrl+C to stop)")
    try:
        while not stop.is_set():
            try:
                job_id = await claim()
            except Exception:  # noqa: BLE001  (DB hiccup: wait and try again)
                log.exception("could not read the job queue")
                job_id = None
                await asyncio.sleep(10)
            if job_id is None:
                try:
                    await asyncio.wait_for(stop.wait(), POLL_SECONDS)
                except TimeoutError:
                    pass
                continue
            task = asyncio.create_task(process_job(job_id, s, storage, qd, emb))
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set() and not task.done():
                task.cancel()  # interrupted: requeue_stuck() picks it up next start
                log.info("stopping, the current file will resume next time")
            stopper.cancel()
    finally:
        await emb.aclose()
        await qd.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
