"""Chat completions through OpenRouter. Embeddings do NOT go through here."""

import asyncio
import json
import logging
import re

import httpx

from notesman.core.config import Settings
from notesman.core.usage import Call, UsageCollector, chat_cost_from_tokens

log = logging.getLogger(__name__)
URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class ChatError(RuntimeError):
    pass


class OpenRouterChat:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        usage: UsageCollector | None = None,
    ):
        key = api_key if api_key is not None else settings.openrouter_api_key
        if not key:
            raise RuntimeError("No OpenRouter API key")
        self._settings = settings
        self.usage = usage
        self.model = settings.chat_model
        self.fast_model = settings.fast_model or settings.chat_model
        self._key = key
        self._client = client or httpx.AsyncClient(timeout=120)

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        attempts: int = 3,
        purpose: str = "chat",
    ) -> str:
        body: dict = {"model": model or self.model, "messages": messages, "usage": {"include": True}}
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._key}", "X-Title": "Notesman"}

        for attempt in range(1, attempts + 1):
            try:
                res = await self._client.post(URL, headers=headers, json=body)
            except httpx.TransportError as e:
                if attempt == attempts:
                    raise ChatError(f"OpenRouter unreachable: {type(e).__name__}") from e
                await asyncio.sleep(2**attempt)
                continue
            if res.status_code in RETRY_STATUS and attempt < attempts:
                await asyncio.sleep(2**attempt)
                continue
            if res.status_code >= 400:
                raise ChatError(f"OpenRouter chat failed ({res.status_code}): {res.text[:300]}")
            try:
                data = res.json()
                self._record(data, body["model"], purpose)
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError, TypeError) as e:
                raise ChatError(f"OpenRouter returned an unexpected response: {res.text[:200]}") from e
            if not content or not content.strip():
                if attempt == attempts:
                    raise ChatError("The model returned an empty answer")
                continue
            return content
        raise ChatError("OpenRouter failed")  # pragma: no cover

    def _record(self, data: dict, model: str, purpose: str) -> None:
        """Note what this call cost: OpenRouter's own figure when present, else tokens times the configured price."""
        if self.usage is None:
            return
        u = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(u, dict):
            return
        tin, tout = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
        cost = u.get("cost")
        estimated = not isinstance(cost, (int, float))
        if estimated:
            cost = chat_cost_from_tokens(self._settings, tin, tout)
        self.usage.add(Call("chat", purpose, model, tin, tout, float(cost), estimated))

    async def complete_json(self, messages: list[dict], model: str | None = None, *, purpose: str = "chat") -> dict:
        """Ask for JSON and parse it leniently (some models wrap it in prose or fences)."""
        text = await self.complete(messages, model, temperature=0, json_mode=True, purpose=purpose)
        return parse_json(text)

    async def aclose(self) -> None:
        await self._client.aclose()


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        out = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ChatError("Model did not return JSON") from None
        try:
            out = json.loads(m.group(0))
        except ValueError as e:
            raise ChatError("Model returned malformed JSON") from e
    if not isinstance(out, dict):
        raise ChatError("Model returned JSON that is not an object")
    return out
