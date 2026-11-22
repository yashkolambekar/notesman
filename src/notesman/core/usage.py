"""Collects the cost of paid provider calls during one request or job, then saves them in one go.

The LLM clients only call `collector.add(...)`; they never touch the database. The caller flushes in a
`finally` so a call that spent money is recorded even when the overall operation failed.
Saving usage must never break the real work, so flush swallows and logs its own errors.
"""

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from notesman.core.config import Settings
from notesman.db.base import SessionLocal
from notesman.db.models import UsageEvent

log = logging.getLogger(__name__)


@dataclass
class Call:
    kind: str  # "chat" | "embed"
    purpose: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    estimated: bool = False


def estimate_tokens(texts: list[str]) -> int:
    return sum(len(t) for t in texts) // 4


def embed_cost(s: Settings, tokens: int) -> float:
    return tokens / 1_000_000 * s.embed_price_per_mtok_usd


def chat_cost_from_tokens(s: Settings, tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * s.chat_price_in_per_mtok_usd + tokens_out * s.chat_price_out_per_mtok_usd) / 1_000_000


@dataclass
class UsageCollector:
    calls: list[Call] = field(default_factory=list)

    def add(self, call: Call) -> None:
        self.calls.append(call)

    @property
    def total_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    async def flush(
        self,
        *,
        user_id: uuid.UUID | None,
        subject_id: uuid.UUID | None = None,
        question_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
    ) -> None:
        calls, self.calls = self.calls, []
        if not calls:
            return
        try:
            async with SessionLocal() as db:
                db.add_all(
                    UsageEvent(
                        user_id=user_id, subject_id=subject_id, question_id=question_id, file_id=file_id,
                        kind=c.kind, purpose=c.purpose, model=c.model[:100],
                        input_tokens=c.input_tokens, output_tokens=c.output_tokens,
                        cost_usd=Decimal(f"{c.cost_usd:.6f}"), estimated=c.estimated,
                    )
                    for c in calls
                )
                await db.commit()
        except Exception:  # noqa: BLE001
            log.exception("could not save %d usage record(s)", len(calls))
