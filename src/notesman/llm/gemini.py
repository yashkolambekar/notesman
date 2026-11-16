"""Embeddings through the Gemini API (Google AI Studio).

Gemini Embedding 2 has no task_type switch. Instead the task is written into the
text itself, and it must be applied on both sides: documents at index time,
queries at search time.

Rate limits (429) and server hiccups (5xx) are retried with backoff. With
`patient=True` (used by ingestion) they are retried forever, because a rate limit
is never a reason to give up on a file. Real errors (bad key, bad request) raise.
"""

import asyncio
import logging
import math
import random
import re
from typing import Literal

import httpx

from notesman.core.config import Settings

log = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
MAX_BATCH = 100  # batchEmbedContents hard limit
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MAX_WAIT = 300  # never sleep longer than 5 minutes between attempts

Role = Literal["document", "query"]


class EmbedError(RuntimeError):
    """A failure that retrying will not fix."""


def format_text(text: str, role: Role, title: str | None = None) -> str:
    if role == "query":
        return f"task: search result | query: {text}"
    return f"title: {title or 'none'} | text: {text}"


def normalize(vec: list[float], dim: int) -> list[float]:
    """Truncate to `dim` (Matryoshka) and L2-normalise. Only the full 3072 vector
    comes pre-normalised, so we always do it ourselves for cosine search."""
    vec = vec[:dim]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def retry_delay(res: httpx.Response | None, attempt: int) -> float:
    """How long to wait: whatever Google asks for, else exponential backoff, plus jitter."""
    asked = 0.0
    if res is not None:
        header = res.headers.get("retry-after")
        if header and header.replace(".", "", 1).isdigit():
            asked = float(header)
        m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', res.text)
        if m:
            asked = max(asked, float(m.group(1)))
    backoff = min(2 ** min(attempt, 8), MAX_WAIT)
    return min(max(asked, backoff), MAX_WAIT) + random.uniform(0, 1.5)


class GeminiEmbedder:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, patient: bool = False):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.model = settings.embed_model
        self.dim = settings.embed_dim
        self.patient = patient
        self._key = settings.gemini_api_key
        self._client = client or httpx.AsyncClient(timeout=60)

    async def embed(
        self,
        texts: list[str],
        role: Role,
        titles: list[str | None] | None = None,
    ) -> list[list[float]]:
        titles = titles or [None] * len(texts)
        formatted = [format_text(t, role, ti) for t, ti in zip(texts, titles, strict=True)]
        out: list[list[float]] = []
        for i in range(0, len(formatted), MAX_BATCH):
            out.extend(await self._batch(formatted[i : i + MAX_BATCH]))
        return out

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self.dim,
                }
                for t in texts
            ]
        }
        url = f"{API_ROOT}/models/{self.model}:batchEmbedContents"
        headers = {"x-goog-api-key": self._key}
        limit = None if self.patient else 5

        attempt = 0
        while True:
            res: httpx.Response | None = None
            try:
                res = await self._client.post(url, json=body, headers=headers)
                transient = res.status_code in RETRY_STATUS
            except httpx.TransportError as e:
                transient, why = True, f"network error: {type(e).__name__}"
            else:
                why = f"HTTP {res.status_code}"

            if res is not None and res.status_code < 400:
                vectors = [e["values"] for e in res.json()["embeddings"]]
                if len(vectors) != len(texts):
                    raise EmbedError("Gemini returned a different number of embeddings than inputs")
                return [normalize(v, self.dim) for v in vectors]

            if not transient:
                raise EmbedError(f"Gemini embeddings failed ({res.status_code}): {res.text[:300]}")
            attempt += 1
            if limit is not None and attempt >= limit:
                raise EmbedError(f"Gemini embeddings still failing after {attempt} attempts ({why})")
            wait = retry_delay(res, attempt)
            log.warning("Gemini %s, retrying in %.0fs (attempt %d)", why, wait, attempt)
            await asyncio.sleep(wait)

    async def aclose(self) -> None:
        await self._client.aclose()
