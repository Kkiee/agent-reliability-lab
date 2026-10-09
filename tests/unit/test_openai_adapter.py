from __future__ import annotations

import json

import httpx
import pytest

from agentlab.adapters.openai_compatible import (
    OpenAICompatibleAdapter,
    OpenAICompatibleError,
)
from agentlab.models import FinalAnswer


def _adapter(handler: httpx.MockTransportHandler) -> OpenAICompatibleAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleAdapter(
        client=client,
        base_url="http://mock.test/v1",
        api_key="test-key",
        model="test-model",
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )


def test_complete_uses_chat_completions_and_parses_model_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://mock.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["messages"] == [{"role": "user", "content": "finish"}]
        return _chat_response(
            json.dumps(
                {
                    "action": {"kind": "final", "content": "done"},
                    "token_usage": 5,
                }
            )
        )

    response = _adapter(handler).complete("finish", step=1)

    assert isinstance(response.action, FinalAnswer)
    assert response.action.content == "done"
    assert response.token_usage == 5


def test_complete_uses_usage_when_content_omits_token_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(json.dumps({"action": {"kind": "final", "content": "done"}}))

    response = _adapter(handler).complete("finish", step=1)

    assert response.token_usage == 5


def test_complete_reads_configuration_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTLAB_BASE_URL", "http://env.test/v1/")
    monkeypatch.setenv("AGENTLAB_API_KEY", "env-key")
    monkeypatch.setenv("AGENTLAB_MODEL", "env-model")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://env.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer env-key"
        assert json.loads(request.content)["model"] == "env-model"
        return _chat_response(
            json.dumps(
                {
                    "action": {"kind": "final", "content": "done"},
                    "token_usage": 5,
                }
            )
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = OpenAICompatibleAdapter(client=client).complete("finish", step=1)

    assert response.action == FinalAnswer(content="done")


@pytest.mark.parametrize("status_code", [400, 500])
def test_complete_reports_http_errors(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "failed"})

    with pytest.raises(OpenAICompatibleError, match=str(status_code)):
        _adapter(handler).complete("finish", step=1)


def test_complete_reports_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(OpenAICompatibleError, match="timed out"):
        _adapter(handler).complete("finish", step=1)


def test_complete_reports_invalid_envelope_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", headers={"content-type": "application/json"})

    with pytest.raises(OpenAICompatibleError, match="invalid JSON"):
        _adapter(handler).complete("finish", step=1)


def test_complete_requires_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage": {}}, headers={"content-type": "application/json"})

    with pytest.raises(OpenAICompatibleError, match="choices"):
        _adapter(handler).complete("finish", step=1)


def test_complete_rejects_invalid_model_response_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(json.dumps({"not": "a model response"}))

    with pytest.raises(OpenAICompatibleError, match="ModelResponse"):
        _adapter(handler).complete("finish", step=1)
