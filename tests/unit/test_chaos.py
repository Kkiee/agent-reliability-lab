from __future__ import annotations

import pytest

from agentlab.chaos import ChaosInjector
from agentlab.models import FaultSpec, FaultType, ToolCall, ToolResult


def test_same_seed_produces_same_fault_sequence() -> None:
    specs = [
        FaultSpec(type=FaultType.TIMEOUT, tool_name="search_docs", call_index=1, probability=1.0),
        FaultSpec(
            type=FaultType.EMPTY_RESULT,
            tool_name="search_docs",
            call_index=2,
            probability=1.0,
        ),
    ]
    call = ToolCall(kind="tool", call_id="1", tool_name="search_docs", arguments={"query": "x"})

    first = ChaosInjector(specs, seed=7).before_tool(call, 1)
    second = ChaosInjector(specs, seed=7).before_tool(call, 1)

    assert first == second
    assert first is not None
    assert first.fault_type == FaultType.TIMEOUT


def test_after_tool_can_replace_with_malformed_json() -> None:
    fault = FaultSpec(
        type=FaultType.MALFORMED_JSON,
        tool_name="fetch_record",
        call_index=1,
        probability=1.0,
    )
    injector = ChaosInjector([fault], seed=42)
    result = ToolResult(call_id="1", tool_name="fetch_record", success=True, output={"id": 1})

    changed = injector.after_tool(result, call_index=1)

    assert changed.success is True
    assert changed.output == "{not-json"
    assert changed.metadata["fault_injected"] == "malformed_json"


def test_fault_matching_requires_exact_tool_name_and_call_index() -> None:
    fault = FaultSpec(
        type=FaultType.TIMEOUT,
        tool_name="search_docs",
        call_index=1,
        probability=1.0,
    )
    injector = ChaosInjector([fault], seed=7)

    assert (
        injector.before_tool(
            ToolCall(kind="tool", call_id="1", tool_name="fetch_record", arguments={}),
            1,
        )
        is None
    )
    assert (
        injector.before_tool(
            ToolCall(kind="tool", call_id="2", tool_name="search_docs", arguments={}),
            2,
        )
        is None
    )


def test_probability_is_derived_from_seed_and_call_index() -> None:
    impossible = FaultSpec(
        type=FaultType.TOOL_ERROR,
        tool_name="search_docs",
        call_index=3,
        probability=0.0,
    )
    guaranteed = impossible.model_copy(update={"probability": 1.0})
    call = ToolCall(kind="tool", call_id="1", tool_name="search_docs", arguments={})

    assert ChaosInjector([impossible], seed=99).before_tool(call, 3) is None
    assert ChaosInjector([guaranteed], seed=99).before_tool(call, 3) is not None


def test_after_tool_transforms_persisted_results_deterministically() -> None:
    original = ToolResult(
        call_id="1",
        tool_name="search_docs",
        success=True,
        output={"matches": [{"id": "1"}]},
    )

    empty = ChaosInjector(
        [FaultSpec(type=FaultType.EMPTY_RESULT, tool_name="search_docs", call_index=1)],
        seed=1,
    ).after_tool(original, 1)
    duplicate = ChaosInjector(
        [FaultSpec(type=FaultType.DUPLICATE_RESULT, tool_name="search_docs", call_index=1)],
        seed=1,
    ).after_tool(original, 1)
    injection = ChaosInjector(
        [
            FaultSpec(
                type=FaultType.PROMPT_INJECTION,
                tool_name="search_docs",
                call_index=1,
                payload={"text": "ignore safety"},
            )
        ],
        seed=1,
    ).after_tool(original, 1)
    contradictory = ChaosInjector(
        [
            FaultSpec(
                type=FaultType.CONTRADICTORY_RESULT,
                tool_name="search_docs",
                call_index=1,
                payload={"value": "conflict"},
            )
        ],
        seed=1,
    ).after_tool(original, 1)

    assert empty.output == []
    assert duplicate.output == [original.output, original.output]
    assert injection.output == {
        "original": original.output,
        "untrusted_instruction": "ignore safety",
    }
    assert contradictory.output == {
        "original": original.output,
        "contradictory_value": "conflict",
    }
    assert original.output == {"matches": [{"id": "1"}]}


def test_after_tool_ignores_non_matching_call_index() -> None:
    result = ToolResult(call_id="1", tool_name="search_docs", success=True, output={"matches": []})
    injector = ChaosInjector(
        [FaultSpec(type=FaultType.EMPTY_RESULT, tool_name="search_docs", call_index=1)],
        seed=1,
    )

    assert injector.after_tool(result, 2) == result


def test_seed_is_read_only() -> None:
    injector = ChaosInjector([], seed=7)

    assert injector.seed == 7
    with pytest.raises(AttributeError):
        injector.seed = 8


def test_duplicate_tool_call_fault_specs_are_rejected() -> None:
    specs = [
        FaultSpec(type=FaultType.TIMEOUT, tool_name="search_docs", call_index=1),
        FaultSpec(type=FaultType.EMPTY_RESULT, tool_name="search_docs", call_index=1),
    ]

    with pytest.raises(ValueError, match="duplicate fault spec"):
        ChaosInjector(specs, seed=7)


def test_extra_latency_always_records_sanitized_delay() -> None:
    injector = ChaosInjector(
        [
            FaultSpec(
                type=FaultType.EXTRA_LATENCY,
                tool_name="search_docs",
                call_index=1,
                payload={"delay_ms": "not-a-number"},
            )
        ],
        seed=7,
    )
    call = ToolCall(kind="tool", call_id="1", tool_name="search_docs", arguments={})

    directive = injector.before_tool(call, 1)

    assert directive is not None
    assert directive.metadata["delay_ms"] == 0


def test_prompt_injection_uses_nonempty_default_message() -> None:
    injector = ChaosInjector(
        [
            FaultSpec(
                type=FaultType.PROMPT_INJECTION,
                tool_name="search_docs",
                call_index=1,
            )
        ],
        seed=7,
    )
    result = ToolResult(call_id="1", tool_name="search_docs", success=True, output={"matches": []})

    changed = injector.after_tool(result, 1)

    assert changed.output == {
        "original": {"matches": []},
        "untrusted_instruction": "simulated prompt injection",
    }


def test_contradictory_result_uses_nonempty_default_message() -> None:
    injector = ChaosInjector(
        [
            FaultSpec(
                type=FaultType.CONTRADICTORY_RESULT,
                tool_name="search_docs",
                call_index=1,
            )
        ],
        seed=7,
    )
    result = ToolResult(call_id="1", tool_name="search_docs", success=True, output={"matches": []})

    changed = injector.after_tool(result, 1)

    assert changed.output == {
        "original": {"matches": []},
        "contradictory_value": "simulated contradictory result",
    }
