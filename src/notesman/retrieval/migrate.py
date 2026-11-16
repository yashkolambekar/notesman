"""One-off: rebuild the collection with BM25 sparse vectors, keeping every point.

    uv run python -m notesman.retrieval.migrate

Qdrant cannot add a sparse vector to an existing collection, so this copies all points
(dense vectors and payloads as they are, nothing is re-embedded; the sparse vector is built
from the stored text) into a temporary collection, recreates the real one, and copies back.
The temporary copy is deleted only after the final count matches. STOP THE WORKER FIRST so
nothing is written while this runs. Safe to re-run: it resumes from a leftover temp copy.
"""

import asyncio

from qdrant_client import AsyncQdrantClient, models

from notesman.core.config import Settings, get_settings
from notesman.retrieval.qdrant import INDEXED_FIELDS, _sparse_config, make_client
from notesman.retrieval.sparse import SPARSE_NAME, doc_vector


async def create(qd: AsyncQdrantClient, s: Settings, name: str) -> None:
    await qd.create_collection(
        name,
        vectors_config=models.VectorParams(size=s.embed_dim, distance=models.Distance.COSINE),
        sparse_vectors_config=_sparse_config(),
    )
    for f in INDEXED_FIELDS:
        await qd.create_payload_index(name, f, models.PayloadSchemaType.KEYWORD)


async def copy(qd: AsyncQdrantClient, src: str, dst: str) -> int:
    n, offset = 0, None
    while True:
        pts, offset = await qd.scroll(src, limit=128, offset=offset, with_payload=True, with_vectors=True)
        batch = []
        for p in pts:
            vec = p.vector if isinstance(p.vector, list) else (p.vector or {}).get("")
            text = (p.payload or {}).get("text", "")
            title = (p.payload or {}).get("section", "")
            batch.append(
                models.PointStruct(id=p.id, vector={"": vec, SPARSE_NAME: doc_vector(f"{title} {text}")}, payload=p.payload)
            )
        if batch:
            await qd.upsert(dst, points=batch, wait=True)
            n += len(batch)
        if offset is None:
            return n


async def count(qd: AsyncQdrantClient, name: str) -> int:
    return (await qd.count(name, exact=True)).count


async def main() -> None:
    s = get_settings()
    qd = make_client(s)
    name, tmp = s.qdrant_collection, s.qdrant_collection + "_migrating"

    has_main = await qd.collection_exists(name)
    if has_main and SPARSE_NAME in ((await qd.get_collection(name)).config.params.sparse_vectors or {}):
        print("Already migrated, nothing to do.")
    else:
        if has_main:
            if await qd.collection_exists(tmp):
                await qd.delete_collection(tmp)
            await create(qd, s, tmp)
            total = await count(qd, name)
            print(f"copying {total} points to {tmp} ...")
            await copy(qd, name, tmp)
            if await count(qd, tmp) != total:
                raise SystemExit("temp copy is incomplete; the original was NOT touched")
            await qd.delete_collection(name)
        # (re)build the real collection from the temp copy
        await create(qd, s, name)
        total = await count(qd, tmp)
        print(f"copying {total} points back into {name} ...")
        await copy(qd, tmp, name)
        if await count(qd, name) != total:
            raise SystemExit(f"copy back incomplete; your data is safe in {tmp}. Re-run this command.")
        await qd.delete_collection(tmp)
        print(f"done: {total} points now have hybrid search.")
    await qd.close()


if __name__ == "__main__":
    asyncio.run(main())
