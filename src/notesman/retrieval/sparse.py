"""BM25-style sparse vectors, built locally (no model, no extra dependency).

Documents store the saturated, length-normalised term frequency; Qdrant multiplies by IDF at
query time (the collection's sparse vector uses `modifier=IDF`), which together is BM25.
Terms are hashed to a stable uint32, so the same word always lands on the same index.
"""

import re
import zlib
from collections import Counter

from qdrant_client import models

K1, B, AVG_DOC_LEN = 1.2, 0.75, 350.0
SPARSE_NAME = "bm25"

STOP = frozenset(
    "a an and are as at be been but by can for from had has have he her his i if in into is it its "
    "may of on or our she so such than that the their them then there these they this to was we "
    "were what when where which who will with would you your not no also".split()
)
TOKEN = re.compile(r"[a-z0-9]+")


def stem(w: str) -> str:
    """Tiny suffix stripper so scheduling/scheduled/schedules/schedule meet in one term."""
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("es"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    return [stem(t) for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


def _index(term: str) -> int:
    return zlib.crc32(term.encode())


def doc_vector(text: str) -> models.SparseVector:
    toks = tokens(text)
    n = len(toks) or 1
    acc: Counter[int] = Counter()
    for term, tf in Counter(toks).items():
        acc[_index(term)] += tf * (K1 + 1) / (tf + K1 * (1 - B + B * n / AVG_DOC_LEN))
    idx = sorted(acc)
    return models.SparseVector(indices=idx, values=[acc[i] for i in idx])


def query_vector(text: str) -> models.SparseVector:
    idx = sorted({_index(t) for t in tokens(text)})
    return models.SparseVector(indices=idx, values=[1.0] * len(idx))
