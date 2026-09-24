from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentlab.models import ToolResult
from agentlab.tools.base import ToolRegistry
from agentlab.tools.builtin import MessageRecorder, build_default_registry


def invoke(registry: ToolRegistry, name: str, arguments: dict[str, object]) -> ToolResult:
    spec = registry.get(name)
    validated = spec.input_model.model_validate(arguments)
    return spec.handler(validated)


def test_calculate_returns_numeric_result() -> None:
    registry = build_default_registry()

    result = invoke(registry, "calculate", {"expression": "(2 + 3) * 4"})

    assert result.success is True
    assert result.output == 20


def test_calculate_division_by_zero_fails_without_raising() -> None:
    registry = build_default_registry()

    result = invoke(registry, "calculate", {"expression": "1 / 0"})

    assert result.success is False
    assert result.error == "division_by_zero"
    assert result.output is None


def test_calculate_rejects_non_arithmetic_input() -> None:
    registry = build_default_registry()
    spec = registry.get("calculate")

    with pytest.raises(ValidationError):
        spec.input_model.model_validate({"expression": "__import__('os').system('whoami')"})


def test_calculate_rejects_non_ascii_digits() -> None:
    registry = build_default_registry()
    spec = registry.get("calculate")

    with pytest.raises(ValidationError):
        spec.input_model.model_validate({"expression": "١ + ١"})


def test_unknown_tool_fails_registry_lookup() -> None:
    registry = build_default_registry()

    with pytest.raises(KeyError, match="unknown"):
        registry.get("unknown")


def test_send_message_only_records_in_memory() -> None:
    recorder = MessageRecorder()
    registry = build_default_registry(recorder=recorder)

    result = invoke(registry, "send_message", {"recipient": "user-1", "text": "hello"})

    assert result.success is True
    assert result.output == {"recorded": True}
    assert recorder.messages == [{"recipient": "user-1", "text": "hello"}]


def test_search_docs_is_deterministic_for_a_corpus() -> None:
    registry = build_default_registry()
    corpus = {
        "b": "Beta retry guidance",
        "a": "Alpha retry guidance",
        "c": "Unrelated",
    }

    result = invoke(registry, "search_docs", {"query": "retry", "corpus": corpus})

    assert result.success is True
    assert result.output == {
        "matches": [
            {"id": "a", "text": "Alpha retry guidance"},
            {"id": "b", "text": "Beta retry guidance"},
        ]
    }


def test_fetch_record_returns_an_in_memory_record() -> None:
    registry = build_default_registry()
    records = {"42": {"name": "Ada", "active": True}}

    result = invoke(registry, "fetch_record", {"record_id": "42", "records": records})

    assert result.success is True
    assert result.output == {"name": "Ada", "active": True}


def test_default_registry_has_stable_sorted_names() -> None:
    registry = build_default_registry()

    assert registry.names() == ["calculate", "fetch_record", "search_docs", "send_message"]