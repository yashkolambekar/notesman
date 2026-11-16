import uuid
from urllib.parse import urlparse

from qdrant_client import AsyncQdrantClient, models

from notesman.core.config import Settings
from notesman.retrieval.sparse import SPARSE_NAME, query_vector

POINT_NS = uuid.UUID("6f1c2f5e-5a1e-4c55-9c0e-6e6f7465736d")  # fixed namespace for point ids
INDEXED_FIELDS = ("subject_id", "file_id", "kind")


def make_client(s: Settings) -> AsyncQdrantClient:
    """qdrant-client falls back to port 6333 whenever the URL has no explicit port, even
    for https. So pick the port ourselves: an explicit port in QDRANT_URL wins, otherwise
    443 for https and 6333 for plain http (local docker)."""
    u = urlparse(s.qdrant_url)
    https = u.scheme == "https"
    port = u.port or (443 if https else 6333)
    return AsyncQdrantClient(
        host=u.hostname,
        port=port,
        https=https,
        prefix=u.path.strip("/") or None,
        api_key=s.qdrant_api_key or None,
        prefer_grpc=False,
    )


def point_id(file_id: str, chunk_index: int) -> str:
    """Deterministic, so re-ingesting a file overwrites its points instead of duplicating."""
    return str(uuid.uuid5(POINT_NS, f"{file_id}:{chunk_index}"))


def _sparse_config() -> dict[str, models.SparseVectorParams]:
    return {SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)}


async def ensure_collection(client: AsyncQdrantClient, s: Settings) -> None:
    name = s.qdrant_collection
    if await client.collection_exists(name):
        info = await client.get_collection(name)
        size = info.config.params.vectors.size  # type: ignore[union-attr]
        if size != s.embed_dim:
            raise RuntimeError(
                f"Collection {name!r} has vector size {size} but EMBED_DIM={s.embed_dim}. "
                "Changing the dimension means re-embedding everything into a new collection."
            )
        if SPARSE_NAME not in (info.config.params.sparse_vectors or {}):
            # Qdrant cannot add a sparse vector to an existing collection in place.
            raise RuntimeError(
                f"Collection {name!r} predates hybrid search. Stop the worker, then run: "
                "uv run python -m notesman.retrieval.migrate"
            )
        return

    await client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=s.embed_dim, distance=models.Distance.COSINE),
        sparse_vectors_config=_sparse_config(),
    )
    for field in INDEXED_FIELDS:
        await client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)


def subject_filter(subject_id: str, kind: str | None = None) -> models.Filter:
    """Every query must go through this so subjects never leak into each other."""
    must = [models.FieldCondition(key="subject_id", match=models.MatchValue(value=subject_id))]
    if kind:
        must.append(models.FieldCondition(key="kind", match=models.MatchValue(value=kind)))
    return models.Filter(must=must)


async def delete_points(client: AsyncQdrantClient, s: Settings, field: str, value: str) -> None:
    """Delete every point whose payload `field` equals `value` (file_id or subject_id)."""
    await client.delete(
        s.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key=field, match=models.MatchValue(value=value))]
            )
        ),
    )


async def hybrid_search(
    client: AsyncQdrantClient,
    s: Settings,
    *,
    dense: list[float],
    text: str,
    flt: models.Filter,
    limit: int,
    candidates: int = 40,
):
    """Dense (meaning) + BM25 (exact terms) searched separately, then fused with RRF inside Qdrant."""
    res = await client.query_points(
        s.qdrant_collection,
        prefetch=[
            models.Prefetch(query=dense, filter=flt, limit=candidates),
            models.Prefetch(query=query_vector(text), using=SPARSE_NAME, filter=flt, limit=candidates),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=flt,
        limit=limit,
        with_payload=True,
    )
    return res.points
