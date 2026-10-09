from __future__ import annotations

import json
import os
from typing import cast

import httpx
from pydantic import ValidationError

from agentlab.models import ModelResponse


class OpenAICompatibleError(RuntimeError):
    pass


class OpenAICompatibleAdapter:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("pass either client or transport, not both")
        resolved_base_url = (
            base_url or os.getenv("AGENTLAB_BASE_URL") or "http://localhost:11434/v1"
        )
        self.base_url = resolved_base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("AGENTLAB_API_KEY", "")
        self.model_name = model or os.getenv("AGENTLAB_MODEL") or "qwen2.5:7b"
        self._owns_client = client is None
        self._client = client or httpx.Client(transport=transport, timeout=timeout)

    def complete(self, prompt: str, step: int) -> ModelResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request_payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=request_payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenAICompatibleError(f"Chat Completions request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise OpenAICompatibleError(
                f"Chat Completions request failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenAICompatibleError(f"Chat Completions request failed: {exc}") from exc

        try:
            envelope = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise OpenAICompatibleError("Chat Completions response contained invalid JSON") from exc
        if not isinstance(envelope, dict):
            raise OpenAICompatibleError("Chat Completions response must be a JSON object")
        envelope_dict = cast(dict[str, object], envelope)

        choices = envelope_dict.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenAICompatibleError("Chat Completions response is missing choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OpenAICompatibleError("Chat Completions choice must be a JSON object")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise OpenAICompatibleError("Chat Completions choice is missing message")
        content = message.get("content")
        if not isinstance(content, str):
            raise OpenAICompatibleError("Chat Completions message content must be a string")

        try:
            content_payload = json.loads(content)
        except (json.JSONDecodeError, ValueError) as exc:
            raise OpenAICompatibleError(
                "Chat Completions message content is not valid JSON"
            ) from exc
        if not isinstance(content_payload, dict):
            raise OpenAICompatibleError(
                "Chat Completions content must decode to a ModelResponse object"
            )
        model_payload = cast(dict[str, object], content_payload)
        if "token_usage" not in model_payload:
            usage_total = _usage_total(envelope_dict.get("usage"))
            if usage_total is not None:
                model_payload["token_usage"] = usage_total

        try:
            return ModelResponse.model_validate(model_payload)
        except ValidationError as exc:
            raise OpenAICompatibleError(
                f"Chat Completions content could not be parsed as ModelResponse: {exc}"
            ) from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAICompatibleAdapter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _usage_total(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    prompt_tokens = value.get("prompt_tokens")
    completion_tokens = value.get("completion_tokens")
    if (
        isinstance(prompt_tokens, int)
        and not isinstance(prompt_tokens, bool)
        and prompt_tokens >= 0
        and isinstance(completion_tokens, int)
        and not isinstance(completion_tokens, bool)
        and completion_tokens >= 0
    ):
        return prompt_tokens + completion_tokens
    total_tokens = value.get("total_tokens")
    if isinstance(total_tokens, int) and not isinstance(total_tokens, bool):
        return total_tokens if total_tokens >= 0 else None
    return None
