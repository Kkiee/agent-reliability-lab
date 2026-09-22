from __future__ import annotations

from datetime import UTC, datetime

from agentlab.adapters.base import ModelAdapter
from agentlab.events import Event, InMemoryEventSink
from agentlab.models import (
    EventType,
    FinalAnswer,
    RunRecord,
    RunStatus,
)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


class AgentRuntime:
    def __init__(self, adapter: ModelAdapter, event_sink: InMemoryEventSink, seed: int) -> None:
        self._adapter = adapter
        self._event_sink = event_sink
        self._seed = seed

    def run(self, prompt: str, run_id: str) -> RunRecord:
        seq = 0
        prev_hash: str | None = None

        def emit(event_type: EventType, payload: dict[str, object]) -> None:
            nonlocal seq, prev_hash
            seq += 1
            event = Event(
                event_id=f"{run_id}:{seq}",
                run_id=run_id,
                seq=seq,
                type=event_type,
                timestamp=_utc_timestamp(),
                payload=payload,
                prev_hash=prev_hash,
            )
            prev_hash = self._event_sink.append(event).hash

        emit(EventType.RUN_STARTED, {"seed": self._seed, "prompt": prompt})

        steps = 0
        token_usage = 0
        final_answer: str | None = None

        while True:
            steps += 1
            emit(EventType.MODEL_REQUESTED, {"prompt": prompt, "step": steps})
            response = self._adapter.complete(prompt, steps)
            token_usage += response.token_usage
            emit(
                EventType.MODEL_RESPONDED,
                {
                    "action": response.action.model_dump(mode="json"),
                    "token_usage": response.token_usage,
                },
            )
            if isinstance(response.action, FinalAnswer):
                final_answer = response.action.content
                break
            # Tool execution arrives later; fail loudly instead of returning a partial run.
            raise NotImplementedError("tool execution is not part of Task 1")

        emit(
            EventType.RUN_COMPLETED,
            {"final_answer": final_answer, "steps": steps, "token_usage": token_usage},
        )
        return RunRecord(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            final_answer=final_answer,
            steps=steps,
            token_usage=token_usage,
        )