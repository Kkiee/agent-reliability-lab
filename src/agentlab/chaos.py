from __future__ import annotations

import copy
import random

from pydantic import Field

from agentlab.models import FaultSpec, FaultType, StrictModel, ToolCall, ToolResult

_DEFAULT_MESSAGES = {
    FaultType.TIMEOUT: "simulated timeout",
    FaultType.TOOL_ERROR: "simulated tool error",
    FaultType.MALFORMED_JSON: "simulated malformed JSON",
    FaultType.EMPTY_RESULT: "simulated empty result",
    FaultType.EXTRA_LATENCY: "simulated extra latency",
    FaultType.DUPLICATE_RESULT: "simulated duplicate result",
    FaultType.PROMPT_INJECTION: "simulated prompt injection",
    FaultType.CONTRADICTORY_RESULT: "simulated contradictory result",
}


class FaultDirective(StrictModel):
    fault_type: FaultType
    message: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ChaosInjector:
    def __init__(self, specs: list[FaultSpec], seed: int) -> None:
        seen_calls: set[tuple[str, int]] = set()
        for spec in specs:
            key = (spec.tool_name, spec.call_index)
            if key in seen_calls:
                raise ValueError(
                    f"duplicate fault spec for tool_name={spec.tool_name!r}, "
                    f"call_index={spec.call_index}"
                )
            seen_calls.add(key)
        self._specs = list(specs)
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    def before_tool(self, call: ToolCall, call_index: int) -> FaultDirective | None:
        spec = self._matching_spec(call.tool_name, call_index)
        if spec is None or not self._should_inject(spec, call_index):
            return None

        metadata = dict(spec.payload)
        if spec.type == FaultType.EXTRA_LATENCY:
            metadata["delay_ms"] = _delay_ms(spec.payload)

        return FaultDirective(
            fault_type=spec.type,
            message=_message(spec),
            metadata=metadata,
        )

    def after_tool(self, result: ToolResult, call_index: int) -> ToolResult:
        spec = self._matching_spec(result.tool_name, call_index)
        if (
            spec is None
            or not result.success
            or not self._should_inject(spec, call_index)
            or spec.type
            in {FaultType.TIMEOUT, FaultType.TOOL_ERROR, FaultType.EXTRA_LATENCY}
        ):
            return result

        output = _transform_output(spec, copy.deepcopy(result.output))
        metadata = dict(result.metadata)
        metadata["fault_injected"] = spec.type.value
        return result.model_copy(update={"output": output, "metadata": metadata})

    def _matching_spec(self, tool_name: str, call_index: int) -> FaultSpec | None:
        return next(
            (
                spec
                for spec in self._specs
                if spec.tool_name == tool_name and spec.call_index == call_index
            ),
            None,
        )

    def _should_inject(self, spec: FaultSpec, call_index: int) -> bool:
        # Probability is scoped to one call index so earlier failures cannot perturb later runs.
        return random.Random(self._seed + call_index).random() < spec.probability


def _delay_ms(payload: dict[str, object]) -> int | float:
    value = payload.get("delay_ms", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    return value


def _transform_output(spec: FaultSpec, output: object | None) -> object | None:
    if spec.type == FaultType.MALFORMED_JSON:
        configured = spec.payload.get("output", "{not-json")
        return configured if isinstance(configured, str) else "{not-json"
    if spec.type == FaultType.EMPTY_RESULT:
        return []
    if spec.type == FaultType.DUPLICATE_RESULT:
        return [output, copy.deepcopy(output)]
    if spec.type == FaultType.PROMPT_INJECTION:
        text = spec.payload.get("text")
        if text is None:
            text = _message(spec)
        return {
            "original": output,
            "untrusted_instruction": text if isinstance(text, str) else str(text),
        }
    if spec.type == FaultType.CONTRADICTORY_RESULT:
        value = spec.payload.get("value")
        if value is None:
            value = _message(spec)
        return {"original": output, "contradictory_value": value}
    return output


def _message(spec: FaultSpec) -> str:
    return spec.message or _DEFAULT_MESSAGES[spec.type]
