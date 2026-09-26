from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import ValidationError

from agentlab.events import Event, compute_state_hash
from agentlab.models import EventType, RunRecord, RunStatus, RuntimeState, ToolCall, ToolResult
from agentlab.store import EventIntegrityError, FileEventStore


class ReplayMismatchError(EventIntegrityError):
    pass


class ReplayEngine:
    def __init__(self, root: Path | str | FileEventStore) -> None:
        self._store = root if isinstance(root, FileEventStore) else FileEventStore(root)

    def replay(self, run_id: str) -> RunRecord:
        events = self._store.read_events(run_id)
        if not events or events[0].type != EventType.RUN_STARTED:
            raise EventIntegrityError("event log must start with RunStarted")

        state = RuntimeState(run_id=run_id)
        policy_denied_calls: set[str] = set()
        for event in events:
            self._apply_event(state, event, policy_denied_calls)

        replay_hash = compute_state_hash(state)
        persisted_hash = self._store.load_state_hash(run_id)
        if replay_hash != persisted_hash:
            raise ReplayMismatchError(
                f"replayed state hash {replay_hash} does not match persisted hash {persisted_hash}"
            )

        return RunRecord(
            run_id=run_id,
            status=state.status,
            final_answer=state.final_answer,
            steps=state.step,
            token_usage=state.token_usage,
            state_hash=replay_hash,
        )

    def _apply_event(
        self,
        state: RuntimeState,
        event: Event,
        policy_denied_calls: set[str],
    ) -> None:
        if event.type == EventType.RUN_STARTED:
            state.status = RunStatus.RUNNING
        elif event.type == EventType.MODEL_RESPONDED:
            state.step += 1
            state.token_usage += _required_int(event.payload, "token_usage")
        elif event.type == EventType.TOOL_REQUESTED:
            call = ToolCall(
                call_id=_required_str(event.payload, "call_id"),
                tool_name=_required_str(event.payload, "tool_name"),
                arguments=_required_dict(event.payload, "arguments"),
            )
            state.history.append(call)
            state.tool_calls += 1
        elif event.type == EventType.POLICY_EVALUATED:
            if event.payload.get("decision") == "deny":
                result = _denied_tool_result(event.payload)
                state.tool_results.append(result)
                policy_denied_calls.add(result.call_id)
        elif event.type in {EventType.TOOL_SUCCEEDED, EventType.TOOL_FAILED}:
            result = _event_tool_result(event.payload)
            if result.call_id not in policy_denied_calls:
                state.tool_results.append(result)
        elif event.type == EventType.RUN_COMPLETED:
            state.final_answer = _required_str(event.payload, "final_answer")
            state.status = RunStatus.COMPLETED
        elif event.type == EventType.RUN_FAILED:
            reason = event.payload.get("reason") or event.payload.get("error")
            if isinstance(reason, str):
                state.termination_reason = reason
            state.status = RunStatus.FAILED
        elif event.type == EventType.RUN_TERMINATED:
            state.termination_reason = _required_str(event.payload, "reason")
            state.status = RunStatus.TERMINATED


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise EventIntegrityError(f"event payload field {key!r} must be a string")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventIntegrityError(f"event payload field {key!r} must be a non-negative integer")
    return value


def _required_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise EventIntegrityError(f"event payload field {key!r} must be an object")
    return cast(dict[str, object], value)


def _event_tool_result(payload: dict[str, object]) -> ToolResult:
    value = payload.get("result")
    if not isinstance(value, dict):
        raise EventIntegrityError("tool result event must contain an object result")
    try:
        return ToolResult.model_validate(value)
    except ValidationError as exc:
        raise EventIntegrityError("invalid tool result event payload") from exc


def _denied_tool_result(payload: dict[str, object]) -> ToolResult:
    return ToolResult(
        call_id=_required_str(payload, "call_id"),
        tool_name=_required_str(payload, "tool_name"),
        success=False,
        error=_required_str(payload, "reason"),
        metadata={"policy_decision": "deny"},
    )
