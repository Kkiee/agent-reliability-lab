from __future__ import annotations

import hashlib
import json

from pydantic import Field

from agentlab.models import EventType, RuntimeState, StrictModel


class Event(StrictModel):
    event_id: str
    run_id: str
    seq: int = Field(ge=1)
    type: EventType
    timestamp: str
    payload: dict[str, object]
    prev_hash: str | None = None
    hash: str = ""


def canonical_payload(event: Event) -> bytes:
    data = event.model_dump(mode="json", exclude={"hash"})
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def compute_event_hash(event: Event) -> str:
    return hashlib.sha256(canonical_payload(event)).hexdigest()


def compute_state_hash(state: RuntimeState) -> str:
    data = state.model_dump(mode="json")
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def append(self, event: Event) -> Event:
        event.hash = compute_event_hash(event)
        self.events.append(event)
        return event
