from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

import httpx

from smart_house_hunting.config.models import LLMConfig


class LLMProvider(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: int = 180) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key or 'ollama-local'}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.post(
                    "chat/completions",
                    json={
                        "model": self.model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                retryable = (
                    not isinstance(error, httpx.HTTPStatusError)
                    or error.response.status_code == 429
                    or error.response.status_code >= 500
                )
                if not retryable or attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
        raise RuntimeError("LLM request failed") from last_error


def build_provider(config: LLMConfig, name: str | None = None) -> OpenAICompatibleProvider:
    provider_name = name or config.default_provider
    if provider_name not in config.providers:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
    selected = config.providers[provider_name]
    key = os.environ.get(selected.api_key_env)
    is_local = provider_name == "ollama" or selected.base_url.startswith(
        ("http://localhost", "http://127.0.0.1")
    )
    if not key and not is_local:
        raise ValueError(f"Missing API key environment variable for {provider_name}")
    return OpenAICompatibleProvider(selected.base_url, selected.model, key, config.timeout_seconds)


class FakeLLMProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if not self.responses:
            raise RuntimeError("No fake LLM response remains")
        return self.responses.pop(0)

    async def close(self) -> None:
        return None
