"""End-to-end check: embed -> upsert -> filtered search -> cleanup.

Run:  uv run python scripts/smoke.py
Needs GEMINI_API_KEY in .env and Qdrant running.
"""

import asyncio

from qdrant_client import models

from notesman.core.config import get_settings
from notesman.llm.gemini import GeminiEmbedder
from notesman.retrieval.qdrant import ensure_collection, make_client, point_id, subject_filter

DOCS = [
    ("A process is a program in execution, with its own registers, stack and data.", "syllabus"),
    ("Round Robin gives each process a fixed time quantum in turn.", "reference"),
    ("A relation is in 3NF if every non-key attribute depends only on the key.", "reference"),
]
OTHER_SUBJECT = "smoke-other"
SUBJECT = "smoke"


async def main() -> None:
    s = get_settings()
    qd = make_client(s)
    emb = GeminiEmbedder(s)
    try:
        await ensure_collection(qd, s)

        vecs = await emb.embed([d for d, _ in DOCS], "document")
        print(f"embedded {len(vecs)} docs, dim={len(vecs[0])} (expected {s.embed_dim})")
        assert len(vecs[0]) == s.embed_dim

        points = [
            models.PointStruct(
                id=point_id("smoke-file", i),
                vector=v,
                payload={
                    "subject_id": SUBJECT if i < 2 else OTHER_SUBJECT,
                    "file_id": "smoke-file",
                    "kind": kind,
                    "chunk_index": i,
                    "text": text,
                },
            )
            for i, (v, (text, kind)) in enumerate(zip(vecs, DOCS, strict=True))
        ]
        await qd.upsert(s.qdrant_collection, points=points, wait=True)

        [q] = await emb.embed(["What is round robin scheduling?"], "query")
        hits = (
            await qd.query_points(
                s.qdrant_collection, query=q, limit=3, query_filter=subject_filter(SUBJECT), with_payload=True
            )
        ).points
        for h in hits:
            print(f"{h.score:.3f}  [{h.payload['kind']}]  {h.payload['text']}")
        assert hits[0].payload["text"].startswith("Round Robin"), "wrong top hit"
        assert all(h.payload["subject_id"] == SUBJECT for h in hits), "subject filter leaked"
        print("OK: embedding, upsert, filtered search all work")
    finally:
        await qd.delete(
            s.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="file_id", match=models.MatchValue(value="smoke-file"))]
                )
            ),
        )
        await emb.aclose()
        await qd.close()


asyncio.run(main())
