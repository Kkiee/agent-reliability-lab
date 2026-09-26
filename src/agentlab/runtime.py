from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from agentlab.adapters.base import ModelAdapter
from agentlab.events import Event, InMemoryEventSink, compute_state_hash
from agentlab.models import (
    EventType,
    FinalAnswer,
    PolicyConfig,
    RunRecord,
    RunStatus,
    RuntimeState,
    ToolCall,
    ToolResult,
)
from agentlab.policy import PolicyDecisionType, PolicyEngine
from agentlab.store import FileEventStore
from agentlab.tools.base import ToolRegistry
from agentlab.tools.builtin import build_default_registry


def default_clock(seq: int) -> str:
    # Deterministic fallback; callers can inject wall-clock time when needed.
    return datetime.fromtimestamp(seq, UTC).isoformat()


class AgentRuntime:
    def __init__(
        self,
        adapter: ModelAdapter,
        event_sink: InMemoryEventSink | FileEventStore,
        seed: int,
        clock: Callable[[int], str] | None = None,
        tools: ToolRegistry | None = None,
        policy: PolicyEngine | PolicyConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._event_sink = event_sink
        self._seed = seed
        self._clock = clock or default_clock
        self._tools = tools if tools is not None else build_default_registry()
        if policy is None:
            self._policy = PolicyEngine(PolicyConfig())
        elif isinstance(policy, PolicyConfig):
            self._policy = PolicyEngine(policy)
        else:
            self._policy = policy

    def run(self, prompt: str, run_id: str) -> RunRecord:
        seq = 0
        prev_hash: str | None = None
        if isinstance(self._event_sink, FileEventStore):
            self._event_sink.start_run(run_id, {"seed": self._seed, "prompt": prompt})

        def emit(event_type: EventType, payload: dict[str, object]) -> None:
            nonlocal seq, prev_hash
            seq += 1
            event = Event(
                event_id=f"{run_id}:{seq}",
                run_id=run_id,
                seq=seq,
                type=event_type,
                timestamp=self._clock(seq),
                payload=payload,
                prev_hash=prev_hash,
            )
            prev_hash = self._event_sink.append(event).hash

        emit(EventType.RUN_STARTED, {"seed": self._seed, "prompt": prompt})

        state = RuntimeState(run_id=run_id, status=RunStatus.RUNNING)
        model_prompt = prompt
        final_answer: str | None = None

        while True:
            state.status = RunStatus.WAITING_FOR_MODEL
            state.step += 1
            emit(EventType.MODEL_REQUESTED, {"prompt": model_prompt, "step": state.step})
            response = self._adapter.complete(model_prompt, state.step)
            state.token_usage += response.token_usage
            emit(
                EventType.MODEL_RESPONDED,
                {
                    "action": response.action.model_dump(mode="json"),
                    "token_usage": response.token_usage,
                },
            )

            if isinstance(response.action, FinalAnswer):
                final_answer = response.action.content
                state.status = RunStatus.COMPLETED
                state.final_answer = final_answer
                break

            state.status = RunStatus.WAITING_FOR_TOOL
            tool_result = self._handle_tool_call(emit, response.action, state)
            if tool_result is None:
                return self._record_run(state)

            state.tool_results.append(tool_result)
            model_prompt = _prompt_with_tool_result(model_prompt, tool_result)

        emit(
            EventType.RUN_COMPLETED,
            {
                "final_answer": final_answer,
                "steps": state.step,
                "token_usage": state.token_usage,
            },
        )
        return self._record_run(state)

    def _record_run(self, state: RuntimeState) -> RunRecord:
        state_hash = compute_state_hash(state)
        if isinstance(self._event_sink, FileEventStore):
            self._event_sink.write_state(state)
        return RunRecord(
            run_id=state.run_id,
            status=state.status,
            final_answer=state.final_answer,
            steps=state.step,
            token_usage=state.token_usage,
            state_hash=state_hash,
        )

    def _handle_tool_call(
        self,
        emit: Callable[[EventType, dict[str, object]], None],
        call: ToolCall,
        state: RuntimeState,
    ) -> ToolResult | None:
        emit(
            EventType.TOOL_REQUESTED,
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "arguments": call.arguments,
            },
        )

        try:
            spec = self._tools.get(call.tool_name)
        except KeyError:
            spec = None

        decision = self._policy.evaluate(call, spec, state)
        emit(
            EventType.POLICY_EVALUATED,
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "decision": decision.kind.value,
                "reason": decision.reason,
            },
        )
        state.history.append(call)
        state.tool_calls += 1

        if decision.kind == PolicyDecisionType.TERMINATE:
            state.status = RunStatus.TERMINATED
            state.termination_reason = decision.reason
            emit(
                EventType.RUN_TERMINATED,
                {
                    "reason": decision.reason,
                    "steps": state.step,
                    "tool_calls": state.tool_calls,
                    "token_usage": state.token_usage,
                },
            )
            return None

        if decision.kind == PolicyDecisionType.DENY:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=decision.reason,
                metadata={"policy_decision": decision.kind.value},
            )
            if spec is None:
                self._emit_tool_result(emit, EventType.TOOL_FAILED, result)
            return result

        if spec is None:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="unknown_tool",
            )
            self._emit_tool_result(emit, EventType.TOOL_FAILED, result)
            return result

        emit(
            EventType.TOOL_STARTED,
            {"call_id": call.call_id, "tool_name": call.tool_name},
        )
        try:
            arguments = spec.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="invalid_tool_input",
                metadata={"validation_error": str(exc)},
            )
            self._emit_tool_result(emit, EventType.TOOL_FAILED, result)
            return result

        try:
            result = spec.handler(arguments)
        except Exception as exc:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=str(exc) or type(exc).__name__,
                metadata={"exception_type": type(exc).__name__},
            )
        else:
            result = result.model_copy(
                update={"call_id": call.call_id, "tool_name": call.tool_name}
            )

        event_type = EventType.TOOL_SUCCEEDED if result.success else EventType.TOOL_FAILED
        self._emit_tool_result(emit, event_type, result)
        return result

    @staticmethod
    def _emit_tool_result(
        emit: Callable[[EventType, dict[str, object]], None],
        event_type: EventType,
        result: ToolResult,
    ) -> None:
        emit(
            event_type,
            {
                "call_id": result.call_id,
                "tool_name": result.tool_name,
                "result": result.model_dump(mode="json"),
            },
        )


def _prompt_with_tool_result(prompt: str, result: ToolResult) -> str:
    rendered = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prompt}\n\nTool result:\n{rendered}"