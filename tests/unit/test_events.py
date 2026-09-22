from agentlab.events import Event, compute_event_hash
from agentlab.models import EventType


def test_event_hash_is_stable_for_same_payload() -> None:
    event = Event(
        event_id="event-1",
        run_id="run-1",
        seq=1,
        type=EventType.RUN_STARTED,
        timestamp="2026-09-22T10:00:00Z",
        payload={"seed": 42},
        prev_hash=None,
    )

    first = compute_event_hash(event)
    second = compute_event_hash(event.model_copy(update={"hash": "ignored"}))

    assert first == second
